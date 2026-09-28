#!/usr/bin/env python3

import serial
import RPi.GPIO as GPIO
import time
import re

PORT = "/dev/serial0"
BAUD = 115200
RST = 25

FLASH_SIZE = 0x80000       # 512 KiB
SECTOR_SIZE = 0x10000      # 64 KiB

GPIO.setmode(GPIO.BCM)
GPIO.setup(RST, GPIO.OUT, initial=GPIO.LOW)

p = serial.Serial(PORT, BAUD, timeout=0.20)


def cmd(s, timeout=3.0, show=True):
    if show:
        print(f"\nROM command: '{s}'")

    p.reset_input_buffer()
    p.write((s + "\r\n").encode())
    p.flush()

    deadline = time.monotonic() + timeout
    data = b""

    while time.monotonic() < deadline:
        x = p.read(256)
        if x:
            data += x
            if b"#OK>>:" in data or b"#ER>>:" in data:
                break

    if show:
        print("response:", repr(data))

    return data


def enter_bootloader():
    print("Entering bootloader...")

    for attempt in range(1, 51):
        print(f"\nAttempt {attempt}: RESET")

        GPIO.output(RST, GPIO.LOW)
        time.sleep(0.30)
        GPIO.output(RST, GPIO.HIGH)

        print("Waiting for cmd>>: ...")

        deadline = time.monotonic() + 1.5
        buf = b""

        while time.monotonic() < deadline:
            p.write(b"UXTDWU\r\n")
            p.flush()

            x = p.read(256)

            if x:
                buf += x

                if b"cmd>>:" in buf or b"fct>>:" in buf:
                    print("BOOTLOADER FOUND:", repr(buf))
                    print("Waiting 3 seconds...")
                    time.sleep(3.0)
                    return True

            time.sleep(0.03)

        print("No cmd>>:, retrying...")

    return False


def write_reg(addr, value):
    r = cmd(f"wrreg{addr:08x} {value:08x}")

    if b"#OK>>:" not in r:
        raise RuntimeError(f"wrreg failed: {r!r}")


def read_reg(addr):
    r = cmd(f"rdreg{addr:08x}")

    m = re.search(rb"=0x([0-9A-Fa-f]{8})", r)

    if not m:
        raise RuntimeError(f"Could not read register 0x{addr:08X}: {r!r}")

    return int(m.group(1), 16)


def spi_status():
    # SPI command 0x05: Read Status Register.
    # No address; one byte returned.
    write_reg(0x4000C890, 0x05800001)

    value = read_reg(0x4000C8A0)

    return value & 0xFF


def spi_wren():
    # SPI command 0x06: Write Enable.
    #
    # IMPORTANT:
    # This is a command-only SPI transaction.
    # Do NOT use 0x06800001 here.
    write_reg(0x4000C890, 0x06000001)


def erase_64k(address):
    print(f"\nErasing 64 KiB sector at 0x{address:06X}")

    # Enable writes.
    spi_wren()

    status = spi_status()
    print(f"  Status after WREN: 0x{status:02X}")

    if not (status & 0x02):
        raise RuntimeError(
            f"WREN failed at 0x{address:06X}: "
            f"WEL bit is not set (status=0x{status:02X})"
        )

    # Set 24-bit flash address.
    write_reg(0x4000C894, address)

    # SPI command 0xD8: 64 KiB block erase.
    # This transaction includes a 3-byte address.
    write_reg(0x4000C890, 0xD80A0001)

    # Wait until BUSY clears.
    deadline = time.monotonic() + 15.0

    while True:
        status = spi_status()

        if not (status & 0x01):
            break

        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Timeout waiting for erase at 0x{address:06X}; "
                f"status=0x{status:02X}"
            )

        time.sleep(0.05)

    print(f"  Erase complete, status=0x{status:02X}")


def main():
    try:
        if not enter_bootloader():
            raise RuntimeError("Could not enter bootloader")

        r = cmd("rdrev+ ", timeout=3)

        if b"0x001360eb" not in r.lower():
            raise RuntimeError(
                f"Unexpected ROM ID. Expected 0x001360eb: {r!r}"
            )

        print("\nInitialising flash controller...")

        write_reg(0x4000F054, 0x00000000)
        write_reg(0x4000F140, 0x00000000)
        write_reg(0x4000F144, 0x00000000)

        print("\nConfiguring SPI flash interface...")

        r = cmd("spifs 0 1 3 0")
        if b"#OK>>:" not in r:
            raise RuntimeError(f"spifs failed: {r!r}")

        r = cmd("sfmod 2 2")
        if b"#OK>>:" not in r:
            raise RuntimeError(f"sfmod failed: {r!r}")

        print("\nChecking initial flash status...")

        status = spi_status()
        print(f"Initial flash status: 0x{status:02X}")

        if status & 0x01:
            raise RuntimeError(
                f"Flash is busy before erase: status=0x{status:02X}"
            )

        print("\nStarting FULL 512 KiB erase.")
        print("There are 8 x 64 KiB sectors.")

        for address in range(0, FLASH_SIZE, SECTOR_SIZE):
            erase_64k(address)

        print("\nFULL ERASE COMPLETE")

        status = spi_status()
        print(f"Final flash status: 0x{status:02X}")

        if status & 0x01:
            raise RuntimeError("Flash is still BUSY after full erase")

    finally:
        GPIO.output(RST, GPIO.LOW)
        p.close()
        GPIO.cleanup()


if __name__ == "__main__":
    main()

