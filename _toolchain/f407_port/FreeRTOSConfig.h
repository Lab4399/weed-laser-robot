/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : FreeRTOSConfig.h
  * @brief          : FreeRTOS 配置（按交付包 README 的关键项 + 静态分配）
  *
  * 关键决策：
  *   · configSUPPORT_DYNAMIC_ALLOCATION = 0 —— 纯静态分配。
  *     任务数/栈大小在编译期完全已知，堆碎片在 7×24 场景下
  *     是不可复现故障的主要来源，没有理由用堆。
  *   · configUSE_TIME_SLICING = 0 —— 确定性优先。
  *   · SysTick 由 stm32f4xx_it.c 同时驱动 HAL tick 与 RTOS tick。
  *   · configCHECK_FOR_STACK_OVERFLOW = 2 —— 栈溢出直接停机。
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef FREERTOS_CONFIG_H
#define FREERTOS_CONFIG_H

#include <stdint.h>
#include "stm32f4xx.h"          /* 提供 __NVIC_PRIO_BITS（CMSIS core） */
extern uint32_t SystemCoreClock;

#define configUSE_PREEMPTION                    1
#define configUSE_TIME_SLICING                  0
#define configUSE_TICKLESS_IDLE                 0
#define configCPU_CLOCK_HZ                      ( SystemCoreClock )
#define configTICK_RATE_HZ                      ((TickType_t)1000)
#define configMAX_PRIORITIES                    (16)
#define configMINIMAL_STACK_SIZE                ((uint16_t)128)
#define configTOTAL_HEAP_SIZE                   ((size_t)0)
#define configMAX_TASK_NAME_LEN                 (16)
#define configUSE_16_BIT_TICKS                  0
#define configIDLE_SHOULD_YIELD                 1
#define configUSE_MUTEXES                       1
#define configUSE_RECURSIVE_MUTEXES             0
#define configUSE_COUNTING_SEMAPHORES           1
#define configQUEUE_REGISTRY_SIZE               8
#define configUSE_QUEUE_SETS                    0
#define configUSE_TASK_NOTIFICATIONS            1
#define configUSE_TASK_NOTIFICATION_ARRAY_ENTRIES 1
#define configENABLE_BACKWARD_COMPATIBILITY     0
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 0
#define configSTACK_DEPTH_TYPE                  uint32_t
#define configMESSAGE_BUFFER_LENGTH_TYPE        size_t
#define configSUPPORT_STATIC_ALLOCATION         1
#define configSUPPORT_DYNAMIC_ALLOCATION        0
#define configUSE_POSIX_ERRNO                   0
#define configUSE_NEWLIB_REENTRANT              0

/* 运行期统计与追踪：本工程诊断走 ITM/SWO，不需要这些 */
#define configGENERATE_RUN_TIME_STATS            0
#define configUSE_TRACE_FACILITY                 0
#define configUSE_STATS_FORMATTING_FUNCTIONS     0

/* 软件定时器：不用（任务周期全部由 vTaskDelay 驱动） */
#define configUSE_TIMERS                         0
#define configTIMER_TASK_PRIORITY                0
#define configTIMER_QUEUE_LENGTH                 0
#define configTIMER_TASK_STACK_DEPTH             0

/* Hooks —— app_main.c 提供实现 */
#define configUSE_IDLE_HOOK                      1
#define configUSE_TICK_HOOK                      0
#define configUSE_MALLOC_FAILED_HOOK             1
#define configCHECK_FOR_STACK_OVERFLOW           2

/* Co-routine 未使用 */
#define configUSE_CO_ROUTINES                    0
#define configMAX_CO_ROUTINE_PRIORITIES          2

/* Cortex-M4F 移植相关 */
#define configPRIO_BITS                          __NVIC_PRIO_BITS
#define configLIBRARY_LOWEST_INTERRUPT_PRIORITY         15
#define configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY    5
#define configKERNEL_INTERRUPT_PRIORITY          (configLIBRARY_LOWEST_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))
#define configMAX_SYSCALL_INTERRUPT_PRIORITY     (configLIBRARY_MAX_SYSCALL_INTERRUPT_PRIORITY << (8 - configPRIO_BITS))
#define configUSE_PORT_OPTIMISED_TASK_SELECTION  1

/* 断言：失败即关中断停机，便于调试器抓到现场 */
#define configASSERT( x ) if ((x) == 0) { taskDISABLE_INTERRUPTS(); for( ;; ); }

/* 可选 API 函数（SysTick_Handler 用到 xTaskGetSchedulerState） */
#define INCLUDE_vTaskPrioritySet            0
#define INCLUDE_uxTaskPriorityGet           0
#define INCLUDE_vTaskDelete                 0
#define INCLUDE_vTaskSuspend                1
#define INCLUDE_vTaskDelayUntil             1
#define INCLUDE_vTaskDelay                  1
#define INCLUDE_xTaskGetSchedulerState      1
#define INCLUDE_xTaskGetCurrentTaskHandle   0
#define INCLUDE_uxTaskGetStackHighWaterMark 0
#define INCLUDE_xTaskGetIdleTaskHandle      0
#define INCLUDE_eTaskGetState               0
#define INCLUDE_xTimerPendFunctionCall      0
#define INCLUDE_xTaskAbortDelay             0
#define INCLUDE_xTaskGetHandle              0

#endif /* FREERTOS_CONFIG_H */
