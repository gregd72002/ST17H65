/*
 * nuservice.c
 *
 * Nordic UART Service (NUS)
 *
 * NUS Service:
 *   6E400001-B5A3-F393-E0A9-E50E24DCCA9E
 *
 * RX Characteristic:
 *   6E400002-B5A3-F393-E0A9-E50E24DCCA9E
 *
 * TX Characteristic:
 *   6E400003-B5A3-F393-E0A9-E50E24DCCA9E
 *
 * RX: Write / Write Without Response
 * TX: Notify
 */

#include "types.h"
#include "bcomdef.h"
#include "OSAL.h"
#include "linkdb.h"
#include "att.h"
#include "gatt.h"
#include "gatt_uuid.h"
#include "gatt_profile_uuid.h"
#include "gattservapp.h"

#include "nuservice.h"


/*********************************************************************
 * CONSTANTS
 */

#define NUS_MAX_DATA_LEN        20

#define NUS_SERVICE_UUID_LEN    16
#define NUS_RX_UUID_LEN         16
#define NUS_TX_UUID_LEN         16

#define NUS_TX_VALUE_IDX        4


/*********************************************************************
 * UUIDs
 *
 * UUIDs are stored in Bluetooth little-endian byte order.
 */

/* 6E400001-B5A3-F393-E0A9-E50E24DCCA9E */
static CONST uint8 nusServiceUUID[NUS_SERVICE_UUID_LEN] =
{
    0x9E, 0xCA, 0xDC, 0x24,
    0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5,
    0x01, 0x00, 0x40, 0x6E
};

/* 6E400002-B5A3-F393-E0A9-E50E24DCCA9E */
static CONST uint8 nusRxUUID[NUS_RX_UUID_LEN] =
{
    0x9E, 0xCA, 0xDC, 0x24,
    0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5,
    0x02, 0x00, 0x40, 0x6E
};

/* 6E400003-B5A3-F393-E0A9-E50E24DCCA9E */
static CONST uint8 nusTxUUID[NUS_TX_UUID_LEN] =
{
    0x9E, 0xCA, 0xDC, 0x24,
    0x0E, 0xE5, 0xA9, 0xE0,
    0x93, 0xF3, 0xA3, 0xB5,
    0x03, 0x00, 0x40, 0x6E
};


/*********************************************************************
 * PROFILE ATTRIBUTES
 */

static CONST gattAttrType_t nusService =
{
    NUS_SERVICE_UUID_LEN,
    (uint8 *)nusServiceUUID
};


/*
 * RX characteristic:
 *
 * Write | Write Without Response
 */
static uint8 nusRxProps =
    GATT_PROP_WRITE |
    GATT_PROP_WRITE_NO_RSP;


/*
 * TX characteristic:
 *
 * Notify
 */
static uint8 nusTxProps =
    GATT_PROP_NOTIFY;


/*
 * TX notification configuration.
 */
static gattCharCfg_t nusTxClientCharCfg[GATT_MAX_NUM_CONN];


/*
 * TX data buffer.
 */
static uint8 nusTxValue[NUS_MAX_DATA_LEN];


/*
 * Actual number of bytes currently in nusTxValue.
 */
static uint8 nusTxLen;


/*********************************************************************
 * ATTRIBUTE TABLE
 */

static gattAttribute_t nusAttrTbl[] =
{
    /*
     * 0 - NUS Service
     */
    {
        { ATT_BT_UUID_SIZE, primaryServiceUUID },
        GATT_PERMIT_READ,
        0,
        (uint8 *)&nusService
    },

    /*
     * 1 - RX Characteristic Declaration
     */
    {
        { ATT_BT_UUID_SIZE, characterUUID },
        GATT_PERMIT_READ,
        0,
        &nusRxProps
    },

    /*
     * 2 - RX Characteristic Value
     */
    {
        { NUS_RX_UUID_LEN, nusRxUUID },
        GATT_PERMIT_WRITE,
        0,
        NULL
    },

    /*
     * 3 - TX Characteristic Declaration
     */
    {
        { ATT_BT_UUID_SIZE, characterUUID },
        GATT_PERMIT_READ,
        0,
        &nusTxProps
    },

    /*
     * 4 - TX Characteristic Value
     */
    {
        { NUS_TX_UUID_LEN, nusTxUUID },
        GATT_PERMIT_READ,
        0,
        nusTxValue
    },

    /*
     * 5 - TX Client Characteristic Configuration
     */
    {
        { ATT_BT_UUID_SIZE, clientCharCfgUUID },
        GATT_PERMIT_READ | GATT_PERMIT_WRITE,
        0,
        (uint8 *)&nusTxClientCharCfg
    }
};


/*********************************************************************
 * LOCAL FUNCTIONS
 */

static uint8 nusReadAttrCB(
    uint16 connHandle,
    gattAttribute_t *pAttr,
    uint8 *pValue,
    uint16 *pLen,
    uint16 offset,
    uint8 maxLen);

static bStatus_t nusWriteAttrCB(
    uint16 connHandle,
    gattAttribute_t *pAttr,
    uint8 *pValue,
    uint16 len,
    uint16 offset);

static void nusNotifyCB(linkDBItem_t *pLinkItem);


/*********************************************************************
 * SERVICE CALLBACKS
 */

CONST gattServiceCBs_t nusCBs =
{
    nusReadAttrCB,
    nusWriteAttrCB,
    NULL
};


/*********************************************************************
 * PUBLIC FUNCTIONS
 */

/*
 * Register NUS with the GATT server.
 */
