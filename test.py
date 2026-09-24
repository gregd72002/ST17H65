#!/usr/bin/env python3

import sys
import time
import serial
import RPi.GPIO as GPIO
import hashlib

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

UART = "/dev/serial0"
BAUD = 115200
RST = 25

FLASH_SIZE = 0x80000
DEFAULT_FILE = "original_flash.bin"

# ------------------------------------------------------------
# Serial helpers
# ------------------------------------------------------------

p = serial.Serial(UART, BAUD, timeout=1.0)

def send_cmd(cmd, wait=True):
    """Send an ASCII bootloader command and return the response."""
    p.reset_input_buffer()
    p.write(cmd.encode("ascii"))
    p.flush()

    if not wait:
        return b""

    time.sleep(0.01)
    return p.read_until(b"#OK>>:")


def read_until_text(text, timeout=2.0):
    """Read until text appears or timeout expires."""
    end = time.time() + timeout
    data = b""

    while time.time() < end:
        chunk = p.read(256)
        if chunk:
            data += chunk
            if text.encode() in data:
                return data

    return data


# ------------------------------------------------------------
# Bootloader entry
# ------------------------------------------------------------

def enter_bootloader():
    print("Entering bootloader...")

    for attempt in range(1, 101):
        print(f"Attempt {attempt}: reset -> waiting for cmd>>:")

        GPIO.output(RST, GPIO.LOW)
        time.sleep(0.30)

        GPIO.output(RST, GPIO.HIGH)

        # UXTDWU is sent at 115200 on this ST17H65 / 6222M005.
        p.reset_input_buffer()

        end = time.time() + 1.0
        found = False

        while time.time() < end:
            p.write(b"UXTDWU")
            p.flush()

            response = read_until_text("cmd>>:", timeout=0.10)

            if b"cmd>>:" in response:
                found = True
                break

            time.sleep(0.03)

        if found:
            print("Bootloader prompt received: cmd>>:")

            # Give the bootloader time to settle before commands.
            print("Waiting 3 seconds...")
            time.sleep(3.0)
            #print("Clearing RX buffer...")
            #p.reset_input_buffer()
            #time.sleep(0.1)
            return

        print("No cmd>>: received. Retrying...")
        time.sleep(1.0)

    raise RuntimeError("Could not enter bootloader after 100 attempts")


# ------------------------------------------------------------
# Register access
# ------------------------------------------------------------

def read_reg(address):
    """Read a 32-bit register using rdreg."""
    cmd = f"rdreg{address:08x}"
    p.reset_input_buffer()
    p.write(cmd.encode("ascii"))
    p.flush()

    response = read_until_text("#OK>>:", timeout=1.0)

    # Expected format:
    # =0x12345678#OK>>:
    marker = b"=0x"
    pos = response.find(marker)

    if pos < 0:
        raise RuntimeError(
            f"rdreg failed at 0x{address:08X}: {response!r}"
        )

    end = response.find(b"#", pos)

    if end < 0:
        raise RuntimeError(
            f"Invalid rdreg response at 0x{address:08X}: {response!r}"
        )

    value_text = response[pos + 3:end]

    try:
        return int(value_text, 16)
    except ValueError:
        raise RuntimeError(
            f"Invalid register value at 0x{address:08X}: {response!r}"
        )


def write_reg(address, value):
    """Write a 32-bit register using wrreg."""
    cmd = f"wrreg{address:08x} {value:08x}"
    response = send_cmd(cmd)

    if b"#OK>>:" not in response:
        raise RuntimeError(
            f"wrreg failed: {cmd} -> {response!r}"
        )


# ------------------------------------------------------------
# Flash setup
# ------------------------------------------------------------

def init_flash():
    print("Initialising flash controller...")

    write_reg(0x4000F054, 0x00000000)
    write_reg(0x4000F140, 0x00000000)
    write_reg(0x4000F144, 0x00000000)

    response = send_cmd("spifs 0 1 3 0")
    if b"#OK>>:" not in response:
        raise RuntimeError(f"spifs failed: {response!r}")

    response = send_cmd("sfmod 2 2")
    if b"#OK>>:" not in response:
        raise RuntimeError(f"sfmod failed: {response!r}")


# ------------------------------------------------------------
# Flash read
# ------------------------------------------------------------

def read_flash_word(address, expected_word):
    print(f"Reading 0x{address:06X}...", flush=True)

    print("  set flash address", flush=True)
    write_reg(0x4000C894, address)

    print("  issue READ command", flush=True)
    write_reg(0x4000C890, 0x03BA0001)

    time.sleep(0.005)

    print("  read data register", flush=True)
    value = read_reg(0x4000C8A0)

    data = value.to_bytes(4, byteorder="little")

    if data == expected_word:
        result = "MATCH"
    else:
        result = "MISMATCH"

    print(
        f"  got: {data.hex(' ')}   "
        f"file: {expected_word.hex(' ')}   "
        f"{result}",
        flush=True
    )

    return data


def read_flash_word_retry(address, expected_word, retries=3):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return read_flash_word(address, expected_word)
        except Exception as exc:
            last_error = exc

            if attempt < retries:
                time.sleep(0.05)

    raise last_error


