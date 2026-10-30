#!/usr/bin/env python3
"""
Repack an Android boot image (header v0-v2): replace only the kernel,
keep ramdisk / second / recovery_dtbo / dtb / cmdline byte-identical.

Usage:
  python repack_boot.py original_boot.img new_Image.gz output_boot.img
  python repack_boot.py --selftest original_boot.img   # round-trip + id check
"""
import hashlib
import struct
import sys

MAGIC = b"ANDROID!"
# header v0 generic fields
# v1 (offset 1632): recovery_dtbo_size(u32), recovery_dtbo_offset(u64), header_size(u32)
# v2 (offset 1648): dtb_size(u32), dtb_addr(u64)
OFF_RDTBO_SIZE = 1632
OFF_HDR_SIZE = 1644
OFF_DTB_SIZE = 1648
OFF_DTB_ADDR = 1652


def align(x, page):
    return (x + page - 1) // page * page


def parse(orig):
    if orig[:8] != MAGIC:
        sys.exit("not an Android boot image")
    (ks, ka, rs, ra, ss, sa, ta, ps, hv, osv) = struct.unpack_from("<10I", orig, 8)
    rdtbo_size = struct.unpack_from("<I", orig, OFF_RDTBO_SIZE)[0] if hv >= 1 else 0
    hdr_size = struct.unpack_from("<I", orig, OFF_HDR_SIZE)[0] if hv >= 1 else 0
    dtb_size = struct.unpack_from("<I", orig, OFF_DTB_SIZE)[0] if hv >= 2 else 0

    off_k = ps
    off_r = align(off_k + ks, ps)
    off_s = align(off_r + rs, ps)
    off_rdtbo = align(off_s + ss, ps)
    off_dtb = align(off_rdtbo + rdtbo_size, ps)

    return dict(ps=ps, hv=hv, osv=osv, ks=ks, rs=rs, ss=ss, rdtbo_size=rdtbo_size,
                dtb_size=dtb_size, hdr_size=hdr_size,
                kernel=orig[off_k:off_k + ks],
                ramdisk=orig[off_r:off_r + rs],
                second=orig[off_s:off_s + ss] if ss else b"",
                rdtbo=orig[off_rdtbo:off_rdtbo + rdtbo_size] if rdtbo_size else b"",
                dtb=orig[off_dtb:off_dtb + dtb_size] if dtb_size else b"",
                header=bytearray(orig[:ps]))


def boot_id(kernel, ramdisk, second, rdtbo, dtb):
    h = hashlib.sha1()
    for blob in (kernel, ramdisk, second, rdtbo, dtb):
        h.update(blob)
        h.update(struct.pack("<I", len(blob)))
    return h.digest()


def build(info, kernel, page_size=None):
    ps = page_size or info["ps"]
    header = bytearray(info["header"])
    struct.pack_into("<I", header, 8, len(kernel))
    # id field is 32 bytes: 20-byte SHA1 + 12 zero bytes
    header[576:608] = boot_id(kernel, info["ramdisk"], info["second"],
                              info["rdtbo"], info["dtb"]) + b"\x00" * 12

    out = bytearray(header)
    for blob in (kernel, info["ramdisk"], info["second"], info["rdtbo"], info["dtb"]):
        if not blob:
            continue
        out += blob
        out += b"\x00" * (align(len(blob), ps) - len(blob))
    return out


def main(argv):
    if len(argv) == 3 and argv[1] == "--selftest":
        orig = open(argv[2], "rb").read()
        info = parse(orig)
        print(f"page={info['ps']} hv={info['hv']} kernel={info['ks']} "
              f"ramdisk={info['rs']} dtb={info['dtb_size']} rdtbo={info['rdtbo_size']}")
        rebuilt = build(info, info["kernel"])
        expected_size = align(info["ps"] + info["ks"] + info["rs"] + info["ss"]
                              + info["rdtbo_size"] + info["dtb_size"], info["ps"])
        print(f"original={len(orig)} rebuilt={len(rebuilt)} expected={expected_size}")
        prefix_ok = bytes(rebuilt) == orig[:len(rebuilt)]
        tail_zero = set(orig[len(rebuilt):]) <= {0}
        print("header+sections identical:", prefix_ok, "| trailing pad all zero:", tail_zero)
        orig_id = orig[576:608].hex()
        calc_id = (boot_id(info["kernel"], info["ramdisk"], info["second"],
                           info["rdtbo"], info["dtb"]) + b"\x00" * 12).hex()
        print("id match:", orig_id == calc_id, orig_id[:16], calc_id[:16])
        return 0 if (prefix_ok and tail_zero and orig_id == calc_id) else 1

    if len(argv) != 4:
        sys.exit(__doc__)

    orig_path, kernel_path, out_path = argv[1], argv[2], argv[3]
    orig = open(orig_path, "rb").read()
    info = parse(orig)
    new_kernel = open(kernel_path, "rb").read()
    out = build(info, new_kernel)
    # The dumped partition carries stale AVB0/AVBf structures after the image.
    # Zero-pad to the original size so the flash fully overwrites them with a
    # consistent (unsigned) partition state.
    if "--no-pad" not in argv and len(out) < len(orig):
        out += b"\x00" * (len(orig) - len(out))
    open(out_path, "wb").write(out)
    print(f"kernel {info['ks']} -> {len(new_kernel)} bytes; "
          f"image -> {len(out)} bytes: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
