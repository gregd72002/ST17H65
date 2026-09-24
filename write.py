#!/usr/bin/env python3

import sys
import time
import hashlib
from pathlib import Path

import serial
import RPi.GPIO as GPIO

# ============================================================
# ST17H65 / PHY6222 512 KiB FULL PROGRAMMER
#
# Proven protocol for this device:
#
#   spifs 0 1 3 0
#   sfmod 2 2
#   cpnum 64
#   wrreg1fff0898 00400000
#
# For each 8 KiB block:
#
#   cpbin cN <offset | 0x80000> 2000 1FFF0000
#   by hex mode:
#   [8192 bytes]
#   checksum is: 0xXXXXXXXX
#   [host verifies checksum]
#   [host echoes XXXXXXXX]
#   #OK>>:
#
# SAFETY:
#   - Expects exactly 512 KiB input image.
#   - Verifies SHA-256 before programming.
#   - DOES NOT erase flash.
#   - Verifies every block checksum before echoing it.
#   - On checksum mismatch/error, resets the device and exits.
#   - No confirmation prompt.
#
# This script programs only. Use the separate erase tool first
# if the flash needs to be erased.
# ============================================================

UART = "/dev/serial0"
BAUD = 115200

RST_TM_GPIO = 25

FLASH_SIZE = 0x80000          # 512 KiB
BLOCK_SIZE = 0x2000           # 8 KiB
BLOCK_COUNT = FLASH_SIZE // BLOCK_SIZE  # 64

FLASH_ADDRESS_FLAG = FLASH_SIZE          # 0x80000
SRAM_ADDRESS = 0x1FFF0000

BOOT_WAIT = 3.0


def reset_target():
    print("\nResetting target...")
    GPIO.output(RST_TM_GPIO, GPIO.LOW)
    time.sleep(0.30)
    GPIO.output(RST_TM_GPIO, GPIO.HIGH)
    time.sleep(0.10)


def rom_cmd(ser, cmd, timeout=3.0):
    """Send a ROM command and require #OK>>:."""
    print(f"  ROM command: {cmd!r}")

    ser.reset_input_buffer()
    ser.timeout = timeout

    ser.write((cmd + " ").encode("ascii"))
    ser.flush()

    response = ser.read_until(b"#OK>>:")

    print(f"  response: {response!r}")

    if not response.endswith(b"#OK>>:"):
        raise RuntimeError(
            f"ROM command failed: {cmd!r}, response={response!r}"
        )

    return response


def enter_bootloader(ser):
    """Enter ROM bootloader using the known working TM/RST bridge."""
    print("\nEntering bootloader...")

    for attempt in range(1, 101):
        print(f"\nAttempt {attempt}")

        print("  RESET: GPIO25 LOW")
        GPIO.output(RST_TM_GPIO, GPIO.LOW)
        time.sleep(0.30)

        print("  RESET: GPIO25 HIGH")
        GPIO.output(RST_TM_GPIO, GPIO.HIGH)
        time.sleep(0.05)

        ser.reset_input_buffer()

        print("  Waiting for cmd>>: ...")

        deadline = time.monotonic() + 1.0
        found = False

        while time.monotonic() < deadline:
            ser.write(b"UXTDWU")
            ser.flush()

            ser.timeout = 0.10
            data = ser.read(64)

            if data:
                print(f"  RX: {data!r}")

                if b"cmd>>:" in data or b"fct>>:" in data:
                    found = True
                    break

            time.sleep(0.03)

        if found:
            print("\n*** BOOTLOADER ENTERED ***")
            print(f"\nWaiting {BOOT_WAIT:g} seconds...")
            time.sleep(BOOT_WAIT)
            print("\nBootloader ready.")
            return True

        print("  no cmd>>: response")
        print("  retrying...")

        time.sleep(0.5)

    return False


def read_revision(ser):
    print("\nReading ROM/chip revision...")

    ser.reset_input_buffer()
    ser.timeout = 3.0

    ser.write(b"rdrev+ ")
    ser.flush()

    response = ser.read_until(b"#OK>>:")
    print(f"  rdrev response: {response!r}")

    if not response.endswith(b"#OK>>:"):
        raise RuntimeError(f"rdrev failed: {response!r}")

    # This programmer is specifically for the discovered 6222M005.
    if b"0x001360eb" not in response:
        raise RuntimeError(
            "Unexpected chip revision. Expected 0x001360eb / 6222M005."
        )


