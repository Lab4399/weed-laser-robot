/**
 * @file    motor.h
 * @brief   履带电机驱动（TIM4 PWM + 方向 GPIO）
 *
 * 硬件假设：TB6612 / DRV8833 类双路 H 桥模块
 *   每路电机 = 1 路 PWM（调速） + 2 路 GPIO（方向） + 1 路共用 STBY（使能）
 *
 * 引脚分配（需按实际接线核对，见 app_config.h）：
 *   左电机  PWM = TIM4_CH1 / PB6      AIN1 = PB12   AIN2 = PB13
 *   右电机  PWM = TIM4_CH2 / PB7      BIN1 = PB14   BIN2 = PB15
 *   驱动使能  STBY = PB11   ← 同时是"安全切除"的硬件执行点
 */
#ifndef MOTOR_H
#define MOTOR_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    MOTOR_LEFT = 0,
    MOTOR_RIGHT = 1,
    MOTOR_COUNT_ = 2
} motor_id_t;

/** 初始化 PWM、方向 GPIO、STBY。上电后电机处于停止且使能关闭状态。 */
void motor_init(void);

/**
 * 设置单路电机占空比。
 * @param id   motor_id_t
 * @param duty 千分比 -1000 ~ +1000。正 = 前进，负 = 后退，0 = 滑行停止。
 *             内部会做极性翻转与死区补偿。
 */
void motor_set(motor_id_t id, int16_t duty);

/** 同时设置两路（差速转向的标准入口）。 */
void motor_set_both(int16_t left, int16_t right);

/** 滑行停止：PWM 归零，方向脚全低。冲击小，适合正常减速。 */
void motor_stop_all(void);

/**
 * 短接刹车：方向脚全高，电机绕组短接。停得快但冲击大、电流大。
 * ⚠️ 高速行驶时慎用，可能触发驱动器过流保护。
 */
void motor_brake_all(void);

/**
 * 驱动器使能。
 * ⚠️ 这是整个安全链的硬件执行点：safety 模块在超时/急停时调用
 *    motor_enable(false)，直接切断驱动输出，不经过任何控制算法。
 */
void motor_enable(bool en);

bool motor_is_enabled(void);

/** 读回当前设定值（千分比，含极性，不含死区补偿）。 */
int16_t motor_get(motor_id_t id);

#endif /* MOTOR_H */
