/**
 * @file    vision_proto.h
 * @brief   视觉链路协议 v1.1 解析
 *
 * 帧格式：  @T,SEQ,CLASS,CONF,CX,CY,W,H,DIST*HH\n
 * 示例：    @T,102,WEED,0.91,173,119,52,64,0*6F
 *
 * 设计要点：
 *   1. 逐字节状态机，不依赖"一帧必须一次收完"。
 *      串口数据天然是字节流，任何按行读取的实现都会在丢字节时永久错位。
 *   2. CRC-8 校验失败 ⇒ 整帧丢弃。绝不"尽力解析"。
 *      这条链最终驱动电机，一个被噪声翻转的字节就能让 CX=173 变成 773。
 *   3. 所有数值做范围检查。ASCII 协议下 "ABCD" 也能被 strtol 解析成 0，
 *      必须显式拒绝非数字与越界。
 *   4. 解析层与业务层彻底分离：本模块只产出 VisionTarget 结构体，
 *      不知道电机、不知道控制算法。
 */
#ifndef VISION_PROTO_H
#define VISION_PROTO_H

#include <stdint.h>
#include <stdbool.h>

/* --------------------------------------------------------------------------
 * 目标类别。编码必须与 OpenMV 侧 uart_protocol.py 的字符串严格一致。
 * ------------------------------------------------------------------------ */
typedef enum {
    VCLS_NONE = 0,   /* 无目标 —— 链路存活但当前无作业对象 */
    VCLS_WEED,       /* 杂草 —— 作业目标 */
    VCLS_CROP,       /* 作物 —— 必须避开 */
    VCLS_UNKNOWN
} vision_class_t;

/* --------------------------------------------------------------------------
 * 解析结果结构体。这是协议层与业务层之间唯一的契约。
 * ------------------------------------------------------------------------ */
typedef struct {
    uint32_t       seq;        /* 帧序号，用于检测丢帧 */
    vision_class_t cls;
    float          confidence; /* 0.0 ~ 1.0 */
    int16_t        cx;         /* 目标中心 X（像素） */
    int16_t        cy;         /* 目标中心 Y（像素） */
    int16_t        width;      /* 目标框宽（像素） */
    int16_t        height;     /* 目标框高（像素） */
    uint16_t       dist_mm;    /* 距离（毫米），0 = 无效/未标定 */
    float          err_x;      /* cx - LINK_IMG_CENTER_X，由协议层算好 */
} VisionTarget;

/* --------------------------------------------------------------------------
 * 错误码。用于统计，不用于控制流。
 * ------------------------------------------------------------------------ */
typedef enum {
    VERR_NONE = 0,
    VERR_CRC,
    VERR_FIELD_COUNT,
    VERR_FIELD_FORMAT,
    VERR_RANGE,
    VERR_TOO_LONG,
    VERR_UNKNOWN_CLASS
} vision_err_t;

/* --------------------------------------------------------------------------
 * 统计量。联调阶段看这些计数就能定位问题出在哪一层。
 * ------------------------------------------------------------------------ */
typedef struct {
    uint32_t frames_ok;
    uint32_t err_crc;
    uint32_t err_field;
    uint32_t err_range;
    uint32_t err_len;
    uint32_t err_class;
    uint32_t seq_gap;      /* 累计丢帧数 */
    uint32_t last_seq;
    uint32_t first_seq;
    bool     seq_inited;
} proto_stats_t;

/* --------------------------------------------------------------------------
 * 解析器实例。
 * ⚠️ 不要做成全局单例后从多个任务访问。
 *    本结构体只允许"一个生产者（UART 任务）"使用。
 * ------------------------------------------------------------------------ */
#define PROTO_LINE_MAX  96

typedef struct {
    /* 状态机 */
    uint8_t  state;
    uint8_t  body[PROTO_LINE_MAX];
    uint16_t body_len;
    uint8_t  crc_hi;        /* 已收到的高位 hex 字符 */
    uint8_t  crc_chars;     /* 已收到的 hex 字符数 */
    uint8_t  crc_calc;      /* 边收边算的 CRC 值 */

    /* 输出 */
    VisionTarget last;      /* 最近一次成功解析的目标 */
    proto_stats_t stats;
} vision_proto_t;

/* --------------------------------------------------------------------------
 * API
 * ------------------------------------------------------------------------ */

/** 初始化解析器。必须在任何 feed 之前调用一次。 */
void vision_proto_init(vision_proto_t *p);

/**
 * 喂入一个字节。
 * @return true 表示本次输入补全了一个合法帧，p->last 已被更新。
 */
bool vision_proto_feed(vision_proto_t *p, uint8_t byte);

/**
 * 批量喂入。等价于循环调用 feed，但省去函数调用开销。
 * @return 本次解析成功的帧数（通常为 0 或 1）
 */
uint32_t vision_proto_feed_buf(vision_proto_t *p, const uint8_t *buf, uint16_t len);

/** 取最近一次成功解析的目标（拷贝）。 */
void vision_proto_get_last(const vision_proto_t *p, VisionTarget *out);

/** 复位状态机与统计（用于错误恢复后重新同步）。 */
void vision_proto_reset(vision_proto_t *p);

/** CRC-8, poly=0x07, init=0x00。与 OpenMV 侧实现必须逐位一致。 */
uint8_t vision_crc8(const uint8_t *data, uint16_t len);

/**
 * 构造一个合法帧（含 CRC 与换行）。返回写入字节数，0 表示缓冲不足。
 * 用于回环自测：不接视觉节点也能验证解析层与控制层。
 */
uint16_t vision_proto_build_frame(uint8_t *out, uint16_t out_sz,
                                  uint32_t seq, const char *cls,
                                  uint16_t conf_hundredths,
                                  int16_t cx, int16_t cy,
                                  int16_t w, int16_t h, uint16_t dist_mm);

/**
 * 自检：核对 CRC 测试向量与若干解析用例。
 * ⚠️ 上电时调用一次。若返回 false，说明本固件与 OpenMV 侧协议不一致，
 *    此时继续运行只会浪费时间在"为什么一直收不到有效帧"上。
 */
bool vision_proto_selftest(void);

const char *vision_class_name(vision_class_t c);

#endif /* VISION_PROTO_H */
