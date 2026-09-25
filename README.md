# ST17H65
ST17H65 / PHY6222-compatible ROM interface as found on your MiLi MiTag HD-P16

# ST17H65 Flash Tools

Tools and documentation for reading, erasing and programming the internal
flash of the **ST17H65** Bluetooth Low Energy SoC used in the **MiLi MiTag
HD-P16**.

The ROM command interface identifies this device as:

    0x001360eb 6222M005

The ROM interface is closely related to the PHY6222 family. The commands
documented here have been experimentally verified on the actual ST17H65
device.

---
## Key files 

- dump.py - dump entire 512kb memory into a file. Note, this is painfully slow process
- erase.py - erases each of the 64 block 64kb at a time
- test_if_empty.py - reads data from flash to check if empty
- write.py - flashes selected file 
- test.py - compares provided number of bytes from selected block with a data from a file


---

## Toolchain

```
https://github.com/pvvx/THB2
```
---

## Standard firmware

Provided in dump.bin. By default, it shows boots sequence on UART. Keeping TX disconnected allow it to boot fully. Once TX is connected, the stock firmware does not initialise fully.
 
---

## Hardware

### Target device

- SoC: **ST17H65**
- Package: QFN32
- Internal flash: **512 KiB**
- CPU: ARM Cortex-M0-class core
- Clock: up to 48 MHz
- BLE SoC
- ROM command interface identifies as:
  `6222M005`
- ROM ID:
  `0x001360eb`

This project specifically targets the ST17H65 implementation found in the
MiLi MiTag HD-P16.

---

## ST17H65 pins used

The following pins are relevant to the programming/debugging work.

| Pin | Function | Use |
|-----|----------|-----|
| 3 | P2 / SWD_IO | SWD (not required for flashing) |
| 4 | P3 / SWD_CLK | SWD (not required for flashing) |
| 7 | TM / TEST_MODE | ROM/bootloader entry |
| 8 | P9 | UART TX |
| 9 | P10 | UART RX |
| 22 | RST_N | Reset |
| 24 | RF | Bluetooth RF |

### UART connection to Raspberry Pi

The ROM bootloader is accessed through the UART.

| ST17H65 | Raspberry Pi |
|---------|--------------|
| P9 / pin 8 (TX) | GPIO15 / UART RX |
| P10 / pin 9 (RX) | GPIO14 / UART TX |
| GND | GND |
| RST_N / pin 22 | GPIO25 |
| TM / pin 22 | GPIO25 |

UART speed used:

    115200 baud

The Raspberry Pi GPIO is 3.3 V logic.

---

## Entering the ROM bootloader

See example python files on the ROM bootloader entry.

The bootloader entry sequence is timing-sensitive on this particular device.

The working sequence used by this project is:

1. Assert reset (RST pin low)
2. Release reset (RST pin high)
3. Send:

       UXTDWU

   at 115200 baud.
4. Wait for:

       cmd>>:

5. Once `cmd>>:` is received, wait approximately 3 seconds before
   continuing with ROM commands.

Because bootloader entry can be unreliable, the tools retry the reset/handshake
sequence until the ROM responds.

Example response:

    cmd>>:

---

## Identifying the ROM

Send:

    rdrev+

The ST17H65 used by the MiLi MiTag responds:

    0x001360eb 6222M005 #OK>>:

This is useful for making sure that the expected ROM is connected before
performing flash operations.

---

# ROM commands

The following ROM commands have been observed and/or experimentally verified.

## General commands

### Read revision

    rdrev+

Example:

    0x001360eb 6222M005 #OK>>:

---

### Read register

    rdregXXXXXXXX

Example:

    rdreg4000c8a0

Response:

    =0xXXXXXXXX#OK>>:

---

### Write register

    wrregXXXXXXXX YYYYYYYY

Example:

    wrreg4000c894 00002000

Response:

    #OK>>:

---

### UART configuration

Observed ROM command:

    uarts%i

