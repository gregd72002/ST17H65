#!/usr/bin/env python3

import sys
import struct
import argparse

MAX_FLASH_SIZE = 0x200000

PHY_FLASH_ADDR = 0x11000000
PHY_SRAM_ADDR  = 0x1fff0000

SEGMENT_TABLE_ADDR = 0x2000
DEF_START_RUN_APP_ADDR = 0x1fff1838
DEF_START_WR_FLASH_ADDR = 0x5000


# ------------------------------------------------------------
# This is intentionally based closely on rdwr_phy62x2.py
# ParseHexFile()
# ------------------------------------------------------------

def ParseHexFile(hexfile):

    try:
        fin = open(hexfile)
    except:
        print("No file opened", hexfile)
        return None

    table = []
    result = bytearray()

    addr = 0
    naddr = 0
    taddr = 0
    addr_flg = 0

    # Exactly as the original:
    table.append([0, result, 0x2000])

    for hexstr in fin.readlines():

        hexstr = hexstr.strip()

        # Extended Linear Address
        if hexstr[7:9] == '04':

            if len(result):
                table.append([addr, result, 0])

            addr = int(hexstr[9:13], 16) << 16

            addr_flg = 0
            result = bytearray()

            continue

        # EOF / Start Address
        if hexstr[7:9] == '05' or hexstr[7:9] == '01':

            table.append([addr, result, 0])
            break

        # Record address
        taddr = int(hexstr[3:7], 16)

        if addr_flg == 0:

            addr_flg = 1
            addr = addr | taddr
            naddr = taddr

        if taddr != naddr:

            addr_flg = 1

            table.append([addr, result, 0])

            addr = (addr & 0xFFFF0000) | taddr

            result = bytearray()

        # Append record data
        result.extend(
            bytearray.fromhex(hexstr[9:-2])
        )

        naddr = taddr + int(hexstr[1:3], 16)

    fin.close()

    return table


# ------------------------------------------------------------
# Reproduce rdwr_phy62x2.py HexfHeader()
# non-TG7100 path
# ------------------------------------------------------------

def HexfHeader(hp,
               start=DEF_START_RUN_APP_ADDR,
               raddr=DEF_START_WR_FLASH_ADDR):

    if len(hp) <= 1:
        return None

    # 0x100-byte header
    hexf = bytearray(b'\xff') * 0x100

    # Number of real segments
    hexf[0:4] = int.to_bytes(
        len(hp) - 1,
        4,
        byteorder='little'
    )

    # Application start address
    hexf[8:12] = int.to_bytes(
        start,
        4,
        byteorder='little'
    )

    # --------------------------------------------------------
    # First pass: determine flash range and SRAM size
    # --------------------------------------------------------

    faddr_min = MAX_FLASH_SIZE - 1
    faddr_max = 0
    rsize = 0

    for ihp in hp:

        # SRAM
        if (ihp[0] & PHY_SRAM_ADDR) == PHY_SRAM_ADDR:

            rsize += len(ihp[1])

        # Flash / XIP
        elif (ihp[0] & ~(MAX_FLASH_SIZE - 1)) == PHY_FLASH_ADDR:

            offset = ihp[0] & (MAX_FLASH_SIZE - 1)

            if faddr_min > offset:
                faddr_min = offset

            send = offset + len(ihp[1])

            if faddr_max <= send:
                faddr_max = send

    # Same collision handling as original
    if (raddr + rsize) >= faddr_min:
        raddr = (faddr_max + 3) & 0xfffffffc

    print("---- Segments Table -------------------------------------")

    # --------------------------------------------------------
    # Second pass: assign physical flash locations
    # --------------------------------------------------------

    for ihp in hp:

        # SRAM
        if (ihp[0] & PHY_SRAM_ADDR) == PHY_SRAM_ADDR:

            faddr = raddr

            raddr += (len(ihp[1]) + 3) & 0xfffffffc

        # XIP flash
        elif (ihp[0] & ~(MAX_FLASH_SIZE - 1)) == PHY_FLASH_ADDR:

            faddr = ihp[0] & (MAX_FLASH_SIZE - 1)

        # Dummy segment
        elif ihp[0] == 0:

            continue

        else:

            print(
                "Invalid Segment Address 0x%08x!"
                % ihp[0]
            )

            return None

        # Store calculated flash address
        ihp[2] = faddr

        print(
            "Segment: %08x <- Flash addr: %08x, Size: %08x"
            % (
                ihp[0],
                faddr,
                len(ihp[1])
            )
        )

        # Original rdwr_phy62x2.py:
        #
        # <flash address>
        # <size>
        # <CPU address>
        # <0xffffffff>

        hexf.extend(
            bytearray(
                struct.pack(
                    '<IIII',
                    faddr,
                    len(ihp[1]),
                    ihp[0],
                    0xffffffff
                )
            )
        )

    return hexf


