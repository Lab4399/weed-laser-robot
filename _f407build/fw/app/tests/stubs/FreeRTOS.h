/**
 * @file    FreeRTOS.h  （主机侧语法检查用桩文件）
 *
 * 不是 FreeRTOS 官方头文件，也不参与真实编译。
 * 仅用于在没有 RTOS 源码的情况下对固件做 -fsyntax-only 检查。
 *
 * ⚠️ 它不能替代真实编译。真实工程里的 FreeRTOSConfig.h 会定义
 *    configSUPPORT_STATIC_ALLOCATION / configCHECK_FOR_STACK_OVERFLOW 等，
 *    桩文件只保证"语法层面能过"。
 */
#ifndef FREERTOS_STUB_H
#define FREERTOS_STUB_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

typedef uint32_t   TickType_t;
typedef int        BaseType_t;
typedef unsigned   UBaseType_t;
typedef uint32_t   StackType_t;
typedef struct { uint32_t dummy; } StaticTask_t;
typedef void *     TaskHandle_t;

#define pdTRUE   ((BaseType_t)1)
#define pdFALSE  ((BaseType_t)0)
#define pdPASS   pdTRUE
#define pdFAIL   pdFALSE

#define pdMS_TO_TICKS(x)  ((TickType_t)(x))
#define portMAX_DELAY     ((TickType_t)0xFFFFFFFFu)

#define configMINIMAL_STACK_SIZE  128
#define configMAX_PRIORITIES      32

typedef void (*TaskFunction_t)(void *);

TaskHandle_t xTaskCreateStatic(TaskFunction_t fn, const char *name,
                               uint32_t stack_words, void *arg,
                               UBaseType_t prio,
                               StackType_t *stack, StaticTask_t *tcb);

void vTaskDelay(TickType_t ticks);
void vTaskStartScheduler(void);
void vTaskSuspendAll(void);
void xTaskResumeAll(void);

#define taskDISABLE_INTERRUPTS()  ((void)0)
#define taskENABLE_INTERRUPTS()   ((void)0)
#define taskENTER_CRITICAL()      ((void)0)
#define taskEXIT_CRITICAL()       ((void)0)

uint32_t uxTaskGetStackHighWaterMark(TaskHandle_t t);
TickType_t xTaskGetTickCount(void);

#endif /* FREERTOS_STUB_H */
