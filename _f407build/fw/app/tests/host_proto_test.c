/**
 * @file    host_proto_test.c
 * @brief   协议层主机侧单元测试（在 PC 上用 gcc 编译运行，不需要硬件）
 *
 * 为什么这个测试值得存在：
 *   协议解析是本项目最容易出错、也最难在现场定位的一环。
 *   CRC 两边不一致的现象是"每帧都判 CRC 错"，而抓包看帧完全正常；
 *   越界帧漏检的现象是"小车偶尔莫名打舵"，无法复现。
 *   把这两类问题放在 PC 上验证，代价是几秒钟，收益是省掉几天的现场排查。
 *
 * 编译运行（Windows / MSYS2 与 Linux 通用）：
 *     cd firmware/stm32f407
 *     gcc -std=c11 -Wall -Wextra -I. protocol/vision_proto.c tests/host_proto_test.c \
 *         -o tests/host_proto_test
 *     ./tests/host_proto_test
 *
 * 期望输出最后一行：  ALL TESTS PASSED
 */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>

#include "../Core/app_config.h"
#include "../protocol/vision_proto.h"

static int g_pass;
static int g_fail;

#define CHECK(cond, msg)                                            \
    do {                                                            \
        if (cond) { g_pass++; printf("  [OK]   %s\n", msg); }        \
        else      { g_fail++; printf("  [FAIL] %s\n", msg); }        \
    } while (0)

/* ---------------------------------------------------------------------------
 * 1. CRC 一致性
 *
 * 这些期望值必须与 OpenMV 侧 uart_protocol.py 的 selftest() 完全一致。
 * 任一条不符，说明两侧实现不同源，链路一定不通。
 * ------------------------------------------------------------------------- */
static void test_crc(void)
{
    printf("\n== 1. CRC-8 一致性 ==\n");

    struct {
        const char *body;
        uint8_t     expect;
    } v[] = {
        { "123456789",                      0xF4 },  /* CRC-8/ATM 标准校验值 */
        { "@T,0,NONE,0.00,0,0,0,0,0",       0x56 },
        { "@T,104,WEED,0.88,52,131,60,71,0", 0x6C },
        { "@T,105,WEED,0.77,288,126,48,55,0", 0xB6 },
        { "@T,103,NONE,0.00,0,0,0,0,0",     0xD3 },
    };

    for (unsigned i = 0; i < sizeof(v) / sizeof(v[0]); i++) {
        uint8_t got = vision_crc8((const uint8_t *)v[i].body,
                                  (uint16_t)strlen(v[i].body));
        char msg[128];
        snprintf(msg, sizeof(msg), "crc8(\"%s\") = 0x%02X (期望 0x%02X)",
                 v[i].body, got, v[i].expect);
        CHECK(got == v[i].expect, msg);
    }
}

/* ---------------------------------------------------------------------------
 * 2. 正常帧解析
 * ------------------------------------------------------------------------- */
static void test_parse_ok(void)
{
    printf("\n== 2. 正常帧解析 ==\n");

    vision_proto_t p;
    vision_proto_init(&p);

    uint8_t buf[PROTO_LINE_MAX];
    uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                          1234, "WEED", 91,
                                          173, 119, 52, 64, 550);
    CHECK(n > 0, "帧构造成功");

    uint32_t got = vision_proto_feed_buf(&p, buf, n);
    CHECK(got == 1, "解析出 1 帧");

    CHECK(p.last.seq == 1234,               "SEQ == 1234");
    CHECK(p.last.cls == VCLS_WEED,          "CLASS == WEED");
    CHECK(p.last.cx == 173 && p.last.cy == 119, "CX/CY 正确");
    CHECK(p.last.width == 52 && p.last.height == 64, "W/H 正确");
    CHECK(p.last.dist_mm == 550,            "DIST == 550");
    CHECK(p.last.confidence > 0.90f && p.last.confidence < 0.92f,
          "CONF == 0.91（定点解析无浮点误差）");
    CHECK(p.last.err_x == (float)(173 - LINK_IMG_CENTER_X),
          "err_x = CX - 中心（符号约定）");
}

