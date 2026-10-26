/**
 * @file    app_tasks.h
 * @brief   FreeRTOS 任务创建与调度编排
 *
 * 任务清单（优先级数值越大越高）：
 *
 *  | 任务        | 优先级 | 周期   | 职责                                    |
 *  |-------------|--------|--------|-----------------------------------------|
 *  | task_safety | 10     | 1 ms   | 状态机推进、链路超时、唯一喂狗点          |
 *  | task_motion | 8      | 10 ms  | 控制律计算 + 限速输出到电机               |
 *  | task_vision | 6      | 5 ms   | UART 取字节 → 协议解析 → 更新共享目标      |
 *  | task_diag   | 1      | 1000 ms| 状态打印（ITM/SWO），不占用主链路 UART     |
 *
 * ── 为什么安全任务是最高优先级 ──
 *   它负责喂狗和链路超时判定。若它被低优先级任务饿死，
 *   看门狗会误复位，且链路超时判定会失去意义。
 *
 * ── 为什么诊断打印单独一个最低优先级任务 ──
 *   打印是阻塞 I/O。1 ms 的安全任务里只要有一次耗时 50 ms 的串口发送，
 *   就等于整个安全机制停摆 50 个周期。
 */
#ifndef APP_TASKS_H
#define APP_TASKS_H

#include "../protocol/vision_proto.h"

/** 创建全部任务并启动调度器。本函数不返回。 */
void app_tasks_start(void);

/**
 * 取最近一次解析成功的目标（线程安全）。
 * @param out          输出
 * @param lost_frames  自上次有效 WEED 目标以来累计的帧数
 * @return true 表示 out 中是一个有效的非 NONE 目标
 */
bool app_get_target(VisionTarget *out, uint32_t *lost_frames);

/** 已解析成功的帧总数。 */
uint32_t app_good_frames(void);

#endif /* APP_TASKS_H */
