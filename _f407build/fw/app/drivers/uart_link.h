/**
 * @file    uart_link.h
 * @brief   视觉链路 UART 接收驱动（DMA 循环 + IDLE 空闲中断 + 环形缓冲）
 *
 * 为什么不用 HAL_UART_Receive_IT 逐字节中断：
 *   115200 波特率下每字节 87 µs，一帧 40 字节 = 40 次中断。
 *   OpenMV 按 50 ms 心跳持续发送时，中断负载会持续占用 CPU，
 *   并且和 FreeRTOS 的 tick 中断、控制环中断抢优先级。
 *   本项目的控制环对抖动敏感，不能把中断时间浪费在搬字节上。
 *
 * 为什么用 DMA 循环模式 + IDLE：
 *   IDLE 中断在"总线空闲一个字符时间"时触发，正好对应一帧结束。
 *   用它可以把"帧边界检测"交给硬件，CPU 只在帧结束时处理一次。
 *   DMA 用循环模式常驻运行，不需要每帧重启，避免了重启间隙丢字节。
 *
 * ⚠️ 最常见的实现 bug：DMA 传输计数器回绕时丢数据。
 *    F407 的 DMA NDTR 会从 0 回绕到 BUF_SZ-1，若直接用
 *    "pos > last_pos 才拷贝" 的判断，回绕的那一段会被静默丢弃。
 *    本实现在 copy_chunk() 里显式处理了回绕分支。
 */
#ifndef UART_LINK_H
#define UART_LINK_H

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    uint32_t irq_count;      /* IDLE 中断次数 */
    uint32_t bytes_rx;       /* 累计接收字节 */
    uint32_t ring_overflow;  /* 环形缓冲溢出（丢字节）次数 */
    uint32_t dma_err;        /* DMA 错误次数 */
    uint32_t ore_err;        /* USART 溢出错误次数 */
} uart_link_stats_t;

/** 初始化：启动 DMA 循环接收并使能 IDLE 中断。 */
void uart_link_init(void);

/**
 * 从环形缓冲取出数据（非阻塞）。
 * @return 实际取出的字节数，0 表示当前无数据。
 */
uint16_t uart_link_read(uint8_t *out, uint16_t max_len);

/**
 * 发送数据。
 * ⚠️ 阻塞式，超时 50 ms。只用于低频调试输出与后续的下行命令，
 *    不要在控制周期内调用，也不要用于发送高频数据。
 */
bool uart_link_send(const uint8_t *data, uint16_t len);

/** 从 IDLE 中断里调用。 */
void uart_link_idle_isr(void);

/** 从 DMA 错误中断里调用。 */
void uart_link_error_isr(void);

const uart_link_stats_t *uart_link_stats(void);

#endif /* UART_LINK_H */