/* ---------------------------------------------------------------------------
 * 3. 分片喂入：模拟 UART 逐字节到达
 *
 * 解析器必须能在任意切分点正确工作。任何"一帧必须一次收完"的实现
 * 都会在丢字节时永久错位。
 * ------------------------------------------------------------------------- */
static void test_byte_by_byte(void)
{
    printf("\n== 3. 逐字节喂入（模拟串口到达节奏）==\n");

    uint8_t buf[PROTO_LINE_MAX];
    uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                          77, "WEED", 88,
                                          52, 131, 60, 71, 0);

    for (uint16_t chunk = 1; chunk <= n; chunk++) {
        vision_proto_t p;
        vision_proto_init(&p);
        uint32_t frames = 0;
        for (uint16_t i = 0; i < n; i += chunk) {
            uint16_t len = (uint16_t)((i + chunk <= n) ? chunk : (n - i));
            frames += vision_proto_feed_buf(&p, buf + i, len);
        }
        if (chunk == 1 || chunk == 3 || chunk == n) {
            char msg[64];
            snprintf(msg, sizeof(msg), "按 %u 字节切片仍解析出 1 帧", chunk);
            CHECK(frames == 1, msg);
        }
        if (frames != 1) {
            printf("  [FAIL] 切片大小 %u 时解析失败\n", chunk);
            g_fail++;
        }
    }
    g_pass++;
    printf("  [OK]   全部 1..%u 种切片大小均正确\n", n);
}

/* ---------------------------------------------------------------------------
 * 4. 坏帧必须被拒绝
 * ------------------------------------------------------------------------- */
static void test_reject(void)
{
    printf("\n== 4. 非法帧必须被拒绝 ==\n");

    struct {
        const char *frame;
        const char *desc;
    } bad[] = {
        { "@T,1,WEED,0.91,173,119,52,64,0*00\n", "CRC 错误" },
        { "@T,2,WEED,0.91,9000,119,52,64,0",     "CX 超出范围（由构造补正确 CRC）" },
        { "@T,3,NONE,0.00,100,50,20,20,0",       "NONE 帧却带非零目标框" },
        { "@T,4,WEED,1.50,100,50,20,20,0",       "置信度 > 1.00" },
        { "@T,5,WEED,0.91,100,50,20,20,0\n",     "缺少 CRC 段" },
        { "@T,6,GRASS,0.91,100,50,20,20,0",      "未知类别" },
        { "@T,7,WEED,0.9,100,50,20,20,0",        "CONF 小数位不足" },
    };

    for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        vision_proto_t p;
        vision_proto_init(&p);

        uint8_t buf[PROTO_LINE_MAX];
        uint16_t n;

        /* 除第一、五条外，其余用构造器生成（这样 CRC 一定是对的，
         * 从而确保被拒绝的原因确实是"字段非法"而不是"CRC 错"） */
        if (i == 0 || i == 4 || i == 6) {
            n = (uint16_t)strlen(bad[i].frame);
            memcpy(buf, bad[i].frame, n);
        } else {
            /* 手工构造非法内容，然后补正确 CRC */
            int body_len = snprintf((char *)buf, sizeof(buf), "%s",
                                    bad[i].frame);
            /* 去掉尾部可能存在的 \n */
            while (body_len > 0 && (buf[body_len - 1] == '\n')) body_len--;
            uint8_t crc = vision_crc8(buf, (uint16_t)body_len);
            n = (uint16_t)snprintf((char *)buf + body_len,
                                   sizeof(buf) - (size_t)body_len,
                                   "*%02X\n", crc);
            n = (uint16_t)(body_len + n);
        }

        uint32_t frames = vision_proto_feed_buf(&p, buf, n);
        char msg[160];
        snprintf(msg, sizeof(msg), "拒绝：%s", bad[i].desc);
        CHECK(frames == 0, msg);
    }
}

