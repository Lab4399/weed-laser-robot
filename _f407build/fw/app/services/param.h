/**
 * @file    param.h
 * @brief   参数持久化（F407 内部 Flash 双 Bank 乒乓）
 *
 * ── 为什么是双 Bank 而不是单份 ──
 *
 *   单份存储的致命场景：擦除过程中掉电 ⇒ 参数区变成空白。
 *   下次上电读到全 0xFF，若代码没有校验就会把 base_speed=0xFFFFFFFF
 *   当成 4294967295 用 —— 或者更糟，当成 0 静默使用。
 *
 *   双 Bank 乒乓保证：任意时刻至少有一份完整数据。
 *   写入时永远擦除"序号较小的那个"，所以正在被读的那一份不会被碰。
 *
 * ── 关于擦除耗时 ──
 *
 *   F407 单个 128 KB sector 的擦除时间典型值约 1 秒，最坏可到 4 秒。
 *   期间 CPU 从 Flash 取指会停顿（除非代码搬到了 RAM 执行）。
 *   因此：
 *     · 绝不在中断或控制周期内调用 param_save()
 *     · 保存操作必须在 SYS_IDLE / SYS_SAFE_STOP 状态下进行
 *     · 保存前先确认电机已停、伺服已到位
 */
#ifndef PARAM_H
#define PARAM_H

#include <stdint.h>
#include <stdbool.h>
#include "../control/motion.h"

#define PARAM_SERVO_LIMITS 3   /* min / center / max */

typedef struct {
    /* --- 运动控制 --- */
    motion_params_t motion;

    /* --- 舵机脉宽标定（µs）--- */
    uint16_t servo_a[PARAM_SERVO_LIMITS];
    uint16_t servo_b[PARAM_SERVO_LIMITS];

    /* --- 预留 --- */
    uint32_t reserved[4];
} param_payload_t;

/**
 * 初始化：从两个 Bank 中选出有效且序号最大的那份载入。
 * 两份都无效时加载出厂默认值并上报 FAULT_PARAM_LOST。
 */
void param_init(void);

/** 取当前生效参数（拷贝）。 */
void param_get(param_payload_t *out);

/**
 * 更新内存中的参数（不落盘）。会做范围校验。
 * @return true 表示参数合法且已接受
 */
bool param_set(const param_payload_t *in);

/**
 * 把当前参数写入 Flash。
 *
 * ⚠️ 阻塞约 1~4 秒。只在无作业时调用。
 * @return true 表示写入并校验成功
 */
bool param_save(void);

/** 恢复出厂默认（仅改内存，需再调 param_save 才落盘）。 */
void param_load_defaults(void);

/** 上次载入时两份 Bank 是否都无效。 */
bool param_was_lost(void);

/* 诊断用：当前生效数据所在的 Bank 与序号。
 * 刻意不提供"格式化字符串"接口 —— 那会把 stdio 的格式化实现
 * 拖进固件（约 10 KB），而诊断只需要两个整数。 */
int8_t   param_current_bank(void);
uint32_t param_current_seq(void);

#endif /* PARAM_H */
