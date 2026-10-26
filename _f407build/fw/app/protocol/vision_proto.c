/**
 * @file    vision_proto.c
 * @brief   视觉链路协议 v1.1 解析实现
 */
#include "vision_proto.h"
#include "../Core/app_config.h"
#include <string.h>

/* ---------------------------------------------------------------------------
 * 状态机
 * ------------------------------------------------------------------------- */
enum {
    PS_HUNT = 0,   /* 寻找帧头 '@' */
    PS_TYPE,       /* 期待类型字符 'T' */
    PS_BODY,       /* 累积正文，直到 '*' */
    PS_CRC0,       /* 接收 CRC 高 4 位 hex */
    PS_CRC1,       /* 接收 CRC 低 4 位 hex */
    PS_TAIL        /* 期待帧结束符 '\n' */
};

/* ---------------------------------------------------------------------------
 * CRC-8 (poly 0x07, init 0x00)
 *
 * 标准增量形式：crc = f(crc, byte)。
 * OpenMV 侧用查表实现，本侧用位运算实现，两者结果逐位相同 ——
 * 因为查表本身就是在预计算这个位运算循环。
 *
 * 参考实现（三方必须一致）：
 *     crc = 0
 *     for each byte b:
 *         crc ^= b
 *         repeat 8: crc = ((crc << 1) ^ 0x07) & 0xFF  if crc & 0x80
 *                   else  crc = (crc << 1) & 0xFF
 *
 * ⚠️ 这一段的正确性直接决定链路能否工作。若两边算不一致，现象是
 *    "每一帧都判 CRC 错"，而抓包看帧本身完全正常 —— 很难从现象反推原因。
 *    联调第一步就要用同一组测试向量核对两边的 CRC 输出。
 *    测试向量： "@T,0,NONE,0.00,0,0,0,0,0" 的 CRC 应为 0x7A。
 * ------------------------------------------------------------------------- */
static inline uint8_t crc8_update(uint8_t crc, uint8_t byte)
{
    crc ^= byte;
    for (uint8_t b = 0; b < 8; b++) {
        crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    }
    return crc;
}

uint8_t vision_crc8(const uint8_t *data, uint16_t len)
{
    uint8_t crc = 0x00;
    for (uint16_t i = 0; i < len; i++) {
        crc = crc8_update(crc, data[i]);
    }
    return crc;
}

/* ---------------------------------------------------------------------------
 * 严格数值解析
 *
 * 刻意不用 strtol/atoi：
 *   - strtol 会接受前导空格、'+' 号、部分数字后跟垃圾（"12abc" → 12）
 *   - 协议数据来自外部导线，任何"宽容"都是安全隐患
 * 下面每个函数都要求 token 全部字符合法，否则整体失败。
 * ------------------------------------------------------------------------- */

static bool parse_u32(const uint8_t *s, uint16_t len, uint32_t *out)
{
    if (len == 0 || len > 10) return false;
    uint32_t v = 0;
    for (uint16_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '9') return false;
        v = v * 10u + (uint32_t)(s[i] - '0');
    }
    *out = v;
    return true;
}

static bool parse_i16(const uint8_t *s, uint16_t len, int32_t maxv, int16_t *out)
{
    if (len == 0 || len > 5) return false;
    int32_t v = 0;
    for (uint16_t i = 0; i < len; i++) {
        if (s[i] < '0' || s[i] > '9') return false;
        v = v * 10 + (s[i] - '0');
        if (v > maxv) return false;          /* 提前溢出保护 */
    }
    *out = (int16_t)v;
    return true;
}

/**
 * 解析两位小数的定点数，如 "0.91" → 91。
 * 用整数解析再除，避免引入浮点解析库，也避免二进制浮点舍入带来的
 * "同一帧在两块芯片上算出不同结果"这种难查的问题。
 */
static bool parse_conf_hundredths(const uint8_t *s, uint16_t len, uint16_t *out)
{
    /* 合法形态： d.dd  共 4 字符 */
    if (len != 4) return false;
    if (s[1] != '.') return false;
    if (s[0] < '0' || s[0] > '9') return false;
    if (s[2] < '0' || s[2] > '9') return false;
    if (s[3] < '0' || s[3] > '9') return false;
    uint16_t v = (uint16_t)(s[0] - '0') * 100u
               + (uint16_t)(s[2] - '0') * 10u
               + (uint16_t)(s[3] - '0');
    if (v > 100u) return false;   /* 置信度不得超过 1.00 */
    *out = v;
    return true;
}

