"""The vendor app's CMF container (.le lighting effects, .cms macros, .cmf profiles).

32-byte header (u32 magic 0x434D4631, u32 header CRC, u32 time, u32 size, u32 data CRC, u8 type, 3 pad, 8-byte name),
then the body XORed with a key stream: the low byte of a CRC-16/CCITT state that starts at crc(type name) continued
over the 8-byte name, and is then updated with each plain byte.
"""
import struct

from .protocol import crc16

MAGIC = 0x434D4631
TYPE_NAMES = ["_", "PROFILE", "LIGHT", "STATASTIC", "APPCONF", "MACRO"]   # sic


def decode(blob: bytes) -> tuple[str, bytes]:
    """Return (type name, plain body)."""
    if len(blob) < 32:
        raise ValueError("not a CMF file")
    magic, _, _, size, _, typ = struct.unpack_from("<5IB", blob)
    if magic != MAGIC or typ >= len(TYPE_NAMES):
        raise ValueError("not a CMF file")
    key = crc16(blob[24:32], crc16(TYPE_NAMES[typ].encode()))
    out = bytearray()
    for c in blob[32:32 + size]:
        p = c ^ (key & 0xFF)
        out.append(p)
        key = crc16(bytes([p]), key)
    return TYPE_NAMES[typ], bytes(out)


def decode_text(blob: bytes) -> str:
    """Plain body as text (UTF-8, byte-order mark removed)."""
    return decode(blob)[1].decode("utf-8-sig")
