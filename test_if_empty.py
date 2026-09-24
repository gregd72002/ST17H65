#!/usr/bin/env python3

import serial
import RPi.GPIO as GPIO
import time
import re

PORT = "/dev/serial0"
BAUD = 115200
RST = 25

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


def setup_flash():
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


def read_flash_4(address):
    print(f"\n0x{address:06X}", end=" ")

    # Set flash address.
    write_reg(0x4000C894, address)

    # SPI READ 0x03, 4-byte result.
    write_reg(0x4000C890, 0x03BA0001)

    # Give the SPI transaction time to complete.
    time.sleep(0.005)

    # Read the flash data register.
    value = read_reg(0x4000C8A0)

    raw = value.to_bytes(4, "big")

    print(
        f"C8A0=0x{value:08X}  "
        f"DATA={' '.join(f'{b:02X}' for b in raw)}"
    )

    return raw


def main():
    try:
        if not enter_bootloader():
            raise RuntimeError("Could not enter bootloader")

        r = cmd("rdrev+ ", timeout=3)

        if b"0x001360eb" not in r.lower():
            raise RuntimeError(f"Unexpected ROM ID: {r!r}")

        setup_flash()

        print("\n" + "=" * 70)
        print("BYTE-ALIGNMENT READ DIAGNOSTIC")
        print("=" * 70)
        print("Flash was fully erased before this test.")
        print("Every read should therefore return FF FF FF FF.")
        print()
        print("Reading every byte offset from 0x2000 through 0x201F.")
        print("=" * 70)

        results = {}

        for address in range(0x2000, 0x2020):
            results[address] = read_flash_4(address)

        print("\n" + "=" * 70)
        print("SUMMARY")
        print("=" * 70)

        bad = 0

        for address in range(0x2000, 0x2020):
            data = results[address]
            value = int.from_bytes(data, "big")

            if value != 0xFFFFFFFF:
                bad += 1
                print(
                    f"0x{address:06X}: "
                    f"{value:08X}  <-- NOT FFFFFFFF"
                )
            else:
                print(
                    f"0x{address:06X}: "
                    f"FFFFFFFF"
                )

        print()
        print(f"Non-FF results: {bad} / 32")

        if bad == 0:
            print("ALL READS RETURNED FFFFFFFF.")
        else:
            print("Some reads are not FFFFFFFF.")
            print("The address/alignment pattern above is the important result.")

    finally:
        GPIO.output(RST, GPIO.LOW)
        p.close()
        GPIO.cleanup()


if __name__ == "__main__":
    main()