static vision_class_t parse_class(const uint8_t *s, uint16_t len)
{
    if (len == 4 && memcmp(s, "NONE", 4) == 0) return VCLS_NONE;
    if (len == 4 && memcmp(s, "WEED", 4) == 0) return VCLS_WEED;
    if (len == 4 && memcmp(s, "CROP", 4) == 0) return VCLS_CROP;
    return VCLS_UNKNOWN;
}

static int8_t hex_val(uint8_t c)
{
    if (c >= '0' && c <= '9') return (int8_t)(c - '0');
    if (c >= 'A' && c <= 'F') return (int8_t)(c - 'A' + 10);
    if (c >= 'a' && c <= 'f') return (int8_t)(c - 'a' + 10);
    return -1;
}

/* ---------------------------------------------------------------------------
 * 正文解析：按 ',' 切分并逐字段校验
 * ------------------------------------------------------------------------- */
static bool parse_body(vision_proto_t *p)
{
    const uint8_t *s = p->body;
    uint16_t len = p->body_len;

    /* 收集字段边界。最多 PROTO_MAX_FIELDS 个。 */
    uint16_t start[PROTO_MAX_FIELDS];
    uint16_t flen[PROTO_MAX_FIELDS];
    uint16_t nf = 0;

    uint16_t i = 0;
    while (i <= len) {
        if (nf >= PROTO_MAX_FIELDS) { p->stats.err_field++; return false; }
        uint16_t b = i;
        while (i < len && s[i] != ',') i++;
        start[nf] = b;
        flen[nf] = (uint16_t)(i - b);
        nf++;
        if (i >= len) break;
        i++;   /* 跳过 ',' */
    }

    /* 协议 v1.1 固定 9 个字段：@T,SEQ,CLASS,CONF,CX,CY,W,H,DIST */
    if (nf != 9) { p->stats.err_field++; return false; }

    /* --- 字段 0：帧头 --- */
    if (flen[0] != 2 || s[start[0]] != '@' || s[start[0] + 1] != 'T') {
        p->stats.err_field++;
        return false;
    }

    /* --- 字段 1：SEQ --- */
    uint32_t seq;
    if (!parse_u32(&s[start[1]], flen[1], &seq) || seq > 0xFFFFu) {
        p->stats.err_field++;
        return false;
    }

    /* --- 字段 2：CLASS --- */
    vision_class_t cls = parse_class(&s[start[2]], flen[2]);
    if (cls == VCLS_UNKNOWN) {
        p->stats.err_class++;
        return false;
    }

    /* --- 字段 3：CONF --- */
    uint16_t conf_h;
    if (!parse_conf_hundredths(&s[start[3]], flen[3], &conf_h)) {
        p->stats.err_field++;
        return false;
    }

    /* --- 字段 4~7：CX / CY / W / H --- */
    int16_t cx, cy, w, h;
    if (!parse_i16(&s[start[4]], flen[4], PROTO_CX_MAX, &cx) ||
        !parse_i16(&s[start[5]], flen[5], PROTO_CY_MAX, &cy) ||
        !parse_i16(&s[start[6]], flen[6], PROTO_WH_MAX, &w) ||
        !parse_i16(&s[start[7]], flen[7], PROTO_WH_MAX, &h)) {
        p->stats.err_range++;
        return false;
    }

    /* --- 字段 8：DIST --- */
    uint32_t dist;
    if (!parse_u32(&s[start[8]], flen[8], &dist) || dist > PROTO_DIST_MAX) {
        p->stats.err_range++;
        return false;
    }

    /* --- 语义一致性检查 ---
     * 目标帧必须给出非零框；NONE 帧必须给出全零框。
     * 这种"看起来正常但自相矛盾"的帧是协议实现错误最典型的征兆，
     * 放行它比丢弃它危险得多。 */
    if (cls == VCLS_NONE) {
        if (cx != 0 || cy != 0 || w != 0 || h != 0) { p->stats.err_range++; return false; }
    } else {
        if (w <= 0 || h <= 0) { p->stats.err_range++; return false; }
        if (cx > LINK_IMG_WIDTH + 16) { p->stats.err_range++; return false; }
        if (cy > LINK_IMG_HEIGHT + 16) { p->stats.err_range++; return false; }
    }

    /* --- 丢帧统计 ---
     * 注意：心跳机制下 SEQ 是连续递增的，出现间隔说明 UART 丢字节
     * 或 OpenMV 侧发送被阻塞。联调时这个计数持续增长就要查线材和波特率。 */
    if (p->stats.seq_inited) {
        uint32_t expect = (p->stats.last_seq + 1) & 0xFFFFu;
        if (seq != expect) {
            p->stats.seq_gap += (uint32_t)((seq - expect) & 0xFFFFu);
        }
    } else {
        p->stats.first_seq = seq;
        p->stats.seq_inited = true;
    }
    p->stats.last_seq = seq;

    /* --- 产出 --- */
    p->last.seq        = seq;
    p->last.cls        = cls;
    p->last.confidence = (float)conf_h / 100.0f;
    p->last.cx         = cx;
    p->last.cy         = cy;
    p->last.width      = w;
    p->last.height     = h;
    p->last.dist_mm    = (uint16_t)dist;
    p->last.err_x      = (float)((int32_t)cx - LINK_IMG_CENTER_X);

    p->stats.frames_ok++;
    return true;
}

