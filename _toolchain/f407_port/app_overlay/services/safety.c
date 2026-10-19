/**
 * @file    safety.c
 * @brief   系统状态机与安全策略实现
 */
#include "safety.h"
#include "../Core/app_config.h"
#include "../drivers/motor.h"
#include "../drivers/servo.h"
#include "../control/motion.h"

#include "stm32f4xx_hal.h"
#include <string.h>

extern IWDG_HandleTypeDef hiwdg;

/* ------------------------------------------------------------------------- */
static volatile sys_state_t  s_state;
static volatile fault_code_t s_fault;
static volatile bool         s_estop;
static volatile bool         s_auto_requested;

static uint32_t s_last_frame_ms;      /* 最后一次收到有效帧的时刻 */
static uint32_t s_uptime_ms;
static uint32_t s_good_frames;
static uint32_t s_crc_errors;
static uint32_t s_crc_window;         /* 本次统计窗口内的 CRC 错误数 */
static uint32_t s_crc_window_start;
static uint32_t s_iwdg_resets;
static bool     s_link_ever_alive;

static volatile uint32_t s_hb_last[HB_COUNT_];

/* ---------------------------------------------------------------------------
 * 连续 IWDG 复位计数
 *
 * ⚠️ 必须放在 .noinit 段里。普通 static 变量会在每次复位时被 C 运行时
 *    重新初始化，计数永远是 0，于是"连续 3 次看门狗复位判定固件异常"
 *    这条规则永远不会触发。
 *
 * gcc 的属性写法如下；同时需要在链接脚本（STM32F407ZGTx_FLASH.ld）里
 * 加入 .noinit 段，否则会落到 .bss 里，属性不起作用：
 *
 *   .noinit (NOLOAD) :
 *   {
 *     . = ALIGN(4);
 *     *(.noinit)
 *     . = ALIGN(4);
 *   } >RAM
 *
 * 该段在 startup 的 __libc_init_array 之前由 Reset_Handler 跳过清零。
 * 若链接脚本未定义此段，编译器只会给一条 warning 并把它并入 .bss ——
 * 功能静默失效，很隐蔽，务必在首次编译后确认 map 文件里有 .noinit。
 * ------------------------------------------------------------------------- */
static volatile uint32_t s_iwdg_reset_streak
    __attribute__((section(".noinit")));

/* ------------------------------------------------------------------------- */
static void enter_state(sys_state_t s)
{
    if (s_state == s) return;
    s_state = s;

    switch (s) {
    case SYS_INIT:
    case SYS_IDLE:
    case SYS_FAULT:
        motor_set_both(0, 0);
        motor_enable(false);
        motion_request_stop();
        break;

    case SYS_SAFE_STOP:
        /* 只切功率输出，保持 UART/通信在线。
         * 全部关掉会让现场只能拆机排查 —— 这与"可远程诊断"的目标冲突。 */
        motion_request_stop();
        motor_set_both(0, 0);
        motor_enable(false);
        break;

    case SYS_AUTO:
        motor_enable(true);
        break;
    }
}

