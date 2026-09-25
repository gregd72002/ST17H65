#include "types.h"
#include "clock.h"
#include "gpio.h"
#include "uart.h"
#include "pwrmgr.h"

#define UART_TX_BUF_SIZE 256

static uint8_t uart_tx_buf[UART_TX_BUF_SIZE];

int main(void)
{
    /*
     * 32 MHz system clock
     */
    g_system_clk = SYS_CLK_DBL_32M;


    /*
     * Initialise system clock
     */
    clk_init(g_system_clk);

    /*
     * Initialise GPIO
     */
    hal_gpio_init();

    /*
     * UART1:
     *   P9  = TX
     *   P10 = RX
     *
     * Requested baud = 115200
     */
    uart_Cfg_t cfg = {
        .tx_pin = P9,
        .rx_pin = P10,
        .rts_pin = GPIO_DUMMY,
        .cts_pin = GPIO_DUMMY,
        .baudrate = 115200,
        .use_fifo = TRUE,
        .hw_fwctrl = FALSE,
        .use_tx_buf = TRUE,
        .parity = FALSE,
        .evt_handler = NULL,
    };

    hal_uart_deinit(UART1);
    hal_uart_init(cfg, UART1);

    hal_uart_set_tx_buf(
        UART1,
        uart_tx_buf,
        UART_TX_BUF_SIZE
    );


    char msg[] = "Hello from ST17H65!\r\n";
    char msg1[] = "Ping...\r\n";

    hal_uart_send_buff(UART1, (uint8_t *)msg, sizeof(msg) - 1);

    while (1)
    {
	hal_uart_send_buff(UART1, (uint8_t *)msg1, sizeof(msg1) - 1);
        WaitMs(3000);
    }

    return 0;
}