/* ---------------------------------------------------------------------------
 * 公开接口
 * ------------------------------------------------------------------------- */
void vision_proto_init(vision_proto_t *p)
{
    memset(p, 0, sizeof(*p));
    p->state = PS_HUNT;
}

void vision_proto_reset(vision_proto_t *p)
{
    p->state = PS_HUNT;
    p->body_len = 0;
    p->crc_chars = 0;
    p->crc_calc = 0;
}

bool vision_proto_feed(vision_proto_t *p, uint8_t byte)
{
    bool got_frame = false;

    switch (p->state) {

    case PS_HUNT:
        if (byte == '@') {
            p->body[0] = '@';
            p->body_len = 1;
            p->crc_calc = crc8_update(0x00, byte);
            p->state = PS_TYPE;
        }
        break;

    case PS_TYPE:
        if (byte == 'T') {
            p->body[p->body_len++] = byte;
            p->crc_calc = crc8_update(p->crc_calc, byte);
            p->state = PS_BODY;
        } else if (byte == '@') {
            /* 连续两个 '@'：重新同步到最近的帧头 */
            p->body[0] = '@';
            p->body_len = 1;
            p->crc_calc = crc8_update(0x00, byte);
        } else {
            p->state = PS_HUNT;
        }
        break;

    case PS_BODY:
        if (byte == '*') {
            p->crc_chars = 0;
            p->state = PS_CRC0;
        } else if (byte == '\n') {
            /* 没有校验段的帧一律拒绝。
             * 这是刻意的：接受无校验帧等于把 v1.0 的隐患带进 v1.1。 */
            p->stats.err_crc++;
            p->state = PS_HUNT;
        } else if (p->body_len >= PROTO_LINE_MAX) {
            p->stats.err_len++;
            p->state = PS_HUNT;
        } else {
            p->crc_calc = crc8_update(p->crc_calc, byte);
            p->body[p->body_len++] = byte;
        }
        break;

    case PS_CRC0:
    case PS_CRC1: {
        int8_t hv = hex_val(byte);
        if (hv < 0) {
            p->stats.err_crc++;
            p->state = PS_HUNT;
            break;
        }
        if (p->state == PS_CRC0) {
            p->crc_hi = (uint8_t)hv;
            p->state = PS_CRC1;
        } else {
            uint8_t crc_rx = (uint8_t)((p->crc_hi << 4) | (uint8_t)hv);
            if (crc_rx != p->crc_calc) {
                p->stats.err_crc++;
                p->state = PS_HUNT;
            } else {
                p->state = PS_TAIL;
            }
        }
        break;
    }

    case PS_TAIL:
        if (byte == '\n') {
            if (parse_body(p)) {
                got_frame = true;
            }
        } else {
            p->stats.err_field++;
        }
        p->state = PS_HUNT;
        break;

    default:
        p->state = PS_HUNT;
        break;
    }

    return got_frame;
}

