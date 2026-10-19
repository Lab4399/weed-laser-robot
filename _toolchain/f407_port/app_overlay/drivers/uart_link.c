/**
 * @file    uart_link.c
 * @brief   视觉链路 UART 接收驱动实现（DMA 循环 + IDLE + 环形缓冲）
 */
#include "uart_link.h"
#include "../Core/app_config.h"

#include "stm32f4xx_hal.h"
#include <string.h>

/* ===========================================================================
 *  环形缓冲
 * =========================================================================== */
static uint8_t  s_ring[LINK_RING_SZ];
static volatile uint16_t s_ring_head;   /* 生产者（IDLE ISR）写 */
static volatile uint16_t s_ring_tail;   /* 消费者（任务）读   */

static uint8_t  s_dma_buf[LINK_DMA_BUF_SZ];
static volatile uint16_t s_dma_last;    /* 上次已搬运到的 DMA 位置 */

static uart_link_stats_t s_stats;

extern UART_HandleTypeDef LINK_UART;
extern DMA_HandleTypeDef  hdma_usart1_rx;

/* ===========================================================================
 *  内部工具
 * =========================================================================== */

/** DMA 当前已写入的位置（0 .. LINK_DMA_BUF_SZ-1） */
static inline uint16_t dma_pos(void)
{
    /* NDTR = 剩余未传输个数；已写位置 = 缓冲长度 - 剩余 */
    uint16_t remain = (uint16_t)__HAL_DMA_GET_COUNTER(&hdma_usart1_rx);
    return (uint16_t)((LINK_DMA_BUF_SZ - remain) & (LINK_DMA_BUF_SZ - 1));
}

/**
 * 向环形缓冲压入一个字节。满时丢弃并计数。
 *
 * 这里刻意选择"丢弃新字节"而不是"覆盖最旧字节"：
 * 协议层是逐字节状态机，丢新字节最多导致本帧 CRC 失败（可检测）；
 * 覆盖旧字节会破坏帧中间的内容，可能解析出一个 CRC 恰好正确的错误帧。
 * 对一个驱动电机的链路，宁可丢帧也不能出假帧。
 */
static inline void ring_push(uint8_t b)
{
    uint16_t next = (uint16_t)((s_ring_head + 1) & (LINK_RING_SZ - 1));
    if (next == s_ring_tail) {
        s_stats.ring_overflow++;
        return;
    }
    s_ring[s_ring_head] = b;
    s_ring_head = next;
}

/**
 * 把 DMA 缓冲中 [from, to) 一段搬进环形缓冲，正确处理回绕。
 *
 * ⚠️ 这是本驱动最容易写错的地方。F407 的 NDTR 从 0 回绕到 BUF_SZ-1，
 *    若只用 "to > from 才拷贝" 的判断，每次回绕都会静默丢掉一段数据。
 *    现象是"帧率莫名下降、偶发 CRC 错"，且随发送速率变化而时有时无。
 */
static void copy_chunk(uint16_t from, uint16_t to)
{
    if (from == to) return;
    uint16_t n;

    if (to > from) {
        n = (uint16_t)(to - from);
        for (uint16_t i = from; i < to; i++) ring_push(s_dma_buf[i]);
    } else {
        n = (uint16_t)((LINK_DMA_BUF_SZ - from) + to);
        for (uint16_t i = from; i < LINK_DMA_BUF_SZ; i++) ring_push(s_dma_buf[i]);
        for (uint16_t i = 0; i < to; i++) ring_push(s_dma_buf[i]);
    }
    s_stats.bytes_rx += n;
}

/* ===========================================================================
 *  公开接口
 * =========================================================================== */
