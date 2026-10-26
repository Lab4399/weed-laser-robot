/**
 * @file    motor.c
 * @brief   履带电机驱动实现
 */
#include "motor.h"
#include "../Core/app_config.h"

#include "stm32f4xx_hal.h"

/* ---------------------------------------------------------------------------
 * 引脚表。改接线只需改这里，不要改下面的逻辑。
 * ------------------------------------------------------------------------- */
typedef struct {
    uint32_t      tim_channel;
    GPIO_TypeDef *in1_port;
    uint16_t      in1_pin;
    GPIO_TypeDef *in2_port;
    uint16_t      in2_pin;
    int8_t        polarity;     /* +1 / -1 */
    int16_t       cur;          /* 当前设定值（千分比，不含死区补偿） */
} motor_ch_t;

static motor_ch_t s_motor[MOTOR_COUNT_] = {
    [MOTOR_LEFT] = {
        .tim_channel = TIM_CHANNEL_1,
        .in1_port = GPIOB, .in1_pin = GPIO_PIN_12,
        .in2_port = GPIOB, .in2_pin = GPIO_PIN_13,
        .polarity = MOTOR_L_POLARITY,
        .cur      = 0,
    },
    [MOTOR_RIGHT] = {
        .tim_channel = TIM_CHANNEL_2,
        .in1_port = GPIOB, .in1_pin = GPIO_PIN_14,
        .in2_port = GPIOB, .in2_pin = GPIO_PIN_15,
        .polarity = MOTOR_R_POLARITY,
        .cur      = 0,
    },
};

#define MOTOR_STBY_PORT   GPIOB
#define MOTOR_STBY_PIN    GPIO_PIN_11

extern TIM_HandleTypeDef MOTOR_TIM;

static bool s_enabled = false;

/* PWM 周期值（ARR + 1）。由 CubeMX 配置决定，必须与 app_config 的
 * MOTOR_PWM_FREQ_HZ 一致：ARR+1 = 84MHz / 20kHz = 4200 */
#define MOTOR_ARR_PLUS1   4200U

/* ---------------------------------------------------------------------------
 * 内部
 * ------------------------------------------------------------------------- */
static inline uint32_t duty_to_ccr(int16_t mag)
{
    /* mag: 0..1000 千分比 → CCR: 0..MOTOR_ARR_PLUS1-1 */
    uint32_t ccr = ((uint32_t)mag * MOTOR_ARR_PLUS1) / 1000U;
    if (ccr >= MOTOR_ARR_PLUS1) ccr = MOTOR_ARR_PLUS1 - 1U;
    return ccr;
}

/**
 * 死区补偿：占空比太低时电机只会嗡嗡响不转（静摩擦）。
 * 直接把小幅值抬到 MOTOR_DEADZONE_DUTY，否则低速段完全不可控。
 *
 * ⚠️ 代价：补偿后下限不为零，小车无法做到极慢速蠕行。
 *    若需要蠕行，正确做法是改驱动器的 PWM 频率或用更高电压，
 *    而不是把补偿值调小（调小只会让电机在死区里随机地转/不转）。
 */
static inline int16_t apply_deadzone(int16_t duty)
{
    if (duty == 0) return 0;
    if (duty > 0 && duty < MOTOR_DEADZONE_DUTY) return MOTOR_DEADZONE_DUTY;
    if (duty < 0 && duty > -MOTOR_DEADZONE_DUTY) return -MOTOR_DEADZONE_DUTY;
    return duty;
}

/* ---------------------------------------------------------------------------
 * 公开接口
 * ------------------------------------------------------------------------- */
void motor_init(void)
{
    /* 先确保驱动被禁用，再配置引脚 —— 顺序反了会让电机在上电瞬间突然动作 */
    HAL_GPIO_WritePin(MOTOR_STBY_PORT, MOTOR_STBY_PIN, GPIO_PIN_RESET);
    s_enabled = false;

    HAL_TIM_PWM_Start(&MOTOR_TIM, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&MOTOR_TIM, TIM_CHANNEL_2);

    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_1, 0);
    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_2, 0);

    for (uint8_t i = 0; i < MOTOR_COUNT_; i++) {
        s_motor[i].cur = 0;
        HAL_GPIO_WritePin(s_motor[i].in1_port, s_motor[i].in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(s_motor[i].in2_port, s_motor[i].in2_pin, GPIO_PIN_RESET);
    }
}