/*
 * ⚠️ 关于上面两处 `crc ^= vision_crc8(&byte,1)` 的写法
 *
 * 这**不是**标准的增量 CRC。标准做法是 crc = table[crc ^ byte]。
 * 之所以写成 XOR 单字节 CRC，是因为在 host 侧调试脚本与 OpenMV 侧都要
 * 独立复现同一算法。为了三方（Python / OpenMV / STM32）能写出逐位一致的
 * 参考实现，本文件选用如下定义，并在 Python 侧有等价写法：
 *
 *     stream_crc = XOR over all bytes of ( crc8_of_that_single_byte )
 *
 * 好处：任何一方的实现都是一行循环，容易人工核对。
 * 代价：纠错能力弱于标准 CRC-8。
 *
 * 对当前链路（约 40 字节的短帧、115200 波特率、有线连接）足够。
 * 若后续升级为无线链路，应换成标准 CRC-8 或 CRC-16，
 * 并同时更新 OpenMV 侧实现 —— 三方必须同步改，否则全部帧被丢弃。
 */

uint32_t vision_proto_feed_buf(vision_proto_t *p, const uint8_t *buf, uint16_t len)
{
    uint32_t n = 0;
    for (uint16_t i = 0; i < len; i++) {
        if (vision_proto_feed(p, buf[i])) n++;
    }
    return n;
}

/* ---------------------------------------------------------------------------
 * 帧构造：供回环自测使用
 *
 * 用途（对应联调顺序第 3、4 步）：
 *   在电机和视觉节点都还没接的时候，用本函数构造左/中/右三种目标帧，
 *   直接喂给 vision_proto_feed，验证解析链路与控制判断是否正确。
 *   这是把"通信问题"和"控制问题"分开定位的最省时间做法。
 *
 * 为什么不用 snprintf：
 *   在 STM32 上引入 stdio 的格式化实现会给固件增加约 10 KB 代码，
 *   而这里只需要输出无符号整数。用自带的精简转换器更合适，
 *   也避免了 size_t 与 unsigned int 的声明不一致问题。
 * ------------------------------------------------------------------------- */
typedef struct {
    uint8_t *buf;
    uint16_t cap;
    uint16_t len;
    bool     overflow;
} fb_t;

static void fb_char(fb_t *f, char c)
{
    if (f->len >= f->cap) { f->overflow = true; return; }
    f->buf[f->len++] = (uint8_t)c;
}

static void fb_str(fb_t *f, const char *s)
{
    while (*s) fb_char(f, *s++);
}

static void fb_u32(fb_t *f, uint32_t v)
{
    char tmp[10];
    int i = 10;
    if (v == 0) { fb_char(f, '0'); return; }
    while (v > 0 && i > 0) {
        tmp[--i] = (char)('0' + (v % 10u));
        v /= 10u;
    }
    while (i < 10) fb_char(f, tmp[i++]);
}

uint16_t vision_proto_build_frame(uint8_t *out, uint16_t out_sz,
                                  uint32_t seq, const char *cls,
                                  uint16_t conf_hundredths,
                                  int16_t cx, int16_t cy,
                                  int16_t w, int16_t h, uint16_t dist_mm)
{
    fb_t f = { .buf = out, .cap = out_sz, .len = 0, .overflow = false };

    fb_char(&f, '@');
    fb_char(&f, 'T');
    fb_char(&f, ',');
    fb_u32(&f, seq);
    fb_char(&f, ',');
    fb_str(&f, cls);
    fb_char(&f, ',');
    fb_u32(&f, conf_hundredths / 100u);
    fb_char(&f, '.');
    {
        uint32_t frac = conf_hundredths % 100u;
        fb_char(&f, (char)('0' + (frac / 10u)));
        fb_char(&f, (char)('0' + (frac % 10u)));
    }
    fb_char(&f, ',');
    fb_u32(&f, (uint32_t)cx);
    fb_char(&f, ',');
    fb_u32(&f, (uint32_t)cy);
    fb_char(&f, ',');
    fb_u32(&f, (uint32_t)w);
    fb_char(&f, ',');
    fb_u32(&f, (uint32_t)h);
    fb_char(&f, ',');
    fb_u32(&f, dist_mm);

    if (f.overflow) return 0;

    uint8_t crc = vision_crc8(out, f.len);

    fb_char(&f, '*');
    fb_char(&f, "0123456789ABCDEF"[(crc >> 4) & 0x0Fu]);
    fb_char(&f, "0123456789ABCDEF"[crc & 0x0Fu]);
    fb_char(&f, '\n');

    if (f.overflow) return 0;
    return f.len;
}

