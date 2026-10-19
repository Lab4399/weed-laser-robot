/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : 主程序 —— 只做外设初始化，应用逻辑全部在 app_main()
  *
  * 本文件对应交付包 firmware/stm32f407/README.md「CubeMX 集成」一节要求的
  * main.c 形态。之所以不直接用 CubeMX 生成，是因为本机构网环境无法运行
  * CubeMX 的 GUI 流程；所有 MX_*_Init() 按 README 规定的顺序手工实现，
  * 与 CubeMX 生成的代码等价。
  *
  * 初始化顺序（有约束，不可调换）：
  *   HAL_Init() → SystemClock_Config() → GPIO → DMA → USART1 → TIM3 → TIM4
  *   → IWDG（最后一个）→ app_main()（不返回）
  *
  * 时钟：板上无外部晶振（沿用 Good_Dog 固件的结论），HSI 16MHz
  *       PLLM=16 PLLN=336 PLLP=2 → SYSCLK 168MHz
  *       APB1 /4 = 42MHz（TIM3/TIM4 时钟 84MHz），APB2 /2 = 84MHz
  *       该配置已由实机 RCC 寄存器读回值（CFGR=0x0000940A）验证。
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "app/Core/app_main.h"

/* Private typedef -----------------------------------------------------------*/
/* Private define ------------------------------------------------------------*/
/* Private macro -------------------------------------------------------------*/
/* Private variables ---------------------------------------------------------*/
/* 外设句柄定义（main.h 中 extern 声明）。名字由 app_config.h 的别名宏映射：
 *   LINK_UART → huart1, MOTOR_TIM → htim4, SERVO_TIM → htim3, hiwdg */
UART_HandleTypeDef huart1;
DMA_HandleTypeDef  hdma_usart1_rx;
TIM_HandleTypeDef  htim3;      /* 舵机 50 Hz  */
TIM_HandleTypeDef  htim4;      /* 电机 20 kHz  */
IWDG_HandleTypeDef hiwdg;

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_TIM3_Init(void);
static void MX_TIM4_Init(void);
static void MX_IWDG_Init(void);

/* Private user code ---------------------------------------------------------*/

int main(void)
{
  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* Configure the system clock */
  SystemClock_Config();

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_USART1_UART_Init();
  MX_TIM3_Init();
  MX_TIM4_Init();

  /* USER CODE BEGIN 2 */
  /* ★保留 Good_Dog 的安全上电姿态：PB2 状态灯先熄灭，
     电机 STBY 保持禁用，等 app_main() 里的安全模块接管。
     上电不驱动任何执行器 —— 这是"安全版"改造的延续。 */
  HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_RESET);
  /* USER CODE END 2 */

  /* ⚠️ IWDG 必须是初始化块里最后一个 MX_*_Init 调用，且紧邻 app_main()。
     放在前面会让"上电即复位"变成一个连打印都没有的诡异现象。 */
  MX_IWDG_Init();

  /* USER CODE BEGIN 2 */
  app_main();          /* 不返回 */
  /* USER CODE END 2 */

  while (1)
  {
  }
}

/**
  * @brief System Clock Configuration
  * @retval None
  *
  * HSI 16MHz → PLL(336/2) → SYSCLK 168MHz；APB1 /4 = 42MHz；APB2 /2 = 84MHz
  * 与 Good_Dog 固件逐字节一致的时钟配置（该固件已在本机长期稳定运行）。
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 16;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief GPIO 初始化
  *   PB2   输出   状态指示灯（沿用 Good_Dog 接线）
  *   PB11  输出   电机驱动器 STBY（上电即禁用）
  *   PB12~PB15 输出 电机方向脚（上电全低 = 滑行）
  *   PE0   输入   EXTI0 急停（下降沿）
  *   PA9/PA10 由 USART1 MSP 配置（AF8）
  *   PB6/PB7（TIM4）、PA6/PA7（TIM3）由 TIM MSP 配置
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOE_CLK_ENABLE();

  /* 上电默认电平：方向脚与 STBY 全低（驱动器禁用） */
  HAL_GPIO_WritePin(MOTOR_DIR_Port, MOTOR_L_IN1_Pin | MOTOR_L_IN2_Pin
                                   | MOTOR_R_IN1_Pin | MOTOR_R_IN2_Pin,
                    GPIO_PIN_RESET);
  HAL_GPIO_WritePin(MOTOR_STBY_Port, MOTOR_STBY_Pin, GPIO_PIN_RESET);

  /* PB2 状态灯 */
  GPIO_InitStruct.Pin = LED_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED_GPIO_Port, &GPIO_InitStruct);

  /* PB11 STBY + PB12~PB15 方向 */
  GPIO_InitStruct.Pin = MOTOR_STBY_Pin
                      | MOTOR_L_IN1_Pin | MOTOR_L_IN2_Pin
                      | MOTOR_R_IN1_Pin | MOTOR_R_IN2_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(MOTOR_STBY_Port, &GPIO_InitStruct);

  /* PE0 急停输入：上拉 + 下降沿触发（急停按钮常开接 PE0→GND） */
  GPIO_InitStruct.Pin = ESTOP_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_IT_FALLING;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  HAL_GPIO_Init(ESTOP_GPIO_Port, &GPIO_InitStruct);

  /* NVIC：EXTI0 抢占优先级 1（最高，独立于一切软件调度） */
  HAL_NVIC_SetPriority(ESTOP_EXTI_IRQn, 1, 0);
  HAL_NVIC_EnableIRQ(ESTOP_EXTI_IRQn);
}

