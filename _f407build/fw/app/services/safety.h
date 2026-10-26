/**
 * @file    safety.h
 * @brief   系统状态机、链路安全、看门狗仲裁、故障管理
 *
 * ── 本模块是整车的"看门人"，规则集中且不允许旁路 ──
 *
 *   1. 唯一喂狗者：只有本模块的仲裁函数可以刷新 IWDG。
 *      多任务各自喂狗会让看门狗退化成随机定时器 —— 任何单任务卡死都检测不到。
 *
 *   2. 链路超时分级：短暂丢帧只降速，持续无帧才切功率。
 *      把"偶发丢帧"和"线被拽断"做同一处理，会让小车在路上频繁顿停。
 *
 *   3. 故障分级与恢复策略：
 *        WARN      → 记录，继续
 *        DEGRADE   → 降速运行
 *        SAFE_STOP → 切功率输出，保持通信在线（便于远程诊断）
 *        FAULT     → 锁死，仅人工复位
 *      锁死设计是刻意的：过流、连续看门狗复位这类故障若允许自动恢复，
 *      会形成"故障—恢复—再故障"的自激循环，比直接停机危险得多。
 */
#ifndef SAFETY_H
#define SAFETY_H

#include <stdint.h>
#include <stdbool.h>

/* --------------------------------------------------------------------------
 * 系统状态
 * ------------------------------------------------------------------------ */
typedef enum {
    SYS_INIT = 0,      /* 上电自检中，输出全关 */
    SYS_IDLE,          /* 待机/手动模式，电机使能关闭 */
    SYS_AUTO,          /* 自动跟踪作业 */
    SYS_SAFE_STOP,     /* 安全停机：功率切断，通信保留 */
    SYS_FAULT          /* 故障锁死：仅人工复位可解除 */
} sys_state_t;

/* --------------------------------------------------------------------------
 * 故障码
 * ------------------------------------------------------------------------ */
typedef enum {
    FAULT_NONE = 0,
    FAULT_LINK_TIMEOUT,     /* 视觉链路持续无有效帧 */
    FAULT_CRC_BURST,        /* CRC 错误率超限，疑似线材/波特率问题 */
    FAULT_ESTOP,            /* 急停输入触发 */
    FAULT_TASK_STALL,       /* 关键任务心跳超时 */
    FAULT_PARAM_LOST,       /* 参数双备份全损，已回退出厂值 */
    FAULT_IWDG_REPEAT,      /* 连续多次看门狗复位 */
    FAULT_MOTOR_DISABLED,   /* 驱动器使能被意外关闭 */
} fault_code_t;

/* --------------------------------------------------------------------------
 * 心跳 ID
 * ------------------------------------------------------------------------ */
typedef enum {
    HB_VISION = 0,     /* 视觉接收任务 */
    HB_CONTROL = 1,    /* 控制任务 */
    HB_MOTION = 2,     /* 运动输出任务 */
    HB_COUNT_ = 3
} safety_hb_t;

/* --------------------------------------------------------------------------
 * 状态快照（供诊断输出）
 * ------------------------------------------------------------------------ */
typedef struct {
    sys_state_t   state;
    fault_code_t  fault;
    uint32_t      good_frames;
    uint32_t      uptime_ms;
    uint32_t      iwdg_resets;
    bool          estop_active;
    bool          link_alive;
} safety_snapshot_t;

/* --------------------------------------------------------------------------
 * API
 * ------------------------------------------------------------------------ */

/**
 * 初始化。内部会读取 RCC->CSR 判定上次复位原因，
 * 并在读取后立即清除标志（不清则下次复位无法区分）。
 */
void safety_init(void);

/**
 * 1 ms 周期调用（由最高优先级的安全任务执行）。
 * 职责：推进状态机、检查心跳、判定链路超时、唯一的喂狗点。
 */
void safety_tick_1ms(void);

/** 每解析出一个合法帧时调用。用于刷新链路存活时间并触发 AUTO 进入。 */
void safety_on_valid_frame(void);

/** 每次 CRC 失败时调用。用于检测突发错误率。 */
void safety_on_crc_error(void);

/** 任务心跳上报。关键任务必须在窗口内周期性调用。 */
void safety_heartbeat(safety_hb_t id);

/** 主动上报故障。 */
void safety_raise_fault(fault_code_t code);

/** 人工清除锁死故障（仅在 SYS_FAULT 下有意义）。 */
void safety_clear_fault(void);

/** 请求进入自动模式（例如收到上位机的启动命令）。 */
void safety_request_auto(bool enable);

/** 急停输入 ISR 调用。设置标志并在 ISR 内直接切断驱动器使能。 */
void safety_estop_isr(void);

bool safety_estop_active(void);

void safety_get_snapshot(safety_snapshot_t *out);

const char *safety_state_name(sys_state_t s);
const char *safety_fault_name(fault_code_t f);

#endif /* SAFETY_H */