# ------------------------------------------------------------
# Create raw flash image
# ------------------------------------------------------------

def make_image(hexfile, imgfile, image_size):

    hp = ParseHexFile(hexfile)

    if hp is None:
        raise RuntimeError("HEX parsing failed")

    # Same as rdwr_phy62x2.py:
    hexf = HexfHeader(
        hp,
        DEF_START_RUN_APP_ADDR,
        DEF_START_WR_FLASH_ADDR
    )

    if hexf is None:
        raise RuntimeError("Could not create segment table")

    # Original does:
    #
    #     hp[0][1] = hexf
    #
    hp[0][1] = hexf

    # --------------------------------------------------------
    # Find required image size
    # --------------------------------------------------------

    required_size = SEGMENT_TABLE_ADDR + len(hexf)

    for ihp in hp[1:]:

        end = ihp[2] + len(ihp[1])

        if end > required_size:
            required_size = end

    if required_size > image_size:

        raise RuntimeError(
            "Image needs 0x%x bytes, "
            "but requested image size is 0x%x"
            % (required_size, image_size)
        )

    # --------------------------------------------------------
    # Start with all FF
    # --------------------------------------------------------

    image = bytearray(b'\xff') * image_size

    # --------------------------------------------------------
    # Write segment table
    # --------------------------------------------------------

    image[
        SEGMENT_TABLE_ADDR:
        SEGMENT_TABLE_ADDR + len(hexf)
    ] = hexf

    print(
        "Segment Table[%02d] <- Flash addr: %08x, Size: %08x"
        % (
            len(hp) - 1,
            SEGMENT_TABLE_ADDR,
            len(hexf)
        )
    )

    # --------------------------------------------------------
    # Write each actual segment
    # --------------------------------------------------------

    for ihp in hp[1:]:

        flash_addr = ihp[2]
        data = ihp[1]

        if (ihp[0] & PHY_SRAM_ADDR) == PHY_SRAM_ADDR:
            kind = "SRAM"
        elif (ihp[0] & ~(MAX_FLASH_SIZE - 1)) == PHY_FLASH_ADDR:
            kind = "XIP"
        else:
            kind = "???"

        print(
            "%-4s: CPU 0x%08x -> FLASH 0x%08x, size 0x%x"
            % (
                kind,
                ihp[0],
                flash_addr,
                len(data)
            )
        )

        image[
            flash_addr:
            flash_addr + len(data)
        ] = data

    # --------------------------------------------------------
    # Write image
    # --------------------------------------------------------

    with open(imgfile, "wb") as f:
        f.write(image)

    print()
    print(
        "Segment table: FLASH 0x%08x, size 0x%x"
        % (SEGMENT_TABLE_ADDR, len(hexf))
    )

    print(
        "Image size:    0x%x (%d bytes)"
        % (image_size, image_size)
    )

    print("Written:       %s" % imgfile)


def main():

    parser = argparse.ArgumentParser(
        description="Convert PHY62x2 HEX to raw flash image"
    )

    parser.add_argument(
        "hexfile",
        help="Input Intel HEX file"
    )

    parser.add_argument(
        "imgfile",
        help="Output raw flash image"
    )

    parser.add_argument(
        "--size",
        type=lambda x: int(x, 0),
        default=0x80000,
        help="Flash image size (default: 0x80000)"
    )

    args = parser.parse_args()

    try:

        make_image(
            args.hexfile,
            args.imgfile,
            args.size
        )

    except Exception as e:

        print("Error:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