bStatus_t NUS_AddService(void)
{
    bStatus_t status;

    nusTxLen = 0;

    GATTServApp_InitCharCfg(
        INVALID_CONNHANDLE,
        nusTxClientCharCfg);

    status = GATTServApp_RegisterService(
        nusAttrTbl,
        GATT_NUM_ATTRS(nusAttrTbl),
        &nusCBs);

    return status;
}


/*
 * Send data through the NUS TX characteristic.
 *
 * Maximum payload is 20 bytes.
 */
bStatus_t NUS_SendData(uint8 *data, uint16 len)
{
    uint16 offset = 0;
    uint8 chunk_len;

    if (data == NULL || len == 0)
        return FAILURE;

    while (offset < len)
    {
        chunk_len = len - offset;

        if (chunk_len > NUS_MAX_DATA_LEN)
            chunk_len = NUS_MAX_DATA_LEN;

        osal_memcpy(nusTxValue, &data[offset], chunk_len);
        nusTxLen = chunk_len;

        linkDB_PerformFunc(nusNotifyCB);

        offset += chunk_len;
    }

    return SUCCESS;
}


/*
 * Send a string through NUS TX.
 *
 * Maximum length is 20 bytes.
 *
 * If the string is longer than 20 bytes, it is truncated.
 */
bStatus_t NUS_SendString(const char *str)
{
    uint8 len = 0;

    if (str == NULL)
        return FAILURE;

    while (str[len] != '\0' && len < NUS_MAX_DATA_LEN)
        len++;

    if (len == 0)
        return SUCCESS;

    return NUS_SendData((uint8 *)str, len);
}

bStatus_t NUS_SendHex(uint8 *data, uint8 len)
{
    static const char hex[] = "0123456789ABCDEF";
    char str[21];
    uint8 i;
    uint8 truncated = 0;

    if (len > 10)
    {
        len = 10;
        truncated = 1;
    }

    for (i = 0; i < len; i++)
    {
        str[i * 2]     = hex[(data[i] >> 4) & 0x0F];
        str[i * 2 + 1] = hex[data[i] & 0x0F];
    }

    if (truncated)
    {
        str[18] = '.';
        str[19] = '.';
    }

    str[len * 2] = '\0';

    return NUS_SendString(str);
}

/*********************************************************************
 * ATTRIBUTE CALLBACKS
 */

/*
 * Read attribute.
 */
static uint8 nusReadAttrCB(
    uint16 connHandle,
    gattAttribute_t *pAttr,
    uint8 *pValue,
    uint16 *pLen,
    uint16 offset,
    uint8 maxLen)
{

    (void)connHandle;
    /*
     * TX characteristic value.
     */
    if (pAttr == &nusAttrTbl[NUS_TX_VALUE_IDX])
    {
        if (offset > 0)
            return ATT_ERR_ATTR_NOT_LONG;

        if (nusTxLen > maxLen)
            *pLen = maxLen;
        else
            *pLen = nusTxLen;

        osal_memcpy(pValue, nusTxValue, *pLen);

        return SUCCESS;
    }

    /*
     * Let the GATT server handle other attributes.
     */
    return ATT_ERR_ATTR_NOT_FOUND;
}


/*
 * Handle writes.
 *
 * TX CCCD:
 *   Enables/disables notifications.
 *
 * RX:
 *   Currently accepted but ignored.
 */
static bStatus_t nusWriteAttrCB(
    uint16 connHandle,
    gattAttribute_t *pAttr,
    uint8 *pValue,
    uint16 len,
    uint16 offset)
{
    /*
     * TX Client Characteristic Configuration.
     */
    if (pAttr == &nusAttrTbl[5])
    {
        return GATTServApp_ProcessCCCWriteReq(
            connHandle,
            pAttr,
            pValue,
            len,
            offset,
            GATT_CLIENT_CFG_NOTIFY);
    }

    /*
     * NUS RX characteristic.
     *
     * We don't do anything with received NUS data yet.
     */
    if (pAttr == &nusAttrTbl[2])
    {
        return SUCCESS;
    }

    return ATT_ERR_ATTR_NOT_FOUND;
}


/*********************************************************************
 * NOTIFICATION
 */

static void nusNotifyCB(linkDBItem_t *pLinkItem)
{
    attHandleValueNoti_t noti;

    if (nusTxLen == 0)
        return;

    if (pLinkItem->stateFlags & LINK_CONNECTED)
    {
        /*
         * Only notify if the client has enabled notifications.
         */
        if (GATTServApp_ReadCharCfg(
                pLinkItem->connectionHandle,
                nusTxClientCharCfg) & GATT_CLIENT_CFG_NOTIFY)
        {
            noti.handle = nusAttrTbl[NUS_TX_VALUE_IDX].handle;

            /*
             * Send only the actual data length.
             */
            noti.len = nusTxLen;

            osal_memcpy(
                noti.value,
                nusTxValue,
                nusTxLen);

            GATT_Notification(
                pLinkItem->connectionHandle,
                &noti,
                FALSE);
        }
    }
}


/*********************************************************************
 * CONNECTION STATUS
 */

void NUS_HandleConnStatusCB(uint16 connHandle, uint8 changeType)
{
    if (connHandle != LOOPBACK_CONNHANDLE)
    {
        if ((changeType == LINKDB_STATUS_UPDATE_REMOVED) ||
            ((changeType == LINKDB_STATUS_UPDATE_STATEFLAGS) &&
             (!linkDB_Up(connHandle))))
        {
            GATTServApp_InitCharCfg(
                connHandle,
                nusTxClientCharCfg);
        }
    }
}
