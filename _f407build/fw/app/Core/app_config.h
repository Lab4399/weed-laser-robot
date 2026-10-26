/**
 * @file    app_config.h
 * @brief   除草识别小车 · STM32F407 主控节点 · 全局配置
 *
 * 所有可调参数集中在本文件。业务代码中不允许出现未在此处定义的数值常量。
 * 标定类参数（Kp、速度、阈值）在实车联调阶段回填，禁止凭理论值上线。
 */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

/* ===========================================================================
 *  0. 硬件基准
 * ===========================================================================
 *  ⚠️ 引脚分配需按实际接线核对。以下为 F407 常见分配方案，
 *     与开发板原理图不一致时必须改这里，不要改驱动代码。
 */
#define APP_SYSCLK_HZ            168000000U

/* APB1 定时器时钟：SYSCLK=168M, APB1=42M, 定时器时钟 ×2 = 84 MHz
 * 舵机 PWM 与电机 PWM 都在 TIM3/TIM4，均挂 APB1，故共用此基准。 */
#define APP_APB1_TIMER_CLK_HZ     84000000U

/* ---------------------------------------------------------------------------
 *  视觉链路  USART1 @ PA9(TX) / PA10(RX)
 *  DMA：USART1_RX = DMA2 Stream2 Ch4，USART1_TX = DMA2 Stream7 Ch4
 *  ⚠️ 这两个 DMA 请求编号必须查 F407 参考手册的 DMA 请求映射表，
 *     写错不会报错，只会静默收不到数据。
 * ------------------------------------------------------------------------- */
#define LINK_UART                  huart1
#define LINK_UART_INSTANCE         USART1
#define LINK_UART_BAUD             115200U

/* 图像宽度。必须与 OpenMV 侧 config.IMAGE_WIDTH 一致。
 * 不一致会导致 error_x 系统性偏移一个常数，表现为小车永远偏向一侧。 */
#define LINK_IMG_WIDTH             320
#define LINK_IMG_HEIGHT            240
#define LINK_IMG_CENTER_X          (LINK_IMG_WIDTH / 2)

/* 链路超时（ms）。
 * ⚠️ 必须 > OpenMV 单帧推理最坏耗时 × 1.5
 *    取值依据：OpenMV 打印的 infer_ms_max。
 *    取小了 ⇒ 每次推理都触发误超时，小车一顿一顿地走。 */
#define LINK_TIMEOUT_MS            600U
#define LINK_TIMEOUT_DEGRADE_MS    900U   /* 超过此值进入 SAFE_STOP */

/* 接收缓冲 */
#define LINK_DMA_BUF_SZ            256U   /* DMA 循环缓冲，必须是 2 的幂 */
#define LINK_RING_SZ               512U   /* 软件环形缓冲，必须是 2 的幂 */

/* 协议限制 */
#define PROTO_MAX_BODY_LEN         96U    /* 单帧正文最大字节数，超长整帧丢弃 */
#define PROTO_MAX_FIELDS           12U

/* 数值合法性范围。任何越界帧都整帧丢弃，不得驱动电机。 */
#define PROTO_CX_MAX               4095
#define PROTO_CY_MAX               4095
#define PROTO_WH_MAX               4095
#define PROTO_DIST_MAX             65535

/* ===========================================================================
 *  1. 执行器
 * ===========================================================================
 *  控制权归属（协议文档第 7 节，不得越界）：
 *    履带电机 2 路   → F407 控制
 *    执行机构舵机 2 路 → F407 控制
 *    摄像头云台舵机   → OpenMV 控制（不在本固件范围内）
 */

/* --- 电机 PWM：TIM4 CH1~CH4 @ PB6~PB9 --- */
#define MOTOR_TIM                  htim4
#define MOTOR_TIM_INSTANCE         TIM4
#define MOTOR_PWM_FREQ_HZ          20000U  /* 20 kHz，高于人耳听阈，避免啸叫 */
/* ARR = 84MHz / 20kHz - 1 = 4199，占空比分辨率 1/4200 ≈ 0.024% */

#define MOTOR_COUNT                2U

/* --- 舵机 PWM：TIM3 CH1/CH2 @ PA6/PA7 ---
 * 50 Hz（20 ms 周期），1 µs 分辨率
 *   PSC = 84MHz/1MHz - 1 = 83
 *   ARR = 1MHz × 20ms - 1 = 19999
 *   CCR = 脉宽（µs），直接写 1000 就是 1.0 ms
 */
#define SERVO_TIM                  htim3
#define SERVO_TIM_INSTANCE         TIM3
#define SERVO_PWM_PERIOD_US        20000U
#define SERVO_COUNT                2U

/* 舵机脉宽范围。⚠️ 必须以所用舵机型号规格书为准并实测确认。
 * 标称 500~2500 µs 的舵机能到 ±90°，但廉价的 SG90 常只能到 1000~2000 µs，
 * 超范围会造成堵转，电流可达额定值的数倍并烧毁舵机。 */
#define SERVO_PULSE_MIN_US         1000U
#define SERVO_PULSE_MAX_US         2000U
#define SERVO_PULSE_CENTER_US      1500U

/* 上电缓动：从当前位置到目标角度的步进（µs）与步进间隔（ms）。
 * 直接跳变会让舵机瞬间大电流启动，并可能机械冲击损坏齿轮。 */
#define SERVO_SLEW_STEP_US         10U
#define SERVO_SLEW_INTERVAL_MS     10U

/* ===========================================================================
 *  2. 运动控制参数（全部待实车标定）
 * =========================================================================== */