# ------------------------------------------------------------
# Main verification
# ------------------------------------------------------------

def main():
    if len(sys.argv) not in (3, 4):
        print(
            f"Usage: {sys.argv[0]} <start_address> <length> "
            f"[binary_file]"
        )
        print()
        print("Examples:")
        print(f"  {sys.argv[0]} 0x2000 256")
        print(f"  {sys.argv[0]} 0x2000 0x400 original_flash.bin")
        sys.exit(1)

    try:
        start_addr = int(sys.argv[1], 0)
        length = int(sys.argv[2], 0)
    except ValueError:
        print("ERROR: start_address and length must be integers.")
        sys.exit(1)

    filename = sys.argv[3] if len(sys.argv) == 4 else DEFAULT_FILE

    if start_addr < 0:
        print("ERROR: start address cannot be negative.")
        sys.exit(1)

    if length <= 0:
        print("ERROR: length must be greater than zero.")
        sys.exit(1)

    if start_addr % 4 != 0:
        print("ERROR: start address must be a multiple of 4.")
        sys.exit(1)

    if length % 4 != 0:
        print("ERROR: length must be a multiple of 4.")
        sys.exit(1)

    if start_addr + length > FLASH_SIZE:
        print(
            f"ERROR: requested range exceeds flash size "
            f"(0x{FLASH_SIZE:X} bytes)."
        )
        sys.exit(1)

    with open(filename, "rb") as f:
        image = f.read()

    if len(image) != FLASH_SIZE:
        print(
            f"ERROR: {filename} is {len(image)} bytes; "
            f"expected exactly {FLASH_SIZE} bytes."
        )
        sys.exit(1)

    expected = image[start_addr:start_addr + length]

    print()
    print("========== FLASH VERIFICATION ==========")
    print(f"Binary file:      {filename}")
    print(f"Start address:    0x{start_addr:06X}")
    print(f"Length:           0x{length:X} ({length} bytes)")
    print(f"End address:      0x{start_addr + length - 1:06X}")
    print()

    # GPIO setup.
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)

    actual = bytearray()
    mismatched_reads = 0
    mismatched_bytes = 0
    total_reads = length // 4
    mismatch_details = []

    try:
        enter_bootloader()

        # Confirm ROM identity.
        response = send_cmd("rdrev+")
        print("rdrev+ response:")
        print(response.decode("ascii", errors="replace").strip())

        if b"0x001360eb" not in response.lower():
            raise RuntimeError(
                "Unexpected ROM ID. Expected 0x001360eb."
            )

        init_flash()

        print()
        print("Starting read/compare...")
        print()

        for index in range(total_reads):
            address = start_addr + index * 4
            expected_word = expected[index * 4:index * 4 + 4]

            try:
                actual_word = read_flash_word_retry(address, expected_word)
            except Exception as exc:
                print(
                    f"READ ERROR at 0x{address:06X}: {exc}"
                )
                raise

            actual.extend(actual_word)

            if actual_word != expected_word:
                mismatched_reads += 1

                for byte_index in range(4):
                    if actual_word[byte_index] != expected_word[byte_index]:
                        mismatched_bytes += 1

                        if len(mismatch_details) < 20:
                            mismatch_details.append(
                                (
                                    address + byte_index,
                                    expected_word[byte_index],
                                    actual_word[byte_index],
                                )
                            )

                print(
                    f"MISMATCH 0x{address:06X}: "
                    f"expected {expected_word.hex(' ')} "
                    f"actual {actual_word.hex(' ')}"
                )

            # Compact progress output.
            if (index + 1) % 64 == 0 or index + 1 == total_reads:
                percent = (index + 1) * 100.0 / total_reads
                print(
                    f"Progress: {index + 1}/{total_reads} "
                    f"({percent:.1f}%)"
                )

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        print()
        print("========== SUMMARY ==========")
        print(
            f"Range:            "
            f"0x{start_addr:06X} - "
            f"0x{start_addr + length - 1:06X}"
        )
        print(f"Bytes checked:    {length}")
        print(f"Reads performed:  {total_reads}")
        print(f"Mismatched reads: {mismatched_reads}")
        print(f"Mismatched bytes: {mismatched_bytes}")
        print()

        expected_sha = hashlib.sha256(expected).hexdigest()
        actual_sha = hashlib.sha256(actual).hexdigest()

        expected_sum = sum(expected) & 0xFFFFFFFF
        actual_sum = sum(actual) & 0xFFFFFFFF

        print(f"Expected SHA256:  {expected_sha}")
        print(f"Actual SHA256:    {actual_sha}")
        print(f"Expected sum:     0x{expected_sum:08X}")
        print(f"Actual sum:       0x{actual_sum:08X}")

        if mismatch_details:
            print()
            print("First mismatches:")

            for address, exp, act in mismatch_details:
                print(
                    f"  0x{address:06X}: "
                    f"expected 0x{exp:02X}, "
                    f"actual 0x{act:02X}"
                )

        print()

        if mismatched_reads == 0:
            print("RESULT: PASS - all bytes match.")
        else:
            print("RESULT: FAIL - data mismatch detected.")

    finally:
        GPIO.cleanup()
        p.close()


if __name__ == "__main__":
    main()

