#ifndef NUSERVICE_H
#define NUSERVICE_H

#include "bcomdef.h"
#include "att.h"

#define NUS_MAX_DATA_LEN 20

bStatus_t NUS_AddService(void);

bStatus_t NUS_SendData(uint8 *data, uint16 len);
bStatus_t NUS_SendHex(uint8 *data, uint8 len);
bStatus_t NUS_SendString(const char *str);

void NUS_HandleConnStatusCB(uint16 connHandle, uint8 changeType);

#endif
