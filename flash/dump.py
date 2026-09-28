#!/usr/bin/env python3

import sys
import time
import serial
import RPi.GPIO as GPIO
import hashlib

# ============================================================
# ST17H65 / PHY6222M005 read-only flash dumper
#
# Dumps the external SPI flash using the native flash controller.
#
# IMPORTANT ADDRESSING:
#   - The flash itself is addressed from 0x000000 to 0x07FFFF.
#   - 0x4000C894 receives the SPI FLASH OFFSET, NOT 0x11000000+.
#   - 0x4000C890 = flash command register.
#   - 0x4000C8A0 = flash data register.
#
# A 4-byte SPI READ uses command value 0x03BA0001.
#
# No flash write, erase, WREN or status-register-write commands
# are used by this script.
# ============================================================

UART = "/dev/serial0"
BAUD = 115200
RST = 25

FLASH_SIZE = 0x80000          # 512 KiB
FLASH_END = FLASH_SIZE - 1

FLASH_ADDR_REG = 0x4000C894
FLASH_CMD_REG = 0x4000C890
FLASH_DATA_REG = 0x4000C8A0

FLASH_READ_CMD = 0x03BA0001

ROM_ID = b"0x001360eb"

p = serial.Serial(UART, BAUD, timeout=0.10)


# ============================================================
# Serial helpers
# ============================================================

def read_until_text(text, timeout=2.0):
    target = text.encode("ascii")
    deadline = time.monotonic() + timeout
    data = bytearray()

    while time.monotonic() < deadline:
        chunk = p.read(1)
        if chunk:
            data.extend(chunk)

            if target in data:
                return bytes(data)

    return bytes(data)


def send_cmd(cmd, timeout=2.0):
    p.reset_input_buffer()
    p.write(cmd.encode("ascii"))
    p.flush()

    return read_until_text("#OK>>:", timeout)


def require_ok(cmd, timeout=2.0):
    response = send_cmd(cmd, timeout)

    if b"#OK>>:" not in response:
        raise RuntimeError(
            f"Command failed: {cmd!r} -> {response!r}"
        )

    return response


# ============================================================
# Bootloader entry
# ============================================================

def enter_bootloader():
    print("Entering bootloader...", flush=True)

    for attempt in range(1, 101):
        print(
            f"Attempt {attempt}: reset -> waiting for cmd>>:",
            flush=True
        )

        GPIO.output(RST, GPIO.LOW)
        time.sleep(0.30)
        GPIO.output(RST, GPIO.HIGH)

        p.reset_input_buffer()

        deadline = time.monotonic() + 1.0
        found = False

        while time.monotonic() < deadline:
            p.write(b"UXTDWU")
            p.flush()

            response = read_until_text("cmd>>:", timeout=0.10)

            if b"cmd>>:" in response:
                found = True
                break

            time.sleep(0.03)

        if found:
            print("Bootloader prompt received: cmd>>:", flush=True)
            print("Waiting 3 seconds...", flush=True)
            time.sleep(3.0)

            # Remove any bootloader/banner bytes that appeared
            # during the settling period. This happens BEFORE rdrev+.
            print("Clearing RX buffer...", flush=True)
            p.reset_input_buffer()

            return

        print("No cmd>>: received. Retrying...", flush=True)
        time.sleep(1.0)

    raise RuntimeError(
        "Could not enter bootloader after 100 attempts"
    )


# ============================================================
# Register access
# ============================================================

def read_reg(address):
    cmd = f"rdreg{address:08x}"

    p.reset_input_buffer()
    p.write(cmd.encode("ascii"))
    p.flush()

    response = read_until_text("#OK>>:", timeout=2.0)

    marker = b"=0x"
    start = response.find(marker)

    if start < 0:
        raise RuntimeError(
            f"rdreg failed at 0x{address:08X}: {response!r}"
        )

    end = response.find(b"#", start)

    if end < 0:
        raise RuntimeError(
            f"Invalid rdreg response at 0x{address:08X}: {response!r}"
        )

    value_text = response[start + len(marker):end]

    try:
        return int(value_text, 16)
    except ValueError:
        raise RuntimeError(
            f"Invalid register value at 0x{address:08X}: "
            f"{response!r}"
        )


def write_reg(address, value):
    # IMPORTANT: the ROM command syntax requires a space between
    # the register address and the 32-bit value.
    cmd = f"wrreg{address:08x} {value:08x}"

    response = send_cmd(cmd)

    if b"#OK>>:" not in response:
        raise RuntimeError(
            f"wrreg failed: {cmd} -> {response!r}"
        )


# ============================================================
# Flash controller initialization
# ============================================================

def init_flash():
    print("Initialising flash controller...", flush=True)

    # These are the controller initialisation writes previously
    # verified on this ST17H65 / 6222M005 target.
    write_reg(0x4000F054, 0x00000000)
    write_reg(0x4000F140, 0x00000000)
    write_reg(0x4000F144, 0x00000000)

    require_ok("spifs 0 1 3 0")
    require_ok("sfmod 2 2")