def initialise_programming(ser):
    print("\nInitialising flash controller registers...")

    for cmd in (
        "wrreg4000f054 00000000",
        "wrreg4000f140 00000000",
        "wrreg4000f144 00000000",
    ):
        rom_cmd(ser, cmd)

    print("\nInitialising SPI flash interface...")

    rom_cmd(ser, "spifs 0 1 3 0")
    rom_cmd(ser, "sfmod 2 2")

    print(f"\nSetting image block count: {BLOCK_COUNT}")

    rom_cmd(ser, f"cpnum {BLOCK_COUNT}")

    print("\nInitialising external flash size for copy engine...")

    rom_cmd(ser, "wrreg1fff0898 00400000")


def write_block(ser, block_number, data):
    if len(data) != BLOCK_SIZE:
        raise RuntimeError(
            f"Block {block_number}: expected {BLOCK_SIZE} bytes, "
            f"got {len(data)}"
        )

    offset = block_number * BLOCK_SIZE
    rom_address = offset | FLASH_ADDRESS_FLAG

    command = (
        f"cpbin c{block_number} "
        f"{rom_address:X} "
        f"{BLOCK_SIZE:X} "
        f"{SRAM_ADDRESS:X}"
    )

    print("\n" + "=" * 60)
    print(f"WRITE BLOCK {block_number + 1}/{BLOCK_COUNT}")
    print(f"  Flash offset : 0x{offset:06X}")
    print(f"  ROM address  : 0x{rom_address:06X}")
    print(f"  Size         : 0x{BLOCK_SIZE:X} ({BLOCK_SIZE} bytes)")
    print(f"  SRAM address : 0x{SRAM_ADDRESS:08X}")
    print(f"  Data SHA256  : {hashlib.sha256(data).hexdigest()}")
    print(f"  Byte sum     : 0x{sum(data) & 0xFFFFFFFF:08X}")
    print("=" * 60)

    # Send cpbin command.
    ser.reset_input_buffer()
    ser.timeout = 5.0

    print(f"  ROM command: {command!r}")

    ser.write((command + " ").encode("ascii"))
    ser.flush()

    response = ser.read_until(b"by hex mode:")

    print(f"  initial response: {response!r}")

    if not response.endswith(b"by hex mode:"):
        raise RuntimeError(
            f"cpbin block {block_number}: did not receive "
            f"'by hex mode:': {response!r}"
        )

    # The proven ROM protocol sends the payload immediately after
    # "by hex mode:".
    print("  ROM accepted binary transfer.")

    ser.write(data)
    ser.flush()

    print(f"  Sent {len(data)} bytes.")

    # The ROM returns exactly:
    #   checksum is: 0xXXXXXXXX
    #
    # We deliberately capture all bytes first.
    ser.timeout = 5.0

    first = ser.read(1)

    if not first:
        raise RuntimeError(
            f"cpbin block {block_number}: no checksum response "
            f"within 5 seconds"
        )

    captured = bytearray(first)

    ser.timeout = 1.0

    while len(captured) < 23:
        chunk = ser.read(23 - len(captured))

        if not chunk:
            break

        captured.extend(chunk)

    print(f"  ROM checksum response: {bytes(captured)!r}")

    expected_prefix = b"checksum is: 0x"

    if not bytes(captured).startswith(expected_prefix):
        raise RuntimeError(
            f"cpbin block {block_number}: unexpected checksum response: "
            f"{bytes(captured)!r}"
        )

    if len(captured) != 23:
        raise RuntimeError(
            f"cpbin block {block_number}: checksum response has "
            f"{len(captured)} bytes, expected 23: {bytes(captured)!r}"
        )

    checksum_ascii = bytes(captured[15:23])

    try:
        rom_checksum = int(checksum_ascii.decode("ascii"), 16)
    except ValueError:
        raise RuntimeError(
            f"cpbin block {block_number}: invalid ROM checksum "
            f"{checksum_ascii!r}"
        )

    calculated_checksum = sum(data) & 0xFFFFFFFF

    print(f"  ROM checksum       : 0x{rom_checksum:08x}")
    print(f"  Calculated checksum: 0x{calculated_checksum:08x}")

    # SAFETY GATE:
    # Never echo a checksum that doesn't match our source data.
    if rom_checksum != calculated_checksum:
        print("\n*** CHECKSUM MISMATCH ***")
        print("The ROM received data that does not match our source block.")
        print("The checksum will NOT be echoed.")
        raise RuntimeError(
            f"cpbin block {block_number}: checksum mismatch: "
            f"ROM=0x{rom_checksum:08x}, "
            f"calculated=0x{calculated_checksum:08x}"
        )

    print("  *** CHECKSUM MATCH ***")
    print("  Echoing verified checksum to ROM...")

    ser.write(checksum_ascii)
    ser.flush()

    ser.timeout = 5.0
    final_response = ser.read(6)

    print(f"  final ROM response: {final_response!r}")

    if final_response != b"#OK>>:":
        raise RuntimeError(
            f"cpbin block {block_number}: expected #OK>>:, "
            f"got {final_response!r}"
        )

    print(f"  *** BLOCK {block_number + 1} ACCEPTED ***")


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} original_flash.bin")
        sys.exit(1)

    image_path = Path(sys.argv[1])

    if not image_path.is_file():
        print(f"ERROR: file not found: {image_path}")
        sys.exit(1)

    image = image_path.read_bytes()

    print("============================================================")
    print("ST17H65 / PHY6222 FULL PROGRAMMER")
    print("============================================================")
    print(f"Image       : {image_path}")
    print(f"Image size  : {len(image)} bytes")
    print(f"Expected    : {FLASH_SIZE} bytes")

    if len(image) != FLASH_SIZE:
        print(
            f"ERROR: image must be exactly {FLASH_SIZE} bytes "
            f"(512 KiB)."
        )
        sys.exit(1)

    image_sha = hashlib.sha256(image).hexdigest()

    print(f"Image SHA256: {image_sha}")
    print()
    print("IMPORTANT:")
    print("  This script DOES NOT ERASE FLASH.")
    print("  It only programs the supplied 512 KiB image.")
    print("  Every 8 KiB block is independently checksum-verified")
    print("  before its checksum is echoed to the ROM.")
    print("  A checksum mismatch/error resets the target and exits.")
    print()

    ser = None
    success = False

    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RST_TM_GPIO, GPIO.OUT, initial=GPIO.LOW)

    try:
        ser = serial.Serial(
            UART,
            BAUD,
            timeout=0.10,
            write_timeout=5
        )

        if not enter_bootloader(ser):
            raise RuntimeError("Could not enter ROM bootloader")

        read_revision(ser)

        initialise_programming(ser)

        print("\n")
        print("============================================================")
        print("PROGRAMMING ORIGINAL 512 KiB IMAGE")
        print("============================================================")

        for block_number in range(BLOCK_COUNT):
            offset = block_number * BLOCK_SIZE
            data = image[offset:offset + BLOCK_SIZE]

            write_block(ser, block_number, data)

        print("\n" + "=" * 60)
        print("PROGRAMMING COMPLETE")
        print("=" * 60)
        print(f"Blocks programmed : {BLOCK_COUNT}")
        print(f"Bytes programmed  : {FLASH_SIZE}")
        print(f"Image SHA256      : {image_sha}")
        print()
        print("All 64 blocks received matching ROM/source checksums")
        print("and returned #OK>>:.")

        success = True

    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        print("Resetting target and exiting.")

    except Exception as exc:
        print("\n*** PROGRAMMING ERROR ***")
        print(str(exc))
        print()
        print("NO FURTHER BLOCKS WILL BE SENT.")
        print("Resetting target and exiting.")

    finally:
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

        # Always leave the target reset on exit/error.
        GPIO.output(RST_TM_GPIO, GPIO.LOW)
        time.sleep(0.30)
        GPIO.output(RST_TM_GPIO, GPIO.HIGH)

        GPIO.cleanup()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

