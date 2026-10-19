/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : stm32f4xx_hal_msp.c
  * @brief          : MSP 初始化 —— GPIO/时钟的底层配置
  *
  * 对应 CubeMX 生成的同文件。本文件只管"引脚与时钟"，
  * 不涉及任何中断使能（中断在 main.c 的 MX_*_Init 与
  * stm32f4xx_it.c 中管理）。
  ******************************************************************************
  */
/* USER CODE END Header */

#include "main.h"
#include "FreeRTOS.h"
#include "task.h"

/* External functions --------------------------------------------------------*/
void vApplicationGetIdleTaskMemory(StaticTask_t **ppxIdleTaskTCBBuffer,
                                   StackType_t **ppxIdleTaskStackBuffer,
                                   uint32_t *pulIdleTaskStackSize);

/**
  * Initializes the Global MSP.
  */
void HAL_MspInit(void)
{
  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();
  /* System interrupt init（EXTI 的 SYSCFG 时钟已在上面使能） */
}

/**
  * @brief UART MSP Initialization
  *        USART1: PA9 → USART1_TX（→ OpenMV RX）
  *                PA10 → USART1_RX（← OpenMV TX）
  */
void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (huart->Instance == USART1)
  {
    __HAL_RCC_USART1_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    GPIO_InitStruct.Pin = GPIO_PIN_9 | GPIO_PIN_10;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
  }
}

/**
  * @brief TIM MSP Initialization
  *        TIM3: PA6/PA7 → TIM3_CH1/CH2（AF2）执行机构舵机
  *        TIM4: PB6/PB7 → TIM4_CH1/CH2（AF2）履带电机
  */
void HAL_TIM_PWM_MspInit(TIM_HandleTypeDef *htim_pwm)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (htim_pwm->Instance == TIM3)
  {
    __HAL_RCC_TIM3_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE();

    GPIO_InitStruct.Pin = GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM3;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
  }
  else if (htim_pwm->Instance == TIM4)
  {
    __HAL_RCC_TIM4_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    GPIO_InitStruct.Pin = GPIO_PIN_6 | GPIO_PIN_7;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    GPIO_InitStruct.Alternate = GPIO_AF2_TIM4;
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
  }
}

/**
  * @brief FreeRTOS 静态空闲任务内存
  * configSUPPORT_DYNAMIC_ALLOCATION=0，空闲任务缓冲必须由应用提供。
  * 本工程不使用软件定时器（configUSE_TIMERS=0），故无需
  * vApplicationGetTimerTaskMemory。
  */
static StaticTask_t xIdleTaskTCB;
static StackType_t  uxIdleTaskStack[configMINIMAL_STACK_SIZE];

void vApplicationGetIdleTaskMemory(StaticTask_t **ppxIdleTaskTCBBuffer,
                                   StackType_t **ppxIdleTaskStackBuffer,
                                   uint32_t *pulIdleTaskStackSize)
{
  *ppxIdleTaskTCBBuffer   = &xIdleTaskTCB;
  *ppxIdleTaskStackBuffer = uxIdleTaskStack;
  *pulIdleTaskStackSize   = configMINIMAL_STACK_SIZE;
}
