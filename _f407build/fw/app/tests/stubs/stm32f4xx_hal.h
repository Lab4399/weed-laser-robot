/**
 * @file    stm32f4xx_hal.h  （主机侧语法检查用桩文件）
 *
 * 这不是 ST 官方头文件，也不参与任何真实编译。
 * 它的唯一用途：在没有硬件、没有 CubeMX 工程的情况下，
 * 用 `gcc -fsyntax-only` 检查固件源码的语法与类型一致性，
 * 把"拼写错误、参数个数不对、类型不匹配"这类问题挡在烧录之前。
 *
 * ⚠️ 它不能替代在真实 HAL 上的编译。契约一致性（比如某个 HAL 函数
 *    在特定版本的参数顺序）只有用官方头文件才能验证。
 */
#ifndef STM32F4XX_HAL_STUB_H
#define STM32F4XX_HAL_STUB_H

#include <stdint.h>
#include <stddef.h>

typedef enum { HAL_OK = 0, HAL_ERROR, HAL_BUSY, HAL_TIMEOUT } HAL_StatusTypeDef;
typedef enum { RESET = 0, SET } FlagStatus;
typedef enum { DISABLE = 0, ENABLE } FunctionalState;

/* --- GPIO --- */
typedef struct { volatile uint32_t MODER, OTYPER, OSPEEDR, PUPDR, IDR, ODR, BSRR, LCKR, AFR[2]; } GPIO_TypeDef;

#define GPIOA ((GPIO_TypeDef *)0x40020000u)
#define GPIOB ((GPIO_TypeDef *)0x40020400u)
#define GPIOC ((GPIO_TypeDef *)0x40020800u)
#define GPIOD ((GPIO_TypeDef *)0x40020C00u)
#define GPIOE ((GPIO_TypeDef *)0x40021000u)

#define GPIO_PIN_0   ((uint16_t)0x0001)
#define GPIO_PIN_11  ((uint16_t)0x0800)
#define GPIO_PIN_12  ((uint16_t)0x1000)
#define GPIO_PIN_13  ((uint16_t)0x2000)
#define GPIO_PIN_14  ((uint16_t)0x4000)
#define GPIO_PIN_15  ((uint16_t)0x8000)
#define GPIO_PIN_SET   (1u)
#define GPIO_PIN_RESET (0u)

void HAL_GPIO_WritePin(GPIO_TypeDef *port, uint16_t pin, uint32_t state);
void HAL_GPIO_TogglePin(GPIO_TypeDef *port, uint16_t pin);

/* --- UART --- */
typedef struct { uint32_t SR, DR, BRR, CR1, CR2, CR3, GTPR; } USART_TypeDef;

typedef struct {
    USART_TypeDef *Instance;
    uint32_t Init;
} UART_HandleTypeDef;

#define USART1 ((USART_TypeDef *)0x40011000u)
#define USART_SR_ORE  (1u << 3)
#define USART_SR_FE   (1u << 1)
#define USART_SR_NE   (1u << 2)
#define USART_SR_PE   (1u << 0)
#define UART_FLAG_IDLE (1u << 4)
#define UART_IT_IDLE   (1u << 8)
#define UART_IT_ERR    (1u << 9)

#define __HAL_UART_GET_FLAG(h, f)      (((h)->Instance->SR & (f)) ? SET : RESET)
#define __HAL_UART_CLEAR_IDLEFLAG(h)   do { volatile uint32_t _t = (h)->Instance->SR; _t = (h)->Instance->DR; (void)_t; } while (0)
#define __HAL_UART_ENABLE_IT(h, it)    ((void)(h), (void)(it))

HAL_StatusTypeDef HAL_UART_Receive_DMA(UART_HandleTypeDef *h, uint8_t *d, uint16_t n);
HAL_StatusTypeDef HAL_UART_Transmit(UART_HandleTypeDef *h, uint8_t *d, uint16_t n, uint32_t t);
void HAL_UART_IRQHandler(UART_HandleTypeDef *h);

/* --- DMA --- */
typedef struct { uint32_t NDTR, PAR, M0AR; } DMA_Stream_TypeDef;
typedef struct { DMA_Stream_TypeDef *Instance; } DMA_HandleTypeDef;

#define __HAL_DMA_GET_COUNTER(h)  ((h)->Instance->NDTR)
HAL_StatusTypeDef HAL_DMA_Start_IT(DMA_HandleTypeDef *h, uint32_t src, uint32_t dst, uint32_t n);
void HAL_DMA_IRQHandler(DMA_HandleTypeDef *h);

