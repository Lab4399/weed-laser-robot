#ifndef FREERTOS_SEMPHR_STUB_H
#define FREERTOS_SEMPHR_STUB_H
#include "FreeRTOS.h"

typedef struct { uint32_t dummy; } StaticSemaphore_t;
typedef struct { uint32_t dummy; } StaticQueue_t;
typedef void * SemaphoreHandle_t;
typedef void * QueueHandle_t;

SemaphoreHandle_t xSemaphoreCreateMutexStatic(StaticSemaphore_t *buf);
BaseType_t xSemaphoreTake(SemaphoreHandle_t s, TickType_t t);
BaseType_t xSemaphoreGive(SemaphoreHandle_t s);

#endif
