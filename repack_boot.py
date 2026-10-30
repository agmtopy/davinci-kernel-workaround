#!/usr/bin/env python3
"""
Repack Android boot image: replace the kernel with a new Image.gz,
keep ramdisk / second / dtb / cmdline untouched. Supports header v0-v2.

Usage: python repack_boot.py original_boot.img new_Image.gz output_boot.img
"""
import struct
import sys

MAGIC = b"ANDROID!"


def align(x, page):
    return (x + page - 1) // page * page


def main(orig_path, kernel_path, out_path):
    with open(orig_path, "rb") as f:
        orig = f.read()

    if orig[:8] != MAGIC:
        sys.exit("not an Android boot image")

    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr,
     second_size, second_addr, tags_addr, page_size,
     header_version, os_version) = struct.unpack_from("<10I", orig, 8)

    if header_version >= 1:
        recovery_dtbo_size, recovery_dtbo_addr, hdr_size = struct.unpack_from("<3I", orig, 1632)
    else:
        recovery_dtbo_size, recovery_dtbo_addr, hdr_size = 0, 0, 0
    if header_version >= 2:
        dtb_size, dtb_addr = struct.unpack_from("<2I", orig, 1640)
    else:
        dtb_size, dtb_addr = 0, 0

    print(f"page_size={page_size} header_version={header_version}")
    print(f"kernel_size={kernel_size} ramdisk_size={ramdisk_size} "
          f"second_size={second_size} dtb_size={dtb_size} recovery_dtbo={recovery_dtbo_size}")

    # section offsets in original image (each section page-aligned)
    off_kernel = page_size
    off_ramdisk = align(off_kernel + kernel_size, page_size)
    off_second = align(off_ramdisk + ramdisk_size, page_size)
    off_rdtbo = align(off_second + second_size, page_size)
    off_dtb = align(off_rdtbo + recovery_dtbo_size, page_size)

    ramdisk = orig[off_ramdisk:off_ramdisk + ramdisk_size]
    second = orig[off_second:off_second + second_size]
    rdtbo = orig[off_rdtbo:off_rdtbo + recovery_dtbo_size] if recovery_dtbo_size else b""
    dtb = orig[off_dtb:off_dtb + dtb_size] if dtb_size else b""

    with open(kernel_path, "rb") as f:
        new_kernel = f.read()
    print(f"new kernel size: {len(new_kernel)} (old: {kernel_size})")

    header = bytearray(orig[:page_size])
    struct.pack_into("<I", header, 8, len(new_kernel))  # kernel_size only

    out = bytearray(header)
    out += new_kernel
    out += b"\x00" * (align(len(new_kernel), page_size) - len(new_kernel))
    out += ramdisk
    out += b"\x00" * (align(len(ramdisk), page_size) - len(ramdisk))
    out += second
    out += b"\x00" * (align(len(second), page_size) - len(second))
    if rdtbo:
        out += rdtbo
        out += b"\x00" * (align(len(rdtbo), page_size) - len(rdtbo))
    if dtb:
        out += dtb
        out += b"\x00" * (align(len(dtb), page_size) - len(dtb))

    with open(out_path, "wb") as f:
        f.write(out)
    print(f"written {out_path}: {len(out)} bytes (original: {len(orig)})")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
