#ifndef MYUART_H
#define MYUART_H

#include "config.h"
#include <stdint.h>
#include "gpio.h"
#include "log.h"

#if (DEBUG_INFO == 0)

#define LCD_PACKET_LEN 14

typedef struct
{
    uint8_t data[LCD_PACKET_LEN];
} lcd_packet_t;

static lcd_packet_t lcd_packet;
static uint8_t lcd_packet_pos = 0;


void uart_send_dec(uint8_t value);
void debug_print_lcd_packet(const lcd_packet_t *packet);
void process_uart_byte(uint8_t b);
void my_uart_send_hex8(uint8_t value);
void my_uart_send_string(const char *str);
void my_uart_rx_handler(uart_Evt_t *evt);
void my_uart_init(void);

#else

static inline void uart_send_dec(uint8_t value) { (void)value; }
static inline void debug_print_lcd_packet(const lcd_packet_t *packet) { (void)packet; }
static inline void process_uart_byte(uint8_t b) { (void)b; }
static inline void my_uart_send_hex8(uint8_t value) { (void)value; }
static inline void my_uart_send_string(const char *str) { (void)str; }
static inline void my_uart_rx_handler(uart_Evt_t *evt) { (void)evt; }
static inline void my_uart_init(void) { }

#endif

#endif

