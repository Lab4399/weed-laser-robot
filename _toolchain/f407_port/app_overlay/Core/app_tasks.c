/**
 * @file    app_tasks.c
 * @brief   FreeRTOS 任务实现
 */
#include "app_tasks.h"
#include "app_config.h"

#include "../drivers/uart_link.h"
#include "../drivers/motor.h"
#include "../drivers/servo.h"
#include "../control/motion.h"
#include "../services/safety.h"
#include "../services/param.h"

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"

/* ===========================================================================
 *  ITM/SWO 调试输出
 *
 *  用 SWO 而不是主链路 UART：
 *    · 主链路 UART 已被 OpenMV 占用，插打印会污染协议流
 *       （F407 的 TX 会进入 OpenMV 的 RX，虽然当前 OpenMV 不解析，
 *         但一旦后续加下行命令就会互相干扰；更重要的是双向都有数据时
 *         示波器抓包会变得难以判读）
 *    · SWO 不占用任何引脚资源（复用 SWD 的 SWO 脚），无额外布线
 *    · 无阻塞，写 ITM 寄存器即可，不会拖慢任务
 *  代价：需要调试器开启 SWO，且要按系统时钟配置 trace 频率。
 * =========================================================================== */
#define ITM_PORT0  (*(volatile uint32_t *)0xE0000000u)

static void dbg_puts(const char *s)
{
    while (*s) {
        while (ITM_PORT0 == 0u) { /* 等待上一次写入被取走 */ }
        ITM_PORT0 = (uint32_t)(uint8_t)(*s++);
    }
}

static void dbg_u32(uint32_t v)
{
    char buf[12];
    int i = 11;
    buf[11] = '\0';
    if (v == 0) { dbg_puts("0"); return; }
    while (v > 0 && i > 0) {
        buf[--i] = (char)('0' + (v % 10u));
        v /= 10u;
    }
    dbg_puts(&buf[i]);
}

/* ===========================================================================
 *  共享目标（单生产者 / 单消费者）
 * =========================================================================== */
static VisionTarget   s_sh_target;
static volatile uint32_t s_sh_seq;        /* 协议帧序号，用于一致性检查 */
static volatile uint32_t s_sh_lost;       /* 自上次有效目标以来的帧数 */
static volatile uint32_t s_sh_good;       /* 有效帧总数 */

bool app_get_target(VisionTarget *out, uint32_t *lost_frames)
{
    if (out == NULL) return false;

    uint32_t seq_before, seq_after;

    /* 读-校验-重读。VisionTarget 有 30 字节左右，
     * 在 32 位 MCU 上不是一次原子读，必须防止读到"写了一半"的结构。
     * 用序号做前后校验比加锁便宜，且不会在控制周期里引起优先级反转。 */
    do {
        seq_before = s_sh_seq;
        *out = s_sh_target;
        seq_after = s_sh_seq;
    } while (seq_before != seq_after);

    if (lost_frames) *lost_frames = s_sh_lost;
    return (out->cls == VCLS_WEED);
}

uint32_t app_good_frames(void)
{
    return s_sh_good;
}

/* ===========================================================================
 *  任务：视觉接收与协议解析
 * =========================================================================== */
static vision_proto_t s_proto;