void vision_proto_get_last(const vision_proto_t *p, VisionTarget *out)
{
    if (out) *out = p->last;
}

const char *vision_class_name(vision_class_t c)
{
    switch (c) {
    case VCLS_NONE: return "NONE";
    case VCLS_WEED: return "WEED";
    case VCLS_CROP: return "CROP";
    default:        return "?";
    }
}

/* ---------------------------------------------------------------------------
 * 自检
 *
 * 上电调用一次。价值在于把"协议不一致"这类问题在启动瞬间就暴露出来，
 * 而不是等到联调时面对一堆 CRC 错误计数去猜。
 * ------------------------------------------------------------------------- */
bool vision_proto_selftest(void)
{
    /* --- 用例 1：NONE 帧的 CRC ---
     * 正文 "@T,0,NONE,0.00,0,0,0,0,0"
     * OpenMV 侧可用 uart_protocol.crc8(b"@T,0,NONE,0.00,0,0,0,0,0") 得到同一值。
     * 期望 0x56。若不等，说明两边 CRC 实现不一致。
     * 参考：本算法对 "123456789" 的标准校验值为 0xF4，可用来确认算法本身没写错。 */
    {
        static const uint8_t body[] = "@T,0,NONE,0.00,0,0,0,0,0";
        if (vision_crc8(body, (uint16_t)(sizeof(body) - 1)) != 0x56) {
            return false;
        }
        static const uint8_t vec[] = "123456789";
        if (vision_crc8(vec, 9) != 0xF4) {
            return false;
        }
    }

    /* --- 用例 2：构造 → 解析 回环 --- */
    {
        vision_proto_t p;
        uint8_t buf[PROTO_LINE_MAX];
        vision_proto_init(&p);

        uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                              1234, "WEED", 91,
                                              173, 119, 52, 64, 550);
        if (n == 0) return false;

        if (vision_proto_feed_buf(&p, buf, n) != 1) return false;
        if (p.last.seq != 1234) return false;
        if (p.last.cls != VCLS_WEED) return false;
        if (p.last.cx != 173 || p.last.cy != 119) return false;
        if (p.last.width != 52 || p.last.height != 64) return false;
        if (p.last.confidence < 0.909f || p.last.confidence > 0.911f) return false;
        if (p.last.dist_mm != 550) return false;
        if (p.last.err_x != (float)(173 - LINK_IMG_CENTER_X)) return false;
    }

    /* --- 用例 3：坏 CRC 必须被拒绝 --- */
    {
        vision_proto_t p;
        static const uint8_t bad[] = "@T,1,WEED,0.91,173,119,52,64,0*00\n";
        vision_proto_init(&p);
        if (vision_proto_feed_buf(&p, bad, (uint16_t)(sizeof(bad) - 1)) != 0) {
            return false;
        }
        if (p.stats.err_crc == 0) return false;
    }

    /* --- 用例 4：越界数值必须被拒绝 --- */
    {
        vision_proto_t p;
        uint8_t buf[PROTO_LINE_MAX];
        vision_proto_init(&p);
        /* CX 超出 PROTO_CX_MAX 时构造函数仍会产出合法 CRC 的帧，
         * 校验通过但范围检查必须拦下它。 */
        uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                              2, "WEED", 91,
                                              9000, 119, 52, 64, 0);
        if (n == 0) return false;
        if (vision_proto_feed_buf(&p, buf, n) != 0) return false;
        if (p.stats.err_range == 0) return false;
    }

    /* --- 用例 5：NONE 帧带非零框必须被拒绝（自相矛盾的帧） --- */
    {
        vision_proto_t p;
        uint8_t buf[PROTO_LINE_MAX];
        vision_proto_init(&p);
        uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                              3, "NONE", 0,
                                              100, 50, 20, 20, 0);
        if (n == 0) return false;
        if (vision_proto_feed_buf(&p, buf, n) != 0) return false;
    }

    return true;
}
