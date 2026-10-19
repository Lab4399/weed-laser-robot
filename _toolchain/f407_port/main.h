/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c. 外设句柄与 MX_* 原型声明。
  *
  * 对应交付包 firmware/stm32f407/README.md 的「CubeMX 集成」一节：
  *   main.c / stm32f4xx_hal_msp.c / stm32f4xx_it.c 三个文件按该文档的
  *   USER CODE 区段要求手工维护（本工程不用 CubeMX 生成，改为直接编写）。
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef __MAIN_H
#define __MAIN_H

#include "stm32f4xx_hal.h"

/* Exported types ------------------------------------------------------------*/
/* Exported constants --------------------------------------------------------*/
/* Exported macro ------------------------------------------------------------*/
/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* Private defines -----------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* 状态指示灯（沿用 Good_Dog 固件的 PB2，兼容已有接线） */
#define LED_Pin           GPIO_PIN_2
#define LED_GPIO_Port     GPIOB

/* 电机驱动器 STBY —— 安全切除的硬件执行点 */
#define MOTOR_STBY_Pin    GPIO_PIN_11
#define MOTOR_STBY_Port   GPIOB

/* 电机方向脚 PB12~PB15 */
#define MOTOR_L_IN1_Pin   GPIO_PIN_12
#define MOTOR_L_IN2_Pin   GPIO_PIN_13
#define MOTOR_R_IN1_Pin   GPIO_PIN_14
#define MOTOR_R_IN2_Pin   GPIO_PIN_15
#define MOTOR_DIR_Port    GPIOB

/* 急停输入 PE0 / EXTI0 */
#define ESTOP_Pin         GPIO_PIN_0
#define ESTOP_GPIO_Port   GPIOE
#define ESTOP_EXTI_IRQn   EXTI0_IRQn

/* USER CODE END PD */

/* Exported variables --------------------------------------------------------*/
extern UART_HandleTypeDef huart1;
extern DMA_HandleTypeDef  hdma_usart1_rx;
extern TIM_HandleTypeDef  htim3;      /* 舵机 50 Hz */
extern TIM_HandleTypeDef  htim4;      /* 电机 20 kHz */
extern IWDG_HandleTypeDef hiwdg;

/* Private function prototypes -----------------------------------------------
 * MX_*_Init() 与 SystemClock_Config() 的实现都在 main.c 内，
 * 不对外暴露（MX_*_Init 在 main.c 里是 static）。
 */

#endif /* __MAIN_H */
