/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : stm32f4xx_hal_conf.h
  * @brief          : HAL configuration file.
  *
  * 本文件由本工程手工维护（非 CubeMX 生成），只启用本固件用到的模块。
  * 裁剪原则：每多编译一个 HAL 模块，Flash 就多几 KB。
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __STM32F4xx_HAL_CONF_H
#define __STM32F4xx_HAL_CONF_H

#ifdef __cplusplus
 extern "C" {
#endif

/* Exported types ------------------------------------------------------------*/
/* Exported constants --------------------------------------------------------*/

/* ########################## Module Selection ############################## */
#define HAL_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_IWDG_MODULE_ENABLED

/* ########################## HSE/HSI Values adaptation ##################### */
#define HSE_VALUE    (25000000U)
#define HSI_VALUE    (16000000U)
#define LSI_VALUE    (32000U)
#define EXTERNAL_CLOCK_VALUE    (8000000U)   /* TIM/EXT 外部时钟源，本项目未用，按 CubeMX 默认值 */

/* 振荡器启动超时（ms）—— CubeMX 生成的标准值 */
#define HSE_STARTUP_TIMEOUT            100U
#define LSE_STARTUP_TIMEOUT            5000U
/* LSI_STARTUP_TIME 已由 stm32f407xx.h 定义为 40U，不要重复定义 */

/* ########################## System Configuration ######################### */
#define  VDD_VALUE                    (3300U)
#define  TICK_INT_PRIORITY            (15U)   /* SysTick 最低优先级，FreeRTOS 要求 */
#define  USE_RTOS                     0U   /* HAL 1.8.x 已不再分支处理 RTOS，必须为 0 */
#define  PREFETCH_ENABLE              1U
#define  INSTRUCTION_CACHE_ENABLE     1U
#define  DATA_CACHE_ENABLE            1U

#define  USE_SPI_CRC                  0U

/* Includes ------------------------------------------------------------------*/
#ifdef HAL_RCC_MODULE_ENABLED
  #include "stm32f4xx_hal_rcc.h"
#endif
#ifdef HAL_GPIO_MODULE_ENABLED
  #include "stm32f4xx_hal_gpio.h"
#endif
#ifdef HAL_DMA_MODULE_ENABLED
  #include "stm32f4xx_hal_dma.h"
#endif
#ifdef HAL_CORTEX_MODULE_ENABLED
  #include "stm32f4xx_hal_cortex.h"
#endif
#ifdef HAL_FLASH_MODULE_ENABLED
  #include "stm32f4xx_hal_flash.h"
#endif
#ifdef HAL_PWR_MODULE_ENABLED
  #include "stm32f4xx_hal_pwr.h"
#endif
#ifdef HAL_UART_MODULE_ENABLED
  #include "stm32f4xx_hal_uart.h"
#endif
#ifdef HAL_TIM_MODULE_ENABLED
  #include "stm32f4xx_hal_tim.h"
#endif
#ifdef HAL_IWDG_MODULE_ENABLED
  #include "stm32f4xx_hal_iwdg.h"
#endif

/* Exported macro ------------------------------------------------------------*/
#ifdef  USE_FULL_ASSERT
#define assert_param(expr) ((expr) ? (void)0U : assert_failed((uint8_t *)__FILE__, __LINE__))
void assert_failed(uint8_t* file, uint32_t line);
#else
#define assert_param(expr) ((void)0U)
#endif

#ifdef __cplusplus
}
#endif

#endif /* __STM32F4xx_HAL_CONF_H */