/**
  * @brief DMA 初始化：USART1_RX = DMA2 Stream2 Channel4（循环模式）
  * 循环模式是 uart_link.c 常驻接收的前提；TC/HT 回调在循环模式下
  * 只走 HAL 的弱空函数（UART_DMAReceiveCplt 在 CIRC 位有效时不做任何
  * 状态变更），不会与 IDLE 中断的处理逻辑冲突。
  */
static void MX_DMA_Init(void)
{
  /* DMA controller clock enable */
  __HAL_RCC_DMA2_CLK_ENABLE();

  hdma_usart1_rx.Instance = DMA2_Stream2;
  hdma_usart1_rx.Init.Channel = DMA_CHANNEL_4;
  hdma_usart1_rx.Init.Direction = DMA_PERIPH_TO_MEMORY;
  hdma_usart1_rx.Init.PeriphInc = DMA_PINC_DISABLE;
  hdma_usart1_rx.Init.MemInc = DMA_MINC_ENABLE;
  hdma_usart1_rx.Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE;
  hdma_usart1_rx.Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
  hdma_usart1_rx.Init.Mode = DMA_CIRCULAR;
  hdma_usart1_rx.Init.Priority = DMA_PRIORITY_LOW;
  hdma_usart1_rx.Init.FIFOMode = DMA_FIFOMODE_DISABLE;
  if (HAL_DMA_Init(&hdma_usart1_rx) != HAL_OK)
  {
    Error_Handler();
  }

  /* USART1_RX 与 DMA 句柄关联（HAL_UART_Receive_DMA 依赖此链接） */
  __HAL_LINKDMA(&huart1, hdmarx, hdma_usart1_rx);

  /* DMA2_Stream2 中断：优先级 6（≥5，与 README 的 NVIC 表一致） */
  HAL_NVIC_SetPriority(DMA2_Stream2_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(DMA2_Stream2_IRQn);
}

/**
  * @brief USART1 初始化：PA9(TX)/PA10(RX)，115200 8N1
  * 视觉链路唯一通道，波特率必须与 OpenMV 侧 UART_BAUD=115200 一致。
  */
static void MX_USART1_UART_Init(void)
{
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }

  /* USART1 中断：优先级 6（README：必须 ≥5 才能安全使用 HAL 中断 API） */
  HAL_NVIC_SetPriority(USART1_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(USART1_IRQn);
}

/**
  * @brief TIM3 初始化：舵机 50 Hz
  *   PSC = 84MHz/1MHz - 1 = 83   → 1 µs/tick
  *   ARR = 1MHz × 20ms - 1 = 19999 → 20 ms（50 Hz）
  *   CCR 直接写微秒数（1500 = 1.5 ms 中位）
  */
static void MX_TIM3_Init(void)
{
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 83;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 19999;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
  if (HAL_TIM_PWM_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim3, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief TIM4 初始化：电机 PWM 20 kHz
  *   PSC = 0；ARR = 84MHz/20kHz - 1 = 4199
  *   占空比分辨率 1/4200 ≈ 0.024%
  */
static void MX_TIM4_Init(void)
{
  TIM_MasterConfigTypeDef sMasterConfig = {0};
  TIM_OC_InitTypeDef sConfigOC = {0};

  htim4.Instance = TIM4;
  htim4.Init.Prescaler = 0;
  htim4.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim4.Init.Period = 4199;
  htim4.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim4.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_ENABLE;
  if (HAL_TIM_PWM_Init(&htim4) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim4, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sConfigOC.OCMode = TIM_OCMODE_PWM1;
  sConfigOC.Pulse = 0;
  sConfigOC.OCPolarity = TIM_OCPOLARITY_HIGH;
  sConfigOC.OCFastMode = TIM_OCFAST_DISABLE;
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_TIM_PWM_ConfigChannel(&htim4, &sConfigOC, TIM_CHANNEL_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief IWDG 初始化：LSI 32kHz / 32 = 1kHz，Reload 499 → 500 ms
  * ⚠️ 一旦启动无法停止。只有 safety_tick_1ms() 喂狗。
  */
static void MX_IWDG_Init(void)
{
  hiwdg.Instance = IWDG;
  hiwdg.Init.Prescaler = IWDG_PRESCALER_32;
  hiwdg.Init.Reload = 499;
  if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}

#ifdef  USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
  (void)file;
  (void)line;
}
#endif /* USE_FULL_ASSERT */
