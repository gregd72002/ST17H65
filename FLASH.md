The device flash size is 512KiB.

It is addressable - first byte 0x00000, last byte 0x7FFFF

However the CPU maps the flash into 0x11000000 space.


The boot ROM is physically at 0x10000000. But it is mapped to 0x00000000. This is where the CPU starts executing at power on.


# ST17H65 Flash Image Segments

| Segment | Purpose |
|---|---|
| Segment table | Boot metadata describing the firmware segments, their sizes, and their runtime SRAM destinations. |
| RAM initialization | Data stored in flash that is copied to SRAM during startup, initialized RAM data. |
| XIP / code + read-only data | Main application code and read-only data executed/read directly from flash using XIP. |


Segment table seem to be always located at 0x02000. The bootloader uses those entries to know where to read each segment from and where to put it at runtime.
XIP.

The SRAM segment at 0x05000


# Linker and flashing

The current toolchain builds ELF, BIN and HEX files. HEX contains explicit address data so a full 512kb image can be constructred from it.

The hex2img.py script does take Intel HEX file and constructs 512kb image that can be flashed. The script does:

```
1. Create 0x80000 bytes filled with 0xFF.
2. Read hex file.
3. Extract the firmware segments and their addresses.
4. Generate the segment table at physical 0x02000.
6. Place the SRAM-init segment at 0x05000.
7. Place the XIP segment at 0x10100 (this is calculated).
8. Write output flash image 
```

The output file can then be flashed using ./write.py.


Alternatively, THB flasher can be used with the hex:
```
./rdwr_phy62x2.py --port /dev/serial0 wh build/file.hex 
```

rdwr_phy62x2.py is modified version of the original to include:
- boot UART speed is 115200 for this chip
- enter programming mode in loop while trying to reset the chip

The ST17H65 requires the RESET pin and P7 (TST pin) pulled low temporarily to enter the programming mode.
