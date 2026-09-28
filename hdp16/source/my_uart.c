#include "my_uart.h"

#if (DEBUG_INFO == 0)

void uart_send_dec(uint8_t value)
{
    if (value >= 100)
        hal_uart_send_byte(UART1, '0' + value / 100);

    if (value >= 10)
        hal_uart_send_byte(UART1, '0' + (value / 10) % 10);

    hal_uart_send_byte(UART1, '0' + value % 10);
}

void debug_print_lcd_packet(const lcd_packet_t *packet)
{
    for (uint8_t i = 0; i < LCD_PACKET_LEN; i++)
    {
        uart_send_dec(packet->data[i]);
        hal_uart_send_byte(UART1, ' ');
    }

    hal_uart_send_byte(UART1, '\r');
    hal_uart_send_byte(UART1, '\n');
}

void process_uart_byte(uint8_t b)
{
    uint8_t seq = b >> 4;

    // 1X always starts a new packet
    if (seq == 1)
    {
        lcd_packet.data[0] = b;
        lcd_packet_pos = 1;
        return;
    }

    // We haven't seen 1X yet
    if (lcd_packet_pos == 0)
        return;

    // Expect 2X, 3X, 4X ... EX
    if (seq != (lcd_packet_pos + 1))
    {
        // Corrupt/out-of-sequence packet
        lcd_packet_pos = 0;
        return;
    }

    lcd_packet.data[lcd_packet_pos] = b;
    lcd_packet_pos++;

    // Got all 14 bytes
    if (lcd_packet_pos == LCD_PACKET_LEN)
    {
        debug_print_lcd_packet(&lcd_packet);

        lcd_packet_pos = 0;
    }
}

void my_uart_send_hex8(uint8_t value)
{
    const char hex[] = "0123456789ABCDEF";

    hal_uart_send_byte(UART1, hex[(value >> 4) & 0x0F]);
    hal_uart_send_byte(UART1, hex[value & 0x0F]);
}

void my_uart_send_string(const char *str)
{
    while (*str)
        hal_uart_send_byte(UART1, *str++);
}

void my_uart_rx_handler(uart_Evt_t *evt)
{
    if (evt->type != UART_EVT_TYPE_RX_DATA &&
        evt->type != UART_EVT_TYPE_RX_DATA_TO)
    {
        return;
    }

    for (uint8_t i = 0; i < evt->len; i++)
    {
        process_uart_byte(evt->data[i]);
    }
}

void my_uart_init(void)
{
    uart_Cfg_t cfg = {
        .tx_pin = P9,
        .rx_pin = P10,
        .rts_pin = GPIO_DUMMY,
        .cts_pin = GPIO_DUMMY,
        .baudrate = 115200,
        .use_fifo = TRUE,
        .hw_fwctrl = FALSE,
        .use_tx_buf = FALSE,
        .parity = FALSE,
        .evt_handler = my_uart_rx_handler,
    };

    hal_uart_init(cfg, UART1);
}

#endif