/* ------------------------------------------------------------------------- */
void safety_init(void)
{
    s_state = SYS_INIT;
    s_fault = FAULT_NONE;
    s_estop = false;
    s_auto_requested = false;
    s_last_frame_ms = 0;
    s_uptime_ms = 0;
    s_good_frames = 0;
    s_crc_errors = 0;
    s_crc_window = 0;
    s_crc_window_start = 0;
    s_link_ever_alive = false;
    /* s_hb_last 是 volatile（在 ISR 与任务间共享），
     * 不能用 memset —— 会丢弃 volatile 限定，编译器会告警，
     * 且优化后可能被错误地消除。显式循环最稳妥。 */
    for (uint8_t i = 0; i < HB_COUNT_; i++) {
        s_hb_last[i] = 0;
    }

    /* ---- 判定上次复位原因 ----
     * ⚠️ 读完必须立即写 RMVF 清除，否则这些标志会一直累积，
     *    下次复位时无法区分"这次是看门狗复位"还是"很久以前发生过一次"。 */
    uint32_t csr = RCC->CSR;

    if (csr & RCC_CSR_IWDGRSTF) {
        s_iwdg_reset_streak++;
    } else if (csr & (RCC_CSR_PORRSTF | RCC_CSR_PINRSTF | RCC_CSR_BORRSTF)) {
        /* 真正的冷启动：清空连续计数，否则设备跑几个月后
         * 会因为没有断电而累积到阈值，凭空进入 FAULT。 */
        s_iwdg_reset_streak = 0;
    }

    s_iwdg_resets = s_iwdg_reset_streak;

    __HAL_RCC_CLEAR_RESET_FLAGS();

    /* 连续多次看门狗复位 ⇒ 固件本身有缺陷，自动恢复只会陷入复位循环。
     * 直接锁死，等人工介入 —— 这比"复位后继续跑"安全得多。 */
    if (s_iwdg_reset_streak >= SAFETY_MAX_IWDG_RESETS) {
        s_fault = FAULT_IWDG_REPEAT;
        s_state = SYS_FAULT;
    }

    /* ⚠️ 必须用 s_uptime_ms 的时间基准（此处为 0），不能用 HAL_GetTick()。
     * 两者起点不同：s_uptime_ms 由本模块从 0 开始累加，HAL_GetTick() 从
     * HAL_Init 起算。只要 HSE 锁定耗时超过 1ms，HAL_GetTick() 就会大于
     * s_uptime_ms，随后 safety_tick_1ms 里的 `s_uptime_ms - s_hb_last[i]`
     * 按无符号运算下溢成 0xFFFFFFxx，直接越过 2s 门限 —— 开机电平上就
     * 判 TASK_STALL 并锁死。这个 bug 的复现与否完全取决于晶振启动快慢，
     * 属于最典型的"换块板子就好了"型间歇故障。 */
    for (uint8_t i = 0; i < HB_COUNT_; i++) {
        s_hb_last[i] = 0;
    }

    /* ★ 初始化完成必须显式落到 IDLE。
     *
     * 原代码到这里就返回了，s_state 一直停在 SYS_INIT。而"进入自动模式"的
     * 条件是 `s_state == SYS_IDLE && s_auto_requested`，INIT 永远不满足 ——
     * 整机从外部看就是"上电没反应"：电机不转、状态机不推进、也不报故障。
     * 这是最难查的一类问题：所有外设都对、内存也对，就是不动。
     *
     * 放在最后一步做，是为了让前面所有自检（复位原因判定、streak 判定）
     * 有机会先把状态改成 FAULT —— 有故障时不允许降级成 IDLE。 */
    if (s_state == SYS_INIT) {
        enter_state(SYS_IDLE);
    }
}

/* ------------------------------------------------------------------------- */
void safety_heartbeat(safety_hb_t id)
{
    if (id < HB_COUNT_) {
        s_hb_last[id] = s_uptime_ms;
    }
}

void safety_on_valid_frame(void)
{
    s_last_frame_ms = s_uptime_ms;
    s_good_frames++;
    s_link_ever_alive = true;
}

void safety_on_crc_error(void)
{
    s_crc_errors++;
    s_crc_window++;
}

void safety_raise_fault(fault_code_t code)
{
    /* 故障只允许"升级"，不允许被后来的低等级故障覆盖。
     * 否则一次急停可能被随后的链路超时覆盖掉，现场看到的原因就是错的。 */
    if (s_fault == FAULT_NONE || code >= FAULT_ESTOP) {
        s_fault = code;
    }

    /* 锁死类故障直接进 FAULT；其余先走安全停机 */
    switch (code) {
    case FAULT_ESTOP:
    case FAULT_TASK_STALL:
    case FAULT_IWDG_REPEAT:
    case FAULT_PARAM_LOST:
        enter_state(SYS_FAULT);
        break;
    default:
        if (s_state == SYS_AUTO) enter_state(SYS_SAFE_STOP);
        break;
    }
}

