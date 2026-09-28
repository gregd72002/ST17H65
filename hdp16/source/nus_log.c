#include <stdint.h>
#include <stdarg.h>
#include "bcomdef.h"
#include "thb2_main.h"
#include "nuservice.h"

#define NUS_LOG_BUFFER_SIZE  256
#define NUS_LOG_QUEUE_SIZE   4

typedef struct
{
    uint16_t len;
    char data[NUS_LOG_BUFFER_SIZE];
} nus_log_entry_t;

static nus_log_entry_t nus_log_queue[NUS_LOG_QUEUE_SIZE];

static uint8_t nus_log_write = 0;
static uint8_t nus_log_read = 0;
static uint8_t nus_log_count = 0;


/* ---------------------------------------------------------
 * Formatting helpers
 * --------------------------------------------------------- */

static void nus_put_char(nus_log_entry_t *entry, char c)
{
    if (entry->len < NUS_LOG_BUFFER_SIZE - 1)
        entry->data[entry->len++] = c;
}


static void nus_put_string(nus_log_entry_t *entry, const char *str)
{
    if (str == NULL)
        return;

    while (*str)
        nus_put_char(entry, *str++);
}


static void nus_put_uint(nus_log_entry_t *entry,
                         unsigned int value,
                         unsigned int base,
                         int width,
                         char pad,
                         int uppercase)
{
    char tmp[16];
    unsigned int len = 0;
    unsigned int digit;
    int i;

    do
    {
        digit = value % base;

        if (digit < 10)
            tmp[len++] = '0' + digit;
        else
            tmp[len++] = (uppercase ? 'A' : 'a') + digit - 10;

        value /= base;

    } while (value != 0 && len < sizeof(tmp));

    while (len < (unsigned int)width)
        tmp[len++] = pad;

    for (i = (int)len - 1; i >= 0; i--)
        nus_put_char(entry, tmp[i]);
}


static void nus_put_int(nus_log_entry_t *entry,
                        int value,
                        int width,
                        char pad)
{
    unsigned int magnitude;

    if (value < 0)
    {
        nus_put_char(entry, '-');

        /*
         * Avoid overflow for INT_MIN.
         */
        magnitude = (unsigned int)(-(value + 1)) + 1;
    }
    else
    {
        magnitude = (unsigned int)value;
    }

    nus_put_uint(entry, magnitude, 10, width, pad, 0);
}


/* ---------------------------------------------------------
 * Logger
 * --------------------------------------------------------- */

void nus_log_printf(const char *format, ...)
{
    nus_log_entry_t *entry;
    va_list args;
    char c;
    char pad;
    int width;

    /*
     * Drop the message if the queue is full.
     * Never block the application waiting for NUS.
     */
    if (nus_log_count >= NUS_LOG_QUEUE_SIZE)
        return;

    entry = &nus_log_queue[nus_log_write];

    entry->len = 0;

    va_start(args, format);

    while ((c = *format++) != '\0')
    {
        if (c != '%')
        {
            nus_put_char(entry, c);
            continue;
        }

        c = *format++;

        /*
         * %%
         */
        if (c == '%')
        {
            nus_put_char(entry, '%');
            continue;
        }

        /*
         * Optional zero padding.
         */
        pad = ' ';
        width = 0;

        if (c == '0')
        {
            pad = '0';
            c = *format++;
        }

        /*
         * Field width.
         */
        while (c >= '0' && c <= '9')
        {
            width = width * 10 + (c - '0');
            c = *format++;
        }

        switch (c)
        {
            case 'd':
            case 'i':
                nus_put_int(entry,
                            va_arg(args, int),
                            width,
                            pad);
                break;

            case 'u':
                nus_put_uint(entry,
                             va_arg(args, unsigned int),
                             10,
                             width,
                             pad,
                             0);
                break;

            case 'x':
                nus_put_uint(entry,
                             va_arg(args, unsigned int),
                             16,
                             width,
                             pad,
                             0);
                break;

            case 'X':
                nus_put_uint(entry,
                             va_arg(args, unsigned int),
                             16,
                             width,
                             pad,
                             1);
                break;

            case 'c':
                nus_put_char(entry, (char)va_arg(args, int));
                break;

            case 's':
                nus_put_string(entry, va_arg(args, const char *));
                break;

            default:
                /*
                 * Preserve unknown format rather than
                 * silently discarding it.
                 */
                nus_put_char(entry, '%');
                nus_put_char(entry, c);
                break;
        }
    }

    va_end(args);

    /*
     * Terminate the string as well as storing its length.
     */
    entry->data[entry->len] = '\0';

    /*
     * Message is now complete and safely queued.
     */
    nus_log_write++;

    if (nus_log_write >= NUS_LOG_QUEUE_SIZE)
        nus_log_write = 0;

    nus_log_count++;

    /*
     * Tell the application task to transmit it.
     */
    osal_set_event(simpleBLEPeripheral_TaskID, MY_NUS_LOG_EVT);
}

void nus_log_process(void)
{
    nus_log_entry_t *entry;

    while (nus_log_count != 0)
    {
        entry = &nus_log_queue[nus_log_read];

        NUS_SendData((uint8 *)entry->data, entry->len);

        nus_log_read++;

        if (nus_log_read >= NUS_LOG_QUEUE_SIZE)
            nus_log_read = 0;

        nus_log_count--;
    }
}