---

### Reset

Observed ROM command:

    reset

---

## Flash interface commands

The flash controller registers used by this project are:

| Register | Purpose |
|----------|---------|
| `0x4000C890` | Flash/SPI command register |
| `0x4000C894` | Flash address register |
| `0x4000C8A0` | Flash data register |
| `0x4000C8A4` | Additional flash data register |
| `0x4000C8A8` | Flash command/data register |

Additional controller registers used during initialization:

    0x4000F054
    0x4000F140
    0x4000F144

The working initialization sequence is:

    wrreg4000f054 00000000
    wrreg4000f140 00000000
    wrreg4000f144 00000000
    spifs 0 1 3 0
    sfmod 2 2

---

# Reading flash

The flash is read through the native SPI flash controller.

For a 4-byte SPI READ:

1. Write the flash address:

       wrreg4000c894 AAAAAAAA

2. Issue SPI READ (`0x03`) with a 3-byte address and 4-byte result:

       wrreg4000c890 03ba0001

3. Wait approximately 5 ms.

4. Read:

       rdreg4000c8a0

The returned 32-bit value contains the four flash bytes.

Example:

    wrreg4000c894 00002000
    wrreg4000c890 03ba0001

    rdreg4000c8a0

    =0xFFFFFFFF#OK>>:

After erasing the flash, an erased location therefore reads:

    FF FF FF FF

### Important

The command:

    038a0001

was initially used during development but was found to be incorrect for
a 4-byte read.

The verified command is:

    03ba0001

This distinction is important.

---

# Flash status

SPI `0x05` (Read Status Register) can be issued through:

    wrreg4000c890 05800001

followed by:

    rdreg4000c8a0

The low byte contains the SPI flash status.

Important bits:

| Bit | Meaning |
|-----|---------|
| bit 0 | BUSY |
| bit 1 | WEL (Write Enable Latch) |

Example:

    =0xffffff00#OK>>:

means:

    Status = 0x00

After Write Enable, the expected status is:

    Status = 0x02

---

# Flash Write Enable

SPI `0x06` (Write Enable) is issued as:

    wrreg4000c890 06000001

The WEL bit should then be set.

Verify with:

    wrreg4000c890 05800001
    rdreg4000c8a0

Expected low byte:

    0x02

### Important

The correct command is:

    06000001

not:

    06800001

The latter does not correctly perform the command-only Write Enable
transaction on this device.

---

# Erasing flash

The device contains 512 KiB of flash.

The flash can be erased in 64 KiB blocks.

Flash size:

    0x80000 bytes

64 KiB sector size:

    0x10000 bytes

Therefore there are eight sectors:

    0x00000
    0x10000
    0x20000
    0x30000
    0x40000
    0x50000
    0x60000
    0x70000

## 64 KiB erase sequence

For each sector:

### 1. Write Enable

    wrreg4000c890 06000001

### 2. Check WEL

    wrreg4000c890 05800001
    rdreg4000c8a0

The returned status should have:

    bit 1 = 1

### 3. Set flash address

For example:

    wrreg4000c894 00020000

### 4. Issue 64 KiB erase

    wrreg4000c890 d80a0001

This uses SPI command `0xD8`.

### 5. Poll BUSY

Repeatedly read the status register until:

    bit 0 = 0

The erase operation is then complete.

---

# Full 512 KiB erase

A complete erase consists of eight 64 KiB erase operations:

    0x00000
    0x10000
    0x20000
    0x30000
    0x40000
    0x50000
    0x60000
    0x70000

After a complete erase, flash reads should return:

    FF FF FF FF

throughout the entire 512 KiB address space.

---

# Programming flash

The ROM provides a bulk programming mechanism using `cpbin`.

The working initialization sequence discovered for this device is:

    spifs 0 1 3 0
    sfmod 2 2
    cpnum 64
    wrreg1fff0898 00400000

A block is then transferred using:

    cpbin cN OFFSET 2000 1FFF0000

