/**
 * @file    app_main.h
 * @brief   应用层入口。由 CubeMX 生成的 main.c 调用，不要写主循环。
 */
#ifndef APP_MAIN_H
#define APP_MAIN_H

/**
 * 应用初始化 + 启动调度器。本函数不返回。
 *
 * 调用位置：CubeMX 生成的 Core/Src/main.c 中，
 *           MX_*_Init() 调用之后、while (1) 之前，
 *           放在 USER CODE BEGIN 2 / END 2 区段内。
 *
 * ⚠️ 调用前提：调用方必须已经完成
 *    1. HAL_Init() 与 SystemClock_Config()
 *    2. NVIC 优先级分组设置（HAL_Init 默认已是 GROUP_4）
 *    3. 各外设的 MX_*_Init()（USART1 / DMA / TIM3 / TIM4 / IWDG 除外——IWDG 在本函数内启动）
 */
void app_main(void);

#endif /* APP_MAIN_H */