void motor_enable(bool en)
{
    /* ★ 无论使能还是禁用，都先把输出清零。
     *
     * 为什么必须这样（2026-10-23 修复）：
     *   原实现只在 en==true 时清零，en==false 时仅拉低 STBY。
     *   这对 TB6612 有效（STBY 拉低即硬件切断 H 桥），
     *   但本机用的是 **L298N，没有 STBY 引脚** —— PB11 悬空，
     *   拉低它没有任何物理效果，电机仍按上一次的 PWM 与方向继续转。
     *
     *   后果：safety 模块判定故障后调用 motor_enable(false)，
     *   电机却不停，直到 IWDG 复位或人工断电。这是真实的安全漏洞。
     *
     *   清零后再拉 STBY，对 TB6612 也更安全（避免带载切换）。
     */
    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_1, 0);
    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_2, 0);
    for (uint8_t i = 0; i < MOTOR_COUNT_; i++) {
        HAL_GPIO_WritePin(s_motor[i].in1_port, s_motor[i].in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(s_motor[i].in2_port, s_motor[i].in2_pin, GPIO_PIN_RESET);
        s_motor[i].cur = 0;
    }

    HAL_GPIO_WritePin(MOTOR_STBY_PORT, MOTOR_STBY_PIN,
                      en ? GPIO_PIN_SET : GPIO_PIN_RESET);
    s_enabled = en;
}

bool motor_is_enabled(void)
{
    return s_enabled;
}

void motor_set(motor_id_t id, int16_t duty)
{
    if (id >= MOTOR_COUNT_) return;

    /* 未使能时拒绝任何驱动请求，并强制清零输出。
     * 这一层保护让"safety 已切断驱动"成为硬约束，
     * 而不是依赖上层模块记得不要调用 motor_set。
     *
     * 注意：这里不能只 return —— L298N 没有 STBY，若保留上一次的
     * PWM 与方向电平，电机会继续转。必须显式清零。 */
    if (!s_enabled) {
        __HAL_TIM_SET_COMPARE(&MOTOR_TIM, s_motor[id].tim_channel, 0);
        HAL_GPIO_WritePin(s_motor[id].in1_port, s_motor[id].in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(s_motor[id].in2_port, s_motor[id].in2_pin, GPIO_PIN_RESET);
        s_motor[id].cur = 0;
        return;
    }

    /* 限幅 */
    if (duty > CTRL_DUTY_MAX)  duty = CTRL_DUTY_MAX;
    if (duty < -CTRL_DUTY_MAX) duty = -CTRL_DUTY_MAX;

    s_motor[id].cur = duty;

    /* 极性翻转：纠正左右电机接线反向，不动硬件 */
    int32_t d = (int32_t)duty * (int32_t)s_motor[id].polarity;

    int16_t mag = (int16_t)((d < 0) ? -d : d);
    mag = apply_deadzone(mag);

    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, s_motor[id].tim_channel, duty_to_ccr(mag));

    if (d > 0) {
        HAL_GPIO_WritePin(s_motor[id].in1_port, s_motor[id].in1_pin, GPIO_PIN_SET);
        HAL_GPIO_WritePin(s_motor[id].in2_port, s_motor[id].in2_pin, GPIO_PIN_RESET);
    } else if (d < 0) {
        HAL_GPIO_WritePin(s_motor[id].in1_port, s_motor[id].in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(s_motor[id].in2_port, s_motor[id].in2_pin, GPIO_PIN_SET);
    } else {
        /* 滑行停止：方向脚全低 + PWM 归零。
         * 这里不用短接刹车，因为差值控制时某一侧经常经过 0，
         * 若每次过零都短接刹车会明显抖动。 */
        HAL_GPIO_WritePin(s_motor[id].in1_port, s_motor[id].in1_pin, GPIO_PIN_RESET);
        HAL_GPIO_WritePin(s_motor[id].in2_port, s_motor[id].in2_pin, GPIO_PIN_RESET);
        __HAL_TIM_SET_COMPARE(&MOTOR_TIM, s_motor[id].tim_channel, 0);
    }
}

void motor_set_both(int16_t left, int16_t right)
{
    motor_set(MOTOR_LEFT, left);
    motor_set(MOTOR_RIGHT, right);
}

void motor_stop_all(void)
{
    motor_set(MOTOR_LEFT, 0);
    motor_set(MOTOR_RIGHT, 0);
}

void motor_brake_all(void)
{
    for (uint8_t i = 0; i < MOTOR_COUNT_; i++) {
        HAL_GPIO_WritePin(s_motor[i].in1_port, s_motor[i].in1_pin, GPIO_PIN_SET);
        HAL_GPIO_WritePin(s_motor[i].in2_port, s_motor[i].in2_pin, GPIO_PIN_SET);
    }
    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_1, duty_to_ccr(CTRL_DUTY_MAX));
    __HAL_TIM_SET_COMPARE(&MOTOR_TIM, TIM_CHANNEL_2, duty_to_ccr(CTRL_DUTY_MAX));
    s_motor[MOTOR_LEFT].cur = 0;
    s_motor[MOTOR_RIGHT].cur = 0;
}

int16_t motor_get(motor_id_t id)
{
    return (id < MOTOR_COUNT_) ? s_motor[id].cur : 0;
}