static void task_vision(void *arg)
{
    (void)arg;
    uint8_t buf[64];

    for (;;) {
        /* ★ 心跳只代表"本任务还在被调度"，与"有没有收到帧"无关。
         *
         * 曾经把心跳放在"解析成功"分支里，本意是让它同时覆盖 UART 停摆，
         * 实际后果是：相机没接 / 没上电 / 烧录后还没重启时，视觉心跳永远是 0，
         * 开机 2 秒后必定触发 FAULT_TASK_STALL 并锁死 —— 整机再也起不来。
         * 而"链路上没有帧"本来就有专门的判据（safety 的 LINK_TIMEOUT 分级 +
         * 上车宽限期），两者必须分开，否则一个故障会掩盖另一个。 */
        safety_heartbeat(HB_VISION);

        uint16_t n = uart_link_read(buf, sizeof(buf));
        if (n > 0) {
            for (uint16_t i = 0; i < n; i++) {
                if (vision_proto_feed(&s_proto, buf[i])) {
                    /* --- 解析成功 --- */
                    s_sh_target = s_proto.last;
                    s_sh_seq++;
                    s_sh_good++;
                    s_sh_lost = 0;

                    safety_on_valid_frame();
                }
            }
        }

        /* CRC 错误计数同步给安全模块，用于突发错误率判定 */
        static uint32_t last_crc = 0;
        if (s_proto.stats.err_crc != last_crc) {
            for (uint32_t i = last_crc; i < s_proto.stats.err_crc; i++) {
                safety_on_crc_error();
            }
            last_crc = s_proto.stats.err_crc;
        }

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

/* ===========================================================================
 *  任务：运动控制
 * =========================================================================== */
static void task_motion(void *arg)
{
    (void)arg;
    const TickType_t period = pdMS_TO_TICKS(CTRL_PERIOD_MS);

    for (;;) {
        /* 本任务同时承担"控制律"与"运动输出"两项职责，两个心跳都要喂。
         * 原代码只喂了 HB_MOTION，HB_CONTROL 从头到尾没有任何人更新，
         * 于是开机 2 秒（SAFETY_TASK_STALL_MS × 10）后必然 TASK_STALL。 */
        safety_heartbeat(HB_CONTROL);
        safety_heartbeat(HB_MOTION);

        VisionTarget t;
        uint32_t lost = 0;
        bool has_target = app_get_target(&t, &lost);

        /* 控制律只在自动模式下产出期望值；其他状态下 safety 已经
         * 通过 motion_request_stop() 把期望值清零了。 */
        if (!has_target) {
            t.cls = VCLS_NONE;
        }
        motion_command(&t, lost);

        /* 限速输出。即使期望值突变，这里也只会按 slew_step 逐步逼近。 */
        motion_tick();

        vTaskDelay(period);
    }
}

/* ===========================================================================
 *  任务：安全
 * =========================================================================== */
static void task_safety(void *arg)
{
    (void)arg;
    const TickType_t period = pdMS_TO_TICKS(1);
    uint16_t servo_div = 0;

    for (;;) {
        safety_tick_1ms();

        /* 舵机缓动。放在 1 ms 任务里按分频推进，
         * 保证缓动节奏不受控制任务负载波动影响。 */
        if (++servo_div >= SERVO_SLEW_INTERVAL_MS) {
            servo_div = 0;
            servo_update();
        }

        vTaskDelay(period);
    }
}

/* ===========================================================================
 *  任务：诊断
 * =========================================================================== */
static void task_diag(void *arg)
{
    (void)arg;

    for (;;) {
        safety_snapshot_t s;
        safety_get_snapshot(&s);

        dbg_puts("[diag] state=");
        dbg_puts(safety_state_name(s.state));
        dbg_puts(" fault=");
        dbg_puts(safety_fault_name(s.fault));
        dbg_puts(" frames=");
        dbg_u32(s.good_frames);
        dbg_puts(" crc=");
        dbg_u32(s_proto.stats.err_crc);
        dbg_puts(" gap=");
        dbg_u32(s_proto.stats.seq_gap);
        dbg_puts(" ovf=");
        dbg_u32(uart_link_stats()->ring_overflow);
        dbg_puts(" ore=");
        dbg_u32(uart_link_stats()->ore_err);
        dbg_puts(" iwdg=");
        dbg_u32(s.iwdg_resets);
        dbg_puts("\r\n");

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

/* ===========================================================================
 *  静态分配
 *
 *  本项目不支持动态分配（configSUPPORT_DYNAMIC_ALLOCATION = 0）。
 *  理由：堆碎片与分配失败在 7×24 场景下是不可复现故障的主要来源，
 *  而本项目的任务数、栈大小在编译期完全已知 —— 没有任何理由用堆。
 * =========================================================================== */
static StaticTask_t s_tcb_safety, s_tcb_motion, s_tcb_vision, s_tcb_diag;

static StackType_t s_stk_safety[TASK_STACK_SAFETY / sizeof(StackType_t)];
static StackType_t s_stk_motion[TASK_STACK_MOTION / sizeof(StackType_t)];
static StackType_t s_stk_vision[TASK_STACK_VISION / sizeof(StackType_t)];
static StackType_t s_stk_diag[TASK_STACK_PARAM   / sizeof(StackType_t)];

void app_tasks_start(void)
{
    vision_proto_init(&s_proto);
    motion_init();

    xTaskCreateStatic(task_safety, "safety",
                      TASK_STACK_SAFETY / sizeof(StackType_t), NULL,
                      TASK_PRIO_SAFETY, s_stk_safety, &s_tcb_safety);

    xTaskCreateStatic(task_motion, "motion",
                      TASK_STACK_MOTION / sizeof(StackType_t), NULL,
                      TASK_PRIO_CONTROL, s_stk_motion, &s_tcb_motion);

    xTaskCreateStatic(task_vision, "vision",
                      TASK_STACK_VISION / sizeof(StackType_t), NULL,
                      TASK_PRIO_VISION, s_stk_vision, &s_tcb_vision);

    /* 诊断任务优先级必须最低（1）。
     * 它做的是阻塞式 SWO 输出，放到高优先级会挤占安全与控制任务的执行窗口。 */
    xTaskCreateStatic(task_diag, "diag",
                      TASK_STACK_PARAM / sizeof(StackType_t), NULL,
                      1u, s_stk_diag, &s_tcb_diag);

    vTaskStartScheduler();

    /* 调度器正常启动后不会走到这里。走到这里意味着内存不足或被抢占。 */
    for (;;) { }
}