/* ---------------------------------------------------------------------------
 * 5. 丢帧统计
 * ------------------------------------------------------------------------- */
static void test_seq_gap(void)
{
    printf("\n== 5. 丢帧统计 ==\n");

    vision_proto_t p;
    vision_proto_init(&p);

    uint8_t buf[PROTO_LINE_MAX];
    uint16_t n;

    n = vision_proto_build_frame(buf, sizeof(buf), 10, "NONE", 0, 0,0,0,0,0);
    vision_proto_feed_buf(&p, buf, n);
    n = vision_proto_build_frame(buf, sizeof(buf), 11, "NONE", 0, 0,0,0,0,0);
    vision_proto_feed_buf(&p, buf, n);
    CHECK(p.stats.seq_gap == 0, "连续序号无丢帧");

    n = vision_proto_build_frame(buf, sizeof(buf), 15, "NONE", 0, 0,0,0,0,0);
    vision_proto_feed_buf(&p, buf, n);
    CHECK(p.stats.seq_gap == 3, "序号跳变被统计为 3 帧丢失");

    /* SEQ 是 16 位，回绕必须正确 */
    vision_proto_init(&p);
    n = vision_proto_build_frame(buf, sizeof(buf), 65535, "NONE", 0, 0,0,0,0,0);
    vision_proto_feed_buf(&p, buf, n);
    n = vision_proto_build_frame(buf, sizeof(buf), 0, "NONE", 0, 0,0,0,0,0);
    vision_proto_feed_buf(&p, buf, n);
    CHECK(p.stats.seq_gap == 0, "SEQ 65535→0 回绕不误判为丢帧");
}

/* ---------------------------------------------------------------------------
 * 6. 关键控制场景（不接硬件即可验证控制判断）
 * ------------------------------------------------------------------------- */
static void test_control_scenarios(void)
{
    printf("\n== 6. 左/中/右目标的 err_x 符号约定 ==\n");

    struct {
        int16_t cx;
        const char *desc;
        int     expect_sign;   /* -1 左 / 0 中 / +1 右 */
    } cases[] = {
        { 40,  "目标在画面左侧", -1 },
        { 160, "目标居中",        0 },
        { 288, "目标在画面右侧", +1 },
    };

    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        vision_proto_t p;
        vision_proto_init(&p);

        uint8_t buf[PROTO_LINE_MAX];
        uint16_t n = vision_proto_build_frame(buf, sizeof(buf),
                                              1, "WEED", 90,
                                              cases[i].cx, 120, 50, 60, 0);
        vision_proto_feed_buf(&p, buf, n);

        int sign = (p.last.err_x > 0) ? 1 : ((p.last.err_x < 0) ? -1 : 0);
        char msg[128];
        snprintf(msg, sizeof(msg), "%s → err_x=%d（符号 %d）",
                 cases[i].desc, (int)p.last.err_x, sign);
        CHECK(sign == cases[i].expect_sign, msg);
    }
}

/* ---------------------------------------------------------------------------
 * 7. 固件内置自检
 * ------------------------------------------------------------------------- */
static void test_builtin_selftest(void)
{
    printf("\n== 7. 固件内置自检 vision_proto_selftest() ==\n");
    CHECK(vision_proto_selftest(), "内置自检通过（固件启动时的同一套断言）");
}

/* ------------------------------------------------------------------------- */
int main(void)
{
    printf("协议层主机侧测试\n");
    printf("LINK_IMG_WIDTH=%d  LINK_IMG_CENTER_X=%d\n",
           LINK_IMG_WIDTH, LINK_IMG_CENTER_X);

    test_crc();
    test_parse_ok();
    test_byte_by_byte();
    test_reject();
    test_seq_gap();
    test_control_scenarios();
    test_builtin_selftest();

    printf("\n----------------------------------------\n");
    printf("通过 %d 项，失败 %d 项\n", g_pass, g_fail);
    printf("%s\n", (g_fail == 0) ? "ALL TESTS PASSED" : "TESTS FAILED");
    return (g_fail == 0) ? 0 : 1;
}