/* --- TIM --- */
typedef struct { uint32_t CR1, CR2, SMCR, DIER, SR, EGR, CCMR1, CCMR2, CCER, CNT, PSC, ARR, RCR, CCR1, CCR2, CCR3, CCR4; } TIM_TypeDef;
typedef struct { TIM_TypeDef *Instance; } TIM_HandleTypeDef;

#define TIM3 ((TIM_TypeDef *)0x40000400u)
#define TIM4 ((TIM_TypeDef *)0x40000800u)

#define TIM_CHANNEL_1 0x0000u
#define TIM_CHANNEL_2 0x0004u
#define TIM_CHANNEL_3 0x0008u
#define TIM_CHANNEL_4 0x000Cu

#define __HAL_TIM_SET_COMPARE(h, ch, v) ((void)(h), (void)(ch), (void)(v))

HAL_StatusTypeDef HAL_TIM_PWM_Start(TIM_HandleTypeDef *h, uint32_t ch);
HAL_StatusTypeDef HAL_TIM_PWM_Stop(TIM_HandleTypeDef *h, uint32_t ch);

/* --- IWDG --- */
typedef struct { uint32_t Prescaler, Reload; } IWDG_TypeDef;
typedef struct { IWDG_TypeDef *Instance; } IWDG_HandleTypeDef;
HAL_StatusTypeDef HAL_IWDG_Refresh(IWDG_HandleTypeDef *h);

/* --- RCC / 复位标志 --- */
typedef struct { uint32_t CR, PLLCFGR, CFGR, CIR, AHB1RSTR, AHB2RSTR, AHB3RSTR, RES1, APB1RSTR, APB2RSTR, RES2[2], AHB1ENR, AHB2ENR, AHB3ENR, RES3, APB1ENR, APB2ENR, RES4[2], AHB1LPENR, AHB2LPENR, AHB3LPENR, RES5, APB1LPENR, APB2LPENR, RES6[2], BDCR, CSR, RES7[2], SSCGR, PLLI2SCFGR; } RCC_TypeDef;

#define RCC ((RCC_TypeDef *)0x40023800u)

#define RCC_CSR_LSION      (1u << 0)
#define RCC_CSR_IWDGRSTF   (1u << 29)
#define RCC_CSR_WWDGRSTF   (1u << 28)
#define RCC_CSR_SFTRSTF    (1u << 27)
#define RCC_CSR_PORRSTF    (1u << 26)
#define RCC_CSR_PINRSTF    (1u << 25)
#define RCC_CSR_BORRSTF    (1u << 24)
#define RCC_CSR_RMVF       (1u << 24)

#define __HAL_RCC_CLEAR_RESET_FLAGS()  (RCC->CSR |= RCC_CSR_RMVF)

/* --- NVIC --- */
typedef enum {
    NonMaskableInt_IRQn = -14,
    HardFault_IRQn      = -13,
    EXTI0_IRQn          = 6,
    DMA2_Stream2_IRQn   = 56,
    USART1_IRQn         = 37
} IRQn_Type;

#define NVIC_PRIORITYGROUP_4  3u
void HAL_NVIC_SetPriorityGrouping(uint32_t g);
void HAL_NVIC_SetPriority(IRQn_Type irq, uint32_t pre, uint32_t sub);
void HAL_NVIC_EnableIRQ(IRQn_Type irq);
void HAL_NVIC_DisableIRQ(IRQn_Type irq);
#define __HAL_GPIO_EXTI_CLEAR_IT(p) ((void)(p))

/* --- FLASH --- */
typedef struct {
    uint32_t TypeErase;
    uint32_t Banks;
    uint32_t Sector;
    uint32_t NbSectors;
    uint32_t VoltageRange;
} FLASH_EraseInitTypeDef;

#define FLASH_TYPEERASE_SECTORS   0x00000000u
#define FLASH_VOLTAGE_RANGE_3     0x00000002u
#define FLASH_SECTOR_10           10u
#define FLASH_SECTOR_11           11u
#define FLASH_TYPEPROGRAM_WORD    0x00000002u

HAL_StatusTypeDef HAL_FLASH_Unlock(void);
HAL_StatusTypeDef HAL_FLASH_Lock(void);
HAL_StatusTypeDef HAL_FLASHEx_Erase(FLASH_EraseInitTypeDef *e, uint32_t *err);
HAL_StatusTypeDef HAL_FLASH_Program(uint32_t type, uint32_t addr, uint32_t data);

/* --- 系统 --- */
HAL_StatusTypeDef HAL_Init(void);
void HAL_Delay(uint32_t ms);
uint32_t HAL_GetTick(void);
void NVIC_SystemReset(void);

#endif /* STM32F4XX_HAL_STUB_H */