#define CTRL_PERIOD_MS             10U    /* 控制周期，100 Hz */

/* 基础速度：占空比千分比 0~1000 */
#define CTRL_BASE_SPEED_DEFAULT    350
#define CTRL_BASE_SPEED_MIN        100
#define CTRL_BASE_SPEED_MAX        700

/* 转向比例系数：单位 千分比/像素。
 * 默认值仅供首次上电、车轮离地时试探，必须实车标定。 */
#define CTRL_KP_TURN_DEFAULT       1.2f
#define CTRL_KP_TURN_MIN           0.0f
#define CTRL_KP_TURN_MAX           10.0f

/* 死区：|error_x| 小于此值不做转向修正，避免直线行驶时左右抖 */
#define CTRL_CENTER_DEADZONE_PX    20

/* 输出限幅 */
#define CTRL_DUTY_MAX              900    /* 占空比千分比上限 */

/* 加速度限制：每个控制周期允许的最大占空比变化量。
 * ⚠️ 这个参数比 Kp 更重要：
 *    履带车突然反向时，若占空比从 +700 一步跳到 -700，
 *    电机堵转电流可达额定值的 5~10 倍，会烧驱动板。
 *    该值取小会牺牲响应速度，取大则炸驱动板 —— 必须实测。 */
#define CTRL_SLEW_STEP_DEFAULT     35
#define CTRL_SLEW_STEP_MIN         5
#define CTRL_SLEW_STEP_MAX         200

/* 电机死区补偿：占空比低于此值时电机不转（静摩擦力），直接补到该值。
 * 需实测：从 0 缓慢增加占空比直到轮子刚开始转动，读出的值即为此参数。 */
#define MOTOR_DEADZONE_DUTY        60

/* 左右电机极性。1 = 正占空比前进，-1 = 反接。
 * 用于在不动硬件的情况下纠正接线反向。 */
#define MOTOR_L_POLARITY           (+1)
#define MOTOR_R_POLARITY           (+1)

/* ===========================================================================
 *  3. 安全策略
 * =========================================================================== */
#define SAFETY_CONF_MIN            0.55f  /* 低于此置信度不允许激进运动 */
#define SAFETY_CONF_DEGRADE        0.75f  /* 低于此值主动降速 */

#define SAFETY_LOST_FRAMES_SLOW    10U    /* 连续丢多少帧开始减速 */
#define SAFETY_LOST_FRAMES_STOP    40U    /* 连续丢多少帧停车搜索 */

#define SAFETY_IWDG_TIMEOUT_MS     500U   /* 独立看门狗超时 */
#define SAFETY_TASK_STALL_MS       200U   /* 任务心跳窗口 */
#define SAFETY_MAX_IWDG_RESETS     3U     /* 连续多少次 IWDG 复位判定固件异常 */
#define SAFETY_IWDG_STREAK_CLEAR_MS 10000U /* 稳定运行多久后清零复位计数 */

/* ===========================================================================
 *  4. 参数持久化（F407 内部 Flash）
 * ===========================================================================
 *  F407 1MB 型号的 sector 划分：
 *    sector 0-3 : 16 KB  (0x08000000 ~ 0x0800BFFF)
 *    sector 4   : 64 KB  (0x0800C000 ~ 0x0801BFFF)
 *    sector 5-11: 128 KB each
 *  ⚠️ 擦除以 sector 为单位。分区边界必须对齐 sector，
 *     否则擦 A 会连带抹掉相邻区域。
 *  这里取最后两个 sector，永远不会与代码区冲突。
 */
#define PARAM_BANK_A_ADDR          0x080C0000U  /* sector 10, 128 KB */
#define PARAM_BANK_B_ADDR          0x080E0000U  /* sector 11, 128 KB */
#define PARAM_BANK_SIZE            0x00020000U
#define PARAM_MAGIC                0x50415241U  /* "PARA" */
#define PARAM_VERSION              1U

/* ===========================================================================
 *  5. FreeRTOS 任务配置
 * ===========================================================================
 *  configMINIMAL_STACK_SIZE 的单位是 word（4 字节），不是字节。
 *  下表按字节给出，转入 xTaskCreateStatic 时不要再做一次换算。
 */
#define TASK_STACK_SAFETY          512U
#define TASK_STACK_CONTROL         1024U
#define TASK_STACK_VISION          1024U
#define TASK_STACK_MOTION          1024U
#define TASK_STACK_PARAM           768U

#define TASK_PRIO_SAFETY           10U
#define TASK_PRIO_CONTROL          8U
#define TASK_PRIO_VISION           6U
#define TASK_PRIO_MOTION           5U
#define TASK_PRIO_PARAM            2U

/* ===========================================================================
 *  6. 编译期断言：把配置错误挡在编译阶段，而不是运行阶段
 * =========================================================================== */
#if (LINK_DMA_BUF_SZ & (LINK_DMA_BUF_SZ - 1)) != 0
#error "LINK_DMA_BUF_SZ 必须是 2 的幂（环形缓冲回绕依赖此性质）"
#endif
#if (LINK_RING_SZ & (LINK_RING_SZ - 1)) != 0
#error "LINK_RING_SZ 必须是 2 的幂"
#endif
#if CTRL_DUTY_MAX > 1000
#error "CTRL_DUTY_MAX 不得超过 1000（占空比千分比）"
#endif
#if SERVO_PULSE_MIN_US >= SERVO_PULSE_MAX_US
#error "舵机脉宽范围非法"
#endif
#if CTRL_PERIOD_MS == 0
#error "控制周期不能为 0"
#endif

#endif /* APP_CONFIG_H */
