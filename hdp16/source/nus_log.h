#ifndef NUS_LOG_H
#define NUS_LOG_H


#include "nuservice.h"
#include "config.h"

#if (DEV_SERVICES & SERVICE_NUS)

void nus_log_printf(const char *format, ...);
void nus_log_process(void);

#define NUS_LOG(...) nus_log_printf(__VA_ARGS__)

#else

#define NUS_LOG(...) LOG(__VA_ARGS__)

#endif

#endif