# ============================================================
# Flash read
# ============================================================

def read_flash_word(flash_offset):
    """
    Read exactly 4 bytes from the external SPI flash.

    flash_offset is the physical SPI flash offset:
        0x000000 .. 0x07FFFC

    It is NOT a CPU address such as 0x11000000.
    """

    if flash_offset < 0 or flash_offset > FLASH_SIZE - 4:
        raise ValueError(
            f"Invalid flash offset: 0x{flash_offset:X}"
        )

    # Set SPI flash address.
    write_reg(FLASH_ADDR_REG, flash_offset)

    # Issue validated 4-byte SPI READ.
    write_reg(FLASH_CMD_REG, FLASH_READ_CMD)

    time.sleep(0.005)

    # The controller presents the four returned bytes in this
    # 32-bit register. The observed byte order is little-endian.
    value = read_reg(FLASH_DATA_REG)

    return value.to_bytes(4, byteorder="little")


def read_flash_word_retry(flash_offset, retries=3):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return read_flash_word(flash_offset)
        except Exception as exc:
            last_error = exc

            if attempt < retries:
                time.sleep(0.05)

    raise last_error


# ============================================================
# Main
# ============================================================

def main():
    if len(sys.argv) not in (2, 3):
        print(
            f"Usage: {sys.argv[0]} OUTPUT_FILE [LENGTH]",
            file=sys.stderr
        )
        print(
            f"Example: {sys.argv[0]} dump.bin",
            file=sys.stderr
        )
        print(
            f"Example: {sys.argv[0]} dump.bin 0x80000",
            file=sys.stderr
        )
        sys.exit(1)

    output_file = sys.argv[1]

    if len(sys.argv) == 3:
        try:
            length = int(sys.argv[2], 0)
        except ValueError:
            print("ERROR: LENGTH must be an integer.", file=sys.stderr)
            sys.exit(1)
    else:
        length = FLASH_SIZE

    if length <= 0:
        print("ERROR: length must be greater than zero.", file=sys.stderr)
        sys.exit(1)

    if length > FLASH_SIZE:
        print(
            f"ERROR: length exceeds flash size "
            f"(0x{FLASH_SIZE:X} bytes).",
            file=sys.stderr
        )
        sys.exit(1)

    if length % 4 != 0:
        print(
            "ERROR: length must be a multiple of 4.",
            file=sys.stderr
        )
        sys.exit(1)

    print()
    print("========== ST17H65 FLASH DUMP ==========")
    print(f"Output file:      {output_file}")
    print(f"Flash size:       0x{FLASH_SIZE:06X} ({FLASH_SIZE} bytes)")
    print(f"Dump length:      0x{length:06X} ({length} bytes)")
    print(f"Flash range:      0x000000 - 0x{length - 1:06X}")
    print()
    print("Addressing:")
    print("  SPI flash offset -> 0x4000C894")
    print("  READ command     -> 0x4000C890 = 0x03BA0001")
    print("  data register    -> 0x4000C8A0")
    print()

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)

    try:
        enter_bootloader()

        response = send_cmd("rdrev+")

        print("rdrev+ response:")
        print(response.decode("ascii", errors="replace").strip())

        if ROM_ID not in response.lower():
            raise RuntimeError(
                "Unexpected ROM ID. Expected 0x001360eb."
            )

        init_flash()

        print()
        print("Starting dump... I am working, please wait 30sec to see progress", flush=True)

        sha = hashlib.sha256()
        total_sum = 0
        dumped = 0

        with open(output_file, "wb") as f:
            while dumped < length:
                flash_offset = dumped

                data = read_flash_word_retry(flash_offset)

                f.write(data)
                sha.update(data)
                total_sum = (total_sum + sum(data)) & 0xFFFFFFFF

                dumped += 4

                if dumped % 0x1000 == 0 or dumped == length:
                    percent = dumped * 100.0 / length
                    print(
                        f"  0x{dumped:06X} / 0x{length:06X} "
                        f"({percent:6.2f}%)",
                        flush=True
                    )

        print()
        print("========== DUMP COMPLETE ==========")
        print(f"Bytes written:    {dumped}")
        print(f"SHA256:           {sha.hexdigest()}")
        print(f"Byte sum:         0x{total_sum:08X}")
        print()

        if dumped == FLASH_SIZE:
            print(
                "Full 512 KiB image dumped "
                f"(flash offsets 0x000000-0x{FLASH_END:06X})."
            )
        else:
            print(
                f"Partial image dumped "
                f"(flash offsets 0x000000-0x{dumped - 1:06X})."
            )

    finally:
        GPIO.cleanup()
        p.close()


if __name__ == "__main__":
    main()

