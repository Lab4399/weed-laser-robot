/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : stm32f4xx_it.c
  * @brief          : 中断服务程序
  *
  * 中断优先级分配（抢占值，数值越小越高）：
  *   EXTI0 急停            = 1   独立于一切软件调度，直接切驱动器 STBY
  *   USART1 / DMA2_Stream2 = 6   ≥5，满足 FreeRTOS API 安全边界
  *   SysTick（FreeRTOS tick）= 15 最低
  *
  * SysTick_Handler 采用 CubeMX + FreeRTOS 的标准形态：
  * 同时驱动 HAL tick（HAL_IncTick）与 RTOS tick（xPortSysTickHandler），
  * 后者在调度器启动前不调用（xTaskGetSchedulerState 守卫）。
  ******************************************************************************
  */
/* USER CODE END Header */

#include "main.h"
#include "app/drivers/uart_link.h"
#include "app/services/safety.h"
#include "FreeRTOS.h"
#include "task.h"

/* External variables --------------------------------------------------------*/
extern UART_HandleTypeDef huart1;
extern DMA_HandleTypeDef  hdma_usart1_rx;

/* FreeRTOS Cortex-M4F 移植的处理器 handler（声明在 portable/GCC/ARM_CM4F/port.c，
 * 不在任何头文件里，这里显式 extern）。
 * ⚠️ SVC / PendSV / SysTick 三个 handler 是 FreeRTOS 的命脉：
 *    PendSV 承担上下文切换，绝不能留空或改写。 */
extern void vPortSVCHandler(void);
extern void xPortPendSVHandler(void);
extern void xPortSysTickHandler(void);

/******************************************************************************/
/*           Cortex-M4 Processor Interruption and Exception Handlers          */
/******************************************************************************/

void NMI_Handler(void)
{
  while (1) { }
}

void HardFault_Handler(void)
{
  while (1) { }
}

void MemManage_Handler(void)
{
  while (1) { }
}

void BusFault_Handler(void)
{
  while (1) { }
}

void UsageFault_Handler(void)
{
  while (1) { }
}

void DebugMon_Handler(void) { }

/******************************************************************************/
/* STM32F4xx Peripheral Interrupt Handlers                                    */
/******************************************************************************/

/**
  * @brief USART1 中断：IDLE（帧结束）+ ERR（ORE/FE/NE/PE）
  * 先跑 uart_link 的钩子（清 IDLE / 清错误标志），
  * 再走 HAL 的标准处理（此时标志已清，HAL 侧为空操作）。
  */
void USART1_IRQHandler(void)
{
  uart_link_idle_isr();
  uart_link_error_isr();
  HAL_UART_IRQHandler(&huart1);
}

/**
  * @brief DMA2_Stream2 中断：USART1_RX
  * 循环模式下 TC/HT 回调均为 HAL 弱空函数，这里只负责清标志。
  */
void DMA2_Stream2_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_usart1_rx);
}

/**
  * @brief EXTI0 急停中断（PE0，下降沿）
  * ISR 内只做两件绝对必要的事：置标志 + 直写 GPIO 切 STBY。
  * 不调用任何 RTOS API，不做任何日志。
  */
void EXTI0_IRQHandler(void)
{
  /* USER CODE BEGIN EXTI0_IRQn 0 */
  __HAL_GPIO_EXTI_CLEAR_IT(GPIO_PIN_0);
  safety_estop_isr();
  /* USER CODE END EXTI0_IRQn 0 */
  HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_0);
}

/**
  * @brief SVC：FreeRTOS 内核系统调用入口
  */
void SVC_Handler(void)
{
  vPortSVCHandler();
}

/**
  * @brief PendSV：FreeRTOS 上下文切换（优先级最低）
  */
void PendSV_Handler(void)
{
  xPortPendSVHandler();
}

/**
  * @brief SysTick：HAL tick + FreeRTOS tick
  * RTOS tick 在调度器启动前不调用（xTaskGetSchedulerState 守卫），
  * 否则 vPortSysTickHandler 会在内核未初始化时操作任务链表。
  */
void SysTick_Handler(void)
{
  HAL_IncTick();
#if (INCLUDE_xTaskGetSchedulerState == 1)
  if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED)
  {
#endif
    xPortSysTickHandler();
#if (INCLUDE_xTaskGetSchedulerState == 1)
  }
#endif
}
