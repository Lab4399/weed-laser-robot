/**
 * @file    servo.c
 * @brief   执行机构舵机驱动实现
 */
#include "servo.h"
#include "../Core/app_config.h"

#include "stm32f4xx_hal.h"

extern TIM_HandleTypeDef SERVO_TIM;

typedef struct {
    uint32_t channel;
    uint16_t cur_us;      /* 当前实际输出的脉宽 */
    uint16_t target_us;   /* 目标脉宽 */
    uint16_t home_us;     /* 中位 */
} servo_ch_t;

static servo_ch_t s_servo[SERVO_COUNT_] = {
    [SERVO_A] = { .channel = TIM_CHANNEL_1, .cur_us = 0, .target_us = 0, .home_us = 0 },
    [SERVO_B] = { .channel = TIM_CHANNEL_2, .cur_us = 0, .target_us = 0, .home_us = 0 },
};

/* ------------------------------------------------------------------------- */
static inline uint16_t clamp_pulse(uint16_t us)
{
    if (us < SERVO_PULSE_MIN_US) return SERVO_PULSE_MIN_US;
    if (us > SERVO_PULSE_MAX_US) return SERVO_PULSE_MAX_US;
    return us;
}

static inline void write_ccr(servo_ch_t *s, uint16_t us)
{
    __HAL_TIM_SET_COMPARE(&SERVO_TIM, s->channel, us);
    s->cur_us = us;
}

/* ------------------------------------------------------------------------- */
void servo_init(void)
{
    HAL_TIM_PWM_Start(&SERVO_TIM, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&SERVO_TIM, TIM_CHANNEL_2);

    for (uint8_t i = 0; i < SERVO_COUNT_; i++) {
        s_servo[i].home_us = SERVO_PULSE_CENTER_US;
        s_servo[i].target_us = SERVO_PULSE_CENTER_US;
        /* 上电直接写中位。这里不做缓动是有意的：
         * 舵机上电时的物理位置未知，若从 0 开始缓动会先跑完全程再回来，
         * 反而造成更大的机械冲击。 */
        write_ccr(&s_servo[i], SERVO_PULSE_CENTER_US);
    }
}

void servo_set_us(servo_id_t id, uint16_t pulse_us)
{
    if (id >= SERVO_COUNT_) return;
    s_servo[id].target_us = clamp_pulse(pulse_us);
}

void servo_set_us_raw(servo_id_t id, uint16_t pulse_us)
{
    if (id >= SERVO_COUNT_) return;
    s_servo[id].target_us = pulse_us;
    write_ccr(&s_servo[id], pulse_us);
}

bool servo_update(void)
{
    bool changed = false;

    for (uint8_t i = 0; i < SERVO_COUNT_; i++) {
        servo_ch_t *s = &s_servo[i];
        if (s->cur_us == s->target_us) continue;

        if (s->cur_us < s->target_us) {
            uint16_t next = (uint16_t)(s->cur_us + SERVO_SLEW_STEP_US);
            if (next > s->target_us) next = s->target_us;
            write_ccr(s, next);
        } else {
            uint16_t next = (uint16_t)(s->cur_us - SERVO_SLEW_STEP_US);
            if (next < s->target_us) next = s->target_us;
            write_ccr(s, next);
        }
        changed = true;
    }
    return changed;
}

void servo_flush(void)
{
    for (uint8_t i = 0; i < SERVO_COUNT_; i++) {
        write_ccr(&s_servo[i], s_servo[i].target_us);
    }
}

uint16_t servo_get_us(servo_id_t id)
{
    return (id < SERVO_COUNT_) ? s_servo[id].cur_us : 0;
}

uint16_t servo_get_target_us(servo_id_t id)
{
    return (id < SERVO_COUNT_) ? s_servo[id].target_us : 0;
}

bool servo_settled(servo_id_t id)
{
    return (id < SERVO_COUNT_) && (s_servo[id].cur_us == s_servo[id].target_us);
}
