#!/usr/bin/env python3
"""Pack an ARM64 Image into an Android boot image v3 for vili (SM8350).

Boot v3 has no ramdisk/dtb inside the boot image (those live in
vendor_boot.img), so the xnu payload cannot ride the initrd like it did on
sweet. --payload pads the kernel blob to a 4 KiB boundary, appends the
payload, and stores its file offset/size in the ARM64 header's res2/res3
fields (offsets 0x20/0x28) for shim/loader.c to find at runtime.

  mkbootimg3.py OUT.img --kernel Image [--payload PAYLOAD.bin] \
      [--kernel-addr 0x12f67c0] [--os-version 0x1a000198] [--cmdline "..."]

Header layout (AOSP bootimg.h, header_version 3):
  0x000 magic[8] "ANDROID!"      0x018 header_size = 1580
  0x008 kernel_size              0x01c reserved[4]
  0x00c kernel_addr              0x028 header_version = 3
  0x010 os_version               0x02c cmdline[1536]
kernel blob starts at offset 0x1000 (one page after the 1580-byte header).
"""
import argparse, struct

HDR_SIZE = 1580
CMDLINE_LEN = 1536
PAGE = 0x1000
RES2, RES3 = 0x20, 0x28  # ARM64 Image header fields holding payload off/size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--kernel', required=True)
    ap.add_argument('--payload', help='SWEETXNU payload appended to the kernel blob')
    ap.add_argument('--kernel-addr', type=lambda x: int(x, 0), default=0x12f67c0,
                    help='value the vili stock boot.img uses')
    ap.add_argument('--os-version', type=lambda x: int(x, 0), default=0x1a000198,
                    help='value the vili stock boot.img uses')
    ap.add_argument('--cmdline', default='console=null')
    a = ap.parse_args()

    k = bytearray(open(a.kernel, 'rb').read())
    if k[56:60] != b'ARM\x64':
        raise SystemExit('kernel is not an ARM64 Image')
    if a.payload:
        p = open(a.payload, 'rb').read()
        off = (len(k) + 0xfff) & ~0xfff
        k += b'\0' * (off - len(k)) + p
        struct.pack_into('<Q', k, RES2, off)
        struct.pack_into('<Q', k, RES3, len(p))
        # image_size must cover the payload so ABL copies all of it
        struct.pack_into('<Q', k, 0x10, len(k))
        print(f'payload at +0x{off:x} ({len(p)} bytes), image_size=0x{len(k):x}')
    cmd = a.cmdline.encode()[:CMDLINE_LEN]
    hdr = struct.pack('<8sIII', b'ANDROID!', len(k), a.kernel_addr, a.os_version)
    hdr += struct.pack('<I', HDR_SIZE) + b'\0' * 16 + struct.pack('<I', 3)
    hdr += cmd + b'\0' * (CMDLINE_LEN - len(cmd))
    assert len(hdr) == HDR_SIZE
    open(a.out, 'wb').write(hdr + b'\0' * (PAGE - HDR_SIZE) + k)
    print(f'{a.out}: header v3, kernel {len(k)} bytes @ {a.kernel_addr:#x}')


if __name__ == '__main__':
    main()
