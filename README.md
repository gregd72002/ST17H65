# ST17H65
This work is based on pvvx THB2 sources, configured for HDP16 device 
```
https://github.com/pvvx/THB2
```

### Where to start
1. Compile -> go to hdp16 and run make (install toolchains for arm)
2. Flash -> see flash folder

### What is it
This is a DIY project exploring different functionality of HDP16 tracker. The tracker features a very capable low power chip.

My initial idea was to repurpose it as UART<->BLE bridge. This is now working well.
Button presses are recognised too, so does the buzzer work well.

What also works is OTA (over air updates). So any test, new version, functionality can be flashed onto the chip through a browser. Although it requires initially to be flashed by wire. This is to get the OTA BOOT software in. 

What is not working yet - accelerometer. It should be possible to set the device to sleep and wake it up on movement triggering an event.

HDP16 key features:
- BLE
- battery monitor
- accelerometer (SC7A20)
- buzzer
- UART to BLE bridge (wip)
- Nordic UART service (wip)
- OTA with web management


ST17H65 is highly customisable chip featuring:
- GPIO: Up to 22 general-purpose I/O pins on the QFN32 device
- GPIO pins can be configured as inputs or outputs
- GPIOs support interrupts, wake-up, pull-up/pull-down and debounce
- UART: 2-channel UART interfaces
- SPI: 2 × SPI interfaces
- I²C: 2 × I²C interfaces
- PWM: 6 × PWM outputs
- ADC: 12-bit analog inputs
- QDEC: 3 × quadrature decoder interfaces
- PDM/DMIC: Digital microphone interface
- SWD: Serial Wire Debug interface
- RF: Single-pin 2.4 GHz antenna connection

### This repository

- flash - includes scripts to load BOOT firmware as well as helper tools
- bin - precompiles BOOT and APP firmware
- web - OTA management portal for managing the device after BOOT firmware is flashed
- hdp16 - source code and SDK

### If you like it
Buy me a coffee

### HDP16 software

There are 2 types of software in play:
- BOOT
- APP

The functionality overlaps to a degree but they reside in a different places on the chip.

BOOT can be only programmed using physical wiring (see "flash" folder). It has a limitted functionality firmware that exposes OTA to flash APP. The device has a watchdog and will reboot itself after 6min in this mode.
APP is the fully featured firmware that can be easily compiled and flashed over the air into the chip.

HDP16 boots by default into APP.
To force boot into BOOT mode, hold the button pressed and power the device. It will load the BOOT mode and skip the APP. This is useful when a corrupted APP flash happens.

There are 2 ways to check which mode the device is in:
- see UART output (required wire connection to the P9 (TX); configured to 115200 speed;
- use BLE scanner to discover services and characteristics. 0xFFF3 characteristic is the OTA one that is present in BOOT mode only.

To change mode from APP->BOOT, use the Web interface. Button "Mode OTA". It sends command 0x72 0x55 to the device which trigger mode change.
