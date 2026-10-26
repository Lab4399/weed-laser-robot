/**
 * @file    servo.h
 * @brief   执行机构舵机驱动（TIM3, 50 Hz）
 *
 * 控制权归属（协议文档第 7 节）：
 *   本模块控制的是**小车执行机构舵机**，由 F407 决策。
 *   摄像头云台舵机不在本固件范围内，归 OpenMV 控制。
 *   两者绝不能交叉 —— 一块芯片同时被两个控制器驱动会产生控制权冲突，
 *   现象是舵机在两个位置之间来回顶，最终烧毁。
 *
 * PWM 参数推导（F407, APB1 定时器时钟 84 MHz）：
 *   PSC = 84MHz / 1MHz - 1 = 83      ⇒ 计数频率 1 MHz，即 1 µs/tick
 *   ARR = 1MHz × 20ms - 1  = 19999   ⇒ 周期 20 ms（50 Hz）
 *   CCR = 脉宽（µs）
 *   这样 CCR 直接就是微秒数，中间不需要任何换算 ——
 *   任何换算都是引入舍入误差和调试困惑的机会。
 */
#ifndef SERVO_H
#define SERVO_H

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    SERVO_A = 0,
    SERVO_B = 1,
    SERVO_COUNT_ = 2
} servo_id_t;

/** 初始化：启动 PWM 并把两路置到中位脉宽。 */
void servo_init(void);

/**
 * 设置目标脉宽（微秒）。内部会限幅到 [SERVO_PULSE_MIN_US, SERVO_PULSE_MAX_US]，
 * 并按 SERVO_SLEW_STEP_US 逐步逼近，不会瞬间跳变。
 *
 * ⚠️ 限幅不是可选的：廉价的 SG90 类舵机标称 500~2500 µs，
 *    但实际超过 1000~2000 µs 就会顶到机械限位并堵转，
 *    堵转电流可达正常工作值的数倍，几分钟内就能烧掉舵机。
 */
void servo_set_us(servo_id_t id, uint16_t pulse_us);

/**
 * 直接设置，不做限幅也不做缓动。仅用于标定与测试。
 * ⚠️ 生产代码不要调用。
 */
void servo_set_us_raw(servo_id_t id, uint16_t pulse_us);

/**
 * 缓动推进。由控制任务按 SERVO_SLEW_INTERVAL_MS 周期调用。
 * 返回 true 表示本次有实际变化。
 */
bool servo_update(void);

/** 当前实际脉宽（微秒）。 */
uint16_t servo_get_us(servo_id_t id);

/** 目标脉宽（微秒）。 */
uint16_t servo_get_target_us(servo_id_t id);

/** 是否已到达目标。 */
bool servo_settled(servo_id_t id);

/** 立即把目标值写进 CCR（跳过缓动）。用于安全停机时快速到位。 */
void servo_flush(void);

#endif /* SERVO_H */