void uart_link_init(void)
{
    memset(&s_stats, 0, sizeof(s_stats));
    s_ring_head = 0;
    s_ring_tail = 0;
    s_dma_last = 0;

    /* DMA 循环模式常驻接收。不需要每帧重启 —— 重启间隙会丢字节。
     *
     * ⚠️ 这里只能调用一次 HAL_UART_Receive_DMA：它内部已经通过
     *    __HAL_LINKDMA 关联的 hdmarx 调用了 HAL_DMA_Start_IT。
     *    原代码在它后面又手动 HAL_DMA_Start_IT 了一次，第二次必然返回
     *    HAL_BUSY —— 因为流已经处于 BUSY 状态 —— 于是 dma_err 恒为 1，
     *    看起来像"DMA 出错"，实际是重复启动。真出故障时这个计数就不再有
     *    区分度，等于把唯一有效的诊断信号废掉了。 */
    if (HAL_UART_Receive_DMA(&LINK_UART, s_dma_buf, LINK_DMA_BUF_SZ) != HAL_OK) {
        s_stats.dma_err++;
    }

    /* 使能 IDLE 中断：DMA 负责搬字节，"帧结束"由硬件空闲检测通知 */
    __HAL_UART_ENABLE_IT(&LINK_UART, UART_IT_IDLE);

    /* 同时使能错误中断，用于捕获 ORE/NE/FE/PE。
     * ORE（溢出）是最常见的：一旦发生且不处理，UART 会持续丢字节，
     * 而且标志位不清会反复触中断，形成中断风暴。 */
    __HAL_UART_ENABLE_IT(&LINK_UART, UART_IT_ERR);
}

uint16_t uart_link_read(uint8_t *out, uint16_t max_len)
{
    if (out == NULL || max_len == 0) return 0;

    uint16_t n = 0;
    while (n < max_len && s_ring_tail != s_ring_head) {
        out[n++] = s_ring[s_ring_tail];
        s_ring_tail = (uint16_t)((s_ring_tail + 1) & (LINK_RING_SZ - 1));
    }
    return n;
}

bool uart_link_send(const uint8_t *data, uint16_t len)
{
    if (data == NULL || len == 0) return false;
    /* 阻塞式，仅用于低频调试输出与下行命令。
     * ⚠️ 不要在控制周期内调用 —— 50 ms 的超时会直接吃掉整个控制周期。
     *    HAL_UART_Transmit 的签名要求非 const 指针，这里做一次显式转换；
     *    该函数不会修改发送缓冲（只是读取后写 DR）。 */
    return HAL_UART_Transmit(&LINK_UART, (uint8_t *)(uintptr_t)data, len, 50) == HAL_OK;
}

void uart_link_idle_isr(void)
{
    if (__HAL_UART_GET_FLAG(&LINK_UART, UART_FLAG_IDLE) == RESET) {
        return;
    }
    /* 清 IDLE 标志的标准做法：先读 SR 再读 DR，两步都不能省。
     * 只写 __HAL_UART_CLEAR_IDLEFLAG 在某些 HAL 版本上清不掉，
     * 结果是中断反复触发，CPU 被吃满且看起来像"程序卡死"。 */
    __HAL_UART_CLEAR_IDLEFLAG(&LINK_UART);

    s_stats.irq_count++;

    uint16_t now = dma_pos();
    copy_chunk(s_dma_last, now);
    s_dma_last = now;
}

void uart_link_error_isr(void)
{
    uint32_t sr = LINK_UART.Instance->SR;

    if (sr & USART_SR_ORE) {
        /* ORE：接收溢出。必须读 DR 清除，否则标志一直有效，
         * 中断会被反复触发。丢掉的字节由协议层 CRC 兜住。 */
        volatile uint32_t tmp = LINK_UART.Instance->DR;
        (void)tmp;
        s_stats.ore_err++;
    }
    if (sr & USART_SR_FE) {
        volatile uint32_t tmp = LINK_UART.Instance->DR;
        (void)tmp;
    }
    if (sr & USART_SR_NE) {
        volatile uint32_t tmp = LINK_UART.Instance->DR;
        (void)tmp;
    }
    if (sr & USART_SR_PE) {
        volatile uint32_t tmp = LINK_UART.Instance->DR;
        (void)tmp;
    }
}

const uart_link_stats_t *uart_link_stats(void)
{
    return &s_stats;
}