void safety_clear_fault(void)
{
    if (s_state != SYS_FAULT) return;
    if (s_estop) return;          /* 急停未释放时不允许清故障 */
    s_fault = FAULT_NONE;
    s_crc_window = 0;
    enter_state(SYS_IDLE);
}

void safety_request_auto(bool enable)
{
    s_auto_requested = enable;
    if (!enable && s_state == SYS_AUTO) {
        enter_state(SYS_IDLE);
    }
}

/* ---------------------------------------------------------------------------
 * 急停 ISR
 *
 * ⚠️ 本函数运行在中优先级 ISR 上下文（PRIO 1），因此：
 *    · 不调用任何 RTOS API
 *    · 不做日志输出
 *    · 只做"置标志 + 直接切驱动器使能"这两件绝对必要的事
 *
 * 直接操作 GPIO 而不是走 motor_enable()，是为了不依赖该函数内部的状态判断
 * —— 急停路径上任何依赖都是风险。
 * ------------------------------------------------------------------------- */
void safety_estop_isr(void)
{
    s_estop = true;
    s_fault = FAULT_ESTOP;

    /* 硬件级切断：直接把驱动器的 STBY 拉低 */
    GPIOB->BSRR = (uint32_t)GPIO_PIN_11 << 16U;   /* PB11 置低 */
}

bool safety_estop_active(void)
{
    return s_estop;
}

/* ---------------------------------------------------------------------------
 * 1 ms 心跳
 * ------------------------------------------------------------------------- */
