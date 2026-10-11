"""Decode the vendor app's CMF files (.le lighting effects, .cms macros, .cmf profiles).

usage: cmf_decode.py <file-or-dir> <outdir>      (writes <name>.json / .txt per file)

Format (app src/libs/cmfcodec.js): 32-byte header (u32 magic "1FMC" 0x434D4631, u32 header CRC, u32 time, u32 size,
u32 data CRC, u8 type, 3 pad, 8-byte name), then the body XORed with a key stream: key = low byte of a CRC-16/CCITT
state that starts at crc(TYPE_NAME) continued over the 8-byte name, and is then updated with each *plain* byte.
"""
import os, struct, sys

TYPE_NAMES = ["_", "PROFILE", "LIGHT", "STATASTIC", "APPCONF", "MACRO"]


def crc16(data, crc=0xFFFF):
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        crc &= 0xFFFF
    return crc


def decode(blob):
    magic, _, _, size, _, typ = struct.unpack_from("<5IB", blob)
    if magic != 0x434D4631:
        raise ValueError("not a CMF file")
    name = blob[24:32]
    key = crc16(name, crc16(TYPE_NAMES[typ].encode()))
    out = bytearray()
    for c in blob[32:32 + size]:
        p = c ^ (key & 0xFF)
        out.append(p)
        key = crc16(bytes([p]), key)
    return TYPE_NAMES[typ], bytes(out)


src, dst = sys.argv[1], sys.argv[2]
files = [src] if os.path.isfile(src) else sorted(os.path.join(src, f) for f in os.listdir(src))
os.makedirs(dst, exist_ok=True)
for path in files:
    try:
        typ, body = decode(open(path, "rb").read())
    except (ValueError, IndexError, struct.error):
        continue
    ext = ".json" if body.lstrip()[:1] in (b"{", b"[") else ".txt"
    open(os.path.join(dst, os.path.splitext(os.path.basename(path))[0] + ext), "wb").write(body)
    print(f"{typ:8} {os.path.basename(path)} ({len(body)} B)")
