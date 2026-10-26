/**
 * @file    motion.h
 * @brief   运动控制：误差 → 左右履带占空比
 *
 * 分层原则（协议文档第 5 节）：
 *   控制算法只处理解析后的 VisionTarget，不接触任何字符。
 *   本模块不 include 任何 UART / 协议相关头文件。
 */
#ifndef MOTION_H
#define MOTION_H

#include <stdint.h>
#include <stdbool.h>
#include "../protocol/vision_proto.h"

typedef struct {
    int16_t base_speed;    /* 基础速度，千分比 */
    float   kp_turn;       /* 转向比例系数，千分比/像素 */
    int16_t deadzone_px;   /* 中心死区 */
    int16_t slew_step;     /* 每控制周期的占空比最大变化量 */
    int16_t duty_max;      /* 输出限幅 */
} motion_params_t;

typedef struct {
    int16_t left_desired;  /* 算法算出的期望值 */
    int16_t right_desired;
    int16_t left_applied;  /* 经限速后真正写进 PWM 的值 */
    int16_t right_applied;
    float   near_score;    /* 0~1，接近程度 */
    float   turn;          /* 本次的转向分量 */
} motion_state_t;

void motion_init(void);

void motion_get_params(motion_params_t *out);
void motion_set_params(const motion_params_t *in);

/** 用停止指令覆盖期望值（不影响参数）。急停与故障时调用。 */
void motion_request_stop(void);

/**
 * 根据视觉目标更新期望值。不直接写 PWM。
 * @param t           最近一帧目标
 * @param lost_frames 连续丢失目标的帧数
 */
void motion_command(const VisionTarget *t, uint32_t lost_frames);

/**
 * 控制周期回调（CTRL_PERIOD_MS）。做限速并真正输出到电机。
 * 必须由固定周期的任务调用，不能由事件驱动。
 */
void motion_tick(void);

void motion_get_state(motion_state_t *out);

#endif /* MOTION_H */