void safety_tick_1ms(void)
{
    s_uptime_ms++;

    /* ---- 1. 急停保持 ---- */
    if (s_estop) {
        if (s_state != SYS_FAULT) enter_state(SYS_FAULT);
        /* 注意：这里不喂狗会被上层判定为异常。
         * 但急停是一个"已知且安全"的状态，看门狗不应该因此复位设备 ——
         * 复位后如果急停仍按着，就会陷入复位循环。
         * 所以在急停期间仍然喂狗，只是不给电机使能。 */
        HAL_IWDG_Refresh(&hiwdg);
        return;
    }

    /* ---- 2. 任务心跳仲裁 ---- */
    for (uint8_t i = 0; i < HB_COUNT_; i++) {
        uint32_t age = s_uptime_ms - s_hb_last[i];
        if (age > SAFETY_TASK_STALL_MS * 10U) {
            /* 用 10 倍窗口判定，避免刚启动或暂时被抢占就误判 */
            safety_raise_fault(FAULT_TASK_STALL);
            break;
        }
    }

    /* ---- 3. 链路超时分级 ---- */
    uint32_t link_age = s_uptime_ms - s_last_frame_ms;

    if (s_link_ever_alive) {
        if (link_age > LINK_TIMEOUT_DEGRADE_MS) {
            if (s_state == SYS_AUTO) {
                safety_raise_fault(FAULT_LINK_TIMEOUT);
            }
        } else if (link_age > LINK_TIMEOUT_MS) {
            if (s_state == SYS_AUTO) {
                /* 中间地带：不切功率，但让控制层减速。
                 * 由 motion 的 lost 逻辑配合上层调用实现。 */
            }
        }
    } else {
        /* 从未收到过有效帧。上电后允许一段宽限期，
         * 否则视觉节点还没启动完成就会被判故障。 */
        if (s_uptime_ms > LINK_TIMEOUT_DEGRADE_MS * 5U) {
            if (s_state == SYS_AUTO) {
                safety_raise_fault(FAULT_LINK_TIMEOUT);
            }
        }
    }

    /* ---- 4. CRC 突发错误检测 ----
     * 持续大量 CRC 错说明是物理层问题（线材、波特率、共地），
     * 不是偶发干扰。这种状态下继续作业是不安全的。 */
    if (s_uptime_ms - s_crc_window_start >= 1000U) {
        if (s_crc_window > 50U) {
            safety_raise_fault(FAULT_CRC_BURST);
        }
        s_crc_window = 0;
        s_crc_window_start = s_uptime_ms;
    }

    /* ---- 5. 自动模式进入条件 ---- */
    if (s_state == SYS_IDLE && s_auto_requested && s_link_ever_alive
        && (s_uptime_ms - s_last_frame_ms) < LINK_TIMEOUT_MS) {
        enter_state(SYS_AUTO);
    }

    /* ---- 6. 唯一喂狗点 ----
     * ★ 只要本函数还在被 1ms 任务调用，就喂狗 —— 不区分状态。
     *
     * 原设计是"FAULT 时不喂 ⇒ 让 IWDG 复位"，但它制造了一个自锁的复位环：
     *   FAULT → 不喂狗 → 500 ms 后 IWDG 复位 → 复位标志让 streak++ →
     *   开机读到 streak 超限 → 又进 FAULT → 再复位 …… 每 500 ms 一次，永不停止。
     * 现场表现就是"整机不停重启、串口一句输出都没有"，且因为 streak 存在
     * .noinit 里，只要不断电就一直存在。
     *
     * 看门狗的职责是发现"调度器/任务死了"，不是惩罚一个已经锁存的故障。
     * 故障态仍然喂狗，设备就能停在 FAULT 里保持可诊断、可远程清除。 */
    HAL_IWDG_Refresh(&hiwdg);

    /* ---- 7. 健康运行满 10s ⇒ 清零连续复位计数 ----
     * streak 的语义是"连续多少次没能正常跑起来"。一旦证明这次能稳定跑满
     * 10 秒，之前的复位就是历史问题，计数必须归零；否则在同一次上电周期内
     * 计数只增不减，设备越跑越接近锁死阈值。
     * 真正的"起不来"固件缺陷永远跑不到 10 秒，保护依然有效。 */
    if (s_uptime_ms >= SAFETY_IWDG_STREAK_CLEAR_MS) {
        s_iwdg_reset_streak = 0;
    }
}

/* ------------------------------------------------------------------------- */
void safety_get_snapshot(safety_snapshot_t *out)
{
    if (!out) return;
    out->state          = s_state;
    out->fault          = s_fault;
    out->good_frames    = s_good_frames;
    out->uptime_ms      = s_uptime_ms;
    out->iwdg_resets    = s_iwdg_resets;
    out->estop_active   = s_estop;
    out->link_alive     = s_link_ever_alive &&
                          ((s_uptime_ms - s_last_frame_ms) < LINK_TIMEOUT_MS);
}

const char *safety_state_name(sys_state_t s)
{
    switch (s) {
    case SYS_INIT:      return "INIT";
    case SYS_IDLE:      return "IDLE";
    case SYS_AUTO:      return "AUTO";
    case SYS_SAFE_STOP: return "SAFE_STOP";
    case SYS_FAULT:     return "FAULT";
    default:            return "?";
    }
}

const char *safety_fault_name(fault_code_t f)
{
    switch (f) {
    case FAULT_NONE:           return "NONE";
    case FAULT_LINK_TIMEOUT:   return "LINK_TIMEOUT";
    case FAULT_CRC_BURST:      return "CRC_BURST";
    case FAULT_ESTOP:          return "ESTOP";
    case FAULT_TASK_STALL:     return "TASK_STALL";
    case FAULT_PARAM_LOST:     return "PARAM_LOST";
    case FAULT_IWDG_REPEAT:    return "IWDG_REPEAT";
    case FAULT_MOTOR_DISABLED: return "MOTOR_DISABLED";
    default:                   return "?";
    }
}
