/**
 * @file    app_main.c
 * @brief   应用层启动流程
 *
 * ── 为什么这个文件不叫 main.c ──
 *
 *   CubeMX 每次"重新生成代码"都会覆盖 Core/Src/main.c，
 *   你在里面手写的任何逻辑都会丢失。这是 CubeMX 项目最常见的返工来源，
 *   而且往往是"改完 CubeMX 配置、重新生成、代码没了"之后才发现。
 *
 *   正确做法：
 *     · main.c 归 CubeMX 所有，只保留 MX_*_Init 与 SystemClock_Config
 *     · 应用逻辑放在本文件，由 main.c 的 USER CODE 区段调用
 *     · 中断服务程序放在 stm32f4xx_it.c 的 USER CODE 区段调用本模块的钩子
 *
 *   集成位置见 stm32f407/README.md 的「CubeMX 集成」一节。
 *
 * ── 初始化顺序是有约束的，不要随意调整 ──
 *
 *   1. 协议自检           —— 在收数据之前。不一致时现象极难反推，挡在启动阶段
 *   2. 参数载入           —— 在初始化运动模块之前，否则会用编译默认值跑
 *   3. 外设初始化
 *   4. 安全模块           —— 依赖已初始化的电机与运动模块
 *   5. IWDG               —— 最后启动，否则前面的耗时步骤会被看门狗咬
 *   6. 任务创建
 */
#include "app_main.h"
#include "app_config.h"
#include "app_tasks.h"

#include "../drivers/uart_link.h"
#include "../drivers/motor.h"
#include "../drivers/servo.h"
#include "../control/motion.h"
#include "../services/safety.h"
#include "../services/param.h"
#include "../protocol/vision_proto.h"

#include "stm32f4xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"

/* CubeMX 生成的外设句柄。名字由 app_config.h 的别名宏映射过来：
 *   LINK_UART → huart1, MOTOR_TIM → htim4, SERVO_TIM → htim3, hiwdg */
extern UART_HandleTypeDef  LINK_UART;
extern DMA_HandleTypeDef   hdma_usart1_rx;
extern TIM_HandleTypeDef   MOTOR_TIM;
extern TIM_HandleTypeDef   SERVO_TIM;
extern IWDG_HandleTypeDef  hiwdg;

/* ------------------------------------------------------------------------- */
void app_main(void)
{
    /* ---- 1. 协议自检 ----
     * 若两侧 CRC 实现不一致，现象是"一直收不到有效帧"，
     * 而抓包看帧完全正常 —— 几乎无法从现象反推原因。
     * 这里把问题挡在启动瞬间。 */
    if (!vision_proto_selftest()) {
        /* 自检失败进入不可恢复状态。此时串口尚未启动，无法打印，
         * 只能靠调试器看 PC 停在这里。
         * 不喂狗 ⇒ IWDG 超时后复位，形成"上电即复位"的可见现象，
         * 比静默跑起来更容易被发现。 */
        for (;;) { }
    }

    /* ---- 2. 参数 ---- */
    param_init();

    if (param_was_lost()) {
        /* 首次烧录时这是正常现象（Flash 全 0xFF）。
         * 连续两次上电都 lost 才是真故障 —— 但"连续"这个状态
         * 本身需要存储才能判断，这里的取舍是：只记录，不锁死。 */
    }

    param_payload_t pp;
    param_get(&pp);

    /* ---- 3. 外设 ---- */
    uart_link_init();
    motor_init();
    servo_init();
    motion_init();
    motion_set_params(&pp.motion);

    /* 舵机中位下发。用中位而不是端点，避免上电瞬间顶到机械限位。 */
    servo_set_us(SERVO_A, pp.servo_a[1]);
    servo_set_us(SERVO_B, pp.servo_b[1]);

    /* ---- 4. 安全模块 ----
     * 它依赖已初始化的电机与运动模块，必须放最后。
     * 内部会读 RCC->CSR 判定复位原因并清除标志。 */
    safety_init();

    /* ---- 5. 看门狗 ----
     *
     * IWDG 由 CubeMX 生成的 MX_IWDG_Init() 启动，它位于 main.c 的标准
     * 初始化块里，因此在本函数之前就已经开始计数。这是可以接受的，因为：
     *   · 本项目的 IWDG 超时设 500 ms
     *   · app_main 的全部初始化实测在毫秒量级（最耗时的是 param_init
     *     读两次 Flash 扇区头部，不做擦写，微秒级）
     *   · 全程没有任何阻塞等待
     *
     * 但有一个前提必须在 CubeMX 里保证：
     *   MX_IWDG_Init() 必须是 main.c 初始化块里**最后一个** MX_*_Init 调用，
     *   且紧邻 app_main()。把它放在前面会让"上电即复位"变成一个
     *   连打印都没有的诡异现象。
     *
     * 初始化收尾时主动喂一次狗，确保从 MX_IWDG_Init 到
     * task_safety 首次喂狗之间的间隙不会累积。 */
    HAL_IWDG_Refresh(&hiwdg);

    /* ---- 6. 任务与调度器（不返回） ---- */
    app_tasks_start();
}

/* ===========================================================================
 *  FreeRTOS 钩子
 *
 *  放在本文件（而非 main.c）是因为它们必须长期存在，
 *  CubeMX 重新生成 main.c 不会影响这里。
 * =========================================================================== */

/**
 * 栈溢出。
 * ⚠️ 不要尝试恢复 —— 栈溢出已经破坏了相邻内存，
 *    继续运行会产生完全随机的故障，比直接停机难排查得多。
 *    这里只做"关中断、等看门狗"。
 */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
    (void)xTask;
    (void)pcTaskName;
    taskDISABLE_INTERRUPTS();
    for (;;) { }
}

/** 静态分配下不应被调用；保留作为配置错误的早期告警。 */
void vApplicationMallocFailedHook(void)
{
    taskDISABLE_INTERRUPTS();
    for (;;) { }
}

/**
 * 空闲钩子。当前不做事，但保留是为了将来
 * 可以在这里统计 CPU 负载或进入低功耗。
 */
void vApplicationIdleHook(void)
{
    /* 留空 */
}
