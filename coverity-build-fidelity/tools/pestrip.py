"""Canonicalize a PE image for comparison against an unsigned local build.

An official release binary is usually Authenticode-signed; a local rebuild is
not. The signature is appended after the image and referenced by data
directory 4 (Certificate Table), whose RVA field is really a FILE OFFSET.
Leaving it in place makes the reference larger than the rebuild, which trips
the size-mismatch path and buries the real comparison.

This removes the signature deterministically:
  - truncate the file at the certificate table offset
  - zero the certificate table data directory entry
  - optionally zero the PE checksum, which is invalidated by the above

The result is NOT a valid signed binary and is only for comparison. Write it
alongside the original; never overwrite the reference.
"""
import shutil
import struct
import sys

import pe


def strip_signature(src, dst, zero_checksum=True):
    with open(src, "rb") as fh:
        data = bytearray(fh.read())
    p = pe.PE(bytes(data))
    info = {"src": src, "dst": dst, "was_signed": p.signed,
            "original_size": len(data)}

    if p.signed:
        off, size = p.cert
        info["cert_offset"] = off
        info["cert_size"] = size
        # The certificate table is required to sit at the end of the file.
        trailing = len(data) - (off + size)
        info["bytes_after_cert"] = trailing
        del data[off:]
        # Zero data directory 4 (RVA + Size).
        dd4 = p.off_optional + (112 if p.bits == 64 else 96) + 4 * 8
        struct.pack_into("<II", data, dd4, 0, 0)

    if zero_checksum:
        struct.pack_into("<I", data, p.off_checksum, 0)
        info["checksum_zeroed"] = True

    with open(dst, "wb") as fh:
        fh.write(data)
    info["output_size"] = len(data)
    return info


def main(argv):
    if len(argv) < 3:
        print("usage: pestrip.py IN OUT")
        return 2
    info = strip_signature(argv[1], argv[2])
    for k, v in info.items():
        print("  %-18s %s" % (k, v))
    if not info["was_signed"]:
        shutil.copyfile(argv[1], argv[2]) if False else None
        print("  note               input was not signed; only checksum zeroed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