where:

- `N` is the block/channel number used by the ROM
- `OFFSET` is the flash destination
- `2000` is 8192 bytes
- `1FFF0000` is the SRAM staging address

The ROM then enters a bulk transfer mode and reports:

    by hex mode:

The host sends exactly 8192 bytes.

The ROM calculates and reports:

    checksum is: 0xXXXXXXXX

The checksum is the 32-bit sum of all bytes in the transferred block:

    sum(data) & 0xffffffff

The host should independently calculate the checksum and only acknowledge
the block if the values match.

The ROM acknowledges a correct checksum with:

    #OK>>:

---

# 8 KiB programming blocks

The flash can therefore conveniently be programmed in 64 × 8 KiB blocks.

| Block | Flash address |
|------:|---------------|
| 0 | `0x00000` |
| 1 | `0x02000` |
| 2 | `0x04000` |
| ... | ... |
| 63 | `0x7E000` |

Block size:

    0x2000 = 8192 bytes

---

# Flash verification

Verification should use the native SPI READ mechanism rather than relying
only on the programming checksum.

For each 8 KiB block:

1. Read 8192 bytes from the flash.
2. Compare the result byte-for-byte against the source image.
3. Calculate SHA-256.
4. Report the number and locations of differing bytes.

A successful verification should report:

    Differing bytes: 0 / 8192

---

# Known ROM responses

Useful ROM prompts and responses observed on the ST17H65:

    cmd>>:

    fct>>:

    #OK>>:

    #ER>>:

    =0xXXXXXXXX#OK>>:

    by hex mode:

    checksum is: 0xXXXXXXXX

---

# Known ROM commands

Commands discovered during reverse engineering include:

    UXTDWU
    UXTL16
    UDLL48

    rdrev+
    rdregXXXXXXXX
    wrregXXXXXXXX YYYYYYYY

    uarts%i
    reset

    era4k %X
    er64k %X
    er512 %X
    erall

    etcpf
    cpbin c%d %X %X %X
    cpnum ffffffff

    spifs 0 1 3 0
    sfmod 2 2

Not all commands have been fully reverse engineered or tested on the
ST17H65. Commands documented as "known" should not automatically be assumed
safe.

---

# Original firmware backup

Before modifying the device, a complete 512 KiB dump should be made.

The original MiTag flash image used during development is:

    Size: 524288 bytes

SHA-256:

    b092d9c1d965175c8cee55ae0e012678c9c04244ad64096dbe849852e6374d4a

The original image should be treated as a **golden backup** and never
overwritten.

A complete dump should ideally be performed twice and the two resulting
SHA-256 hashes compared.

---

# Development notes

The ST17H65 ROM interface does not expose the flash as a simple readable
memory-mapped region through `rdreg`. Direct reads from addresses such as:

    0x11000000

may return:

    0xFFFFFFFF

even when the flash contains firmware.

The reliable method discovered for this device is to access the external
SPI flash interface through the internal flash controller registers.

The SPI flash JEDEC ID observed on the device is:

    EB 60 13

The SPI unique ID command (`0x4B`) also returned device-specific data.

---

# Safety

This project is intended for reverse engineering and development on hardware
you own or are authorized to modify.

Flash erase and programming can permanently destroy the original firmware.

Recommended workflow:

1. Read the complete flash.
2. Read it again.
3. Compare the two dumps.
4. Record the SHA-256 hash.
5. Preserve the original dump.
6. Perform experiments only on copies.
7. Verify every programmed block.
8. Keep a known-good recovery image.

---

# Disclaimer

This repository documents experimentally determined behaviour of a specific
ST17H65 device and its ROM.

It should not be assumed that every ST17H65, PHY6222, or related SoC has
identical ROM behaviour.

Commands and register values marked as experimentally verified were tested
on the MiLi MiTag HD-P16 hardware used for this project.

Work is based on https://github.com/pvvx/THB2
