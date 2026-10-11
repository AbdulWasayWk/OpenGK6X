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


# File names the official app gives each type (8-byte header field; part of the key stream)
NAMES = {"PROFILE": "profile", "LIGHT": "light", "MACRO": "MACRO"}


def encode(type_name: str, body: bytes, name: str | None = None, timestamp: int | None = None) -> bytes:
    """Plain body → CMF file, as the app's cmfcodec.encode writes it."""
    import time
    typ = TYPE_NAMES.index(type_name)
    name_field = (name if name is not None else NAMES.get(type_name, "")).encode("latin-1")[:8].ljust(8, b"\0")
    header = bytearray(32)
    when = int(time.time()) if timestamp is None else timestamp
    struct.pack_into("<5IB", header, 0, MAGIC, 0, when, len(body), crc16(body), typ)
    header[24:32] = name_field
    struct.pack_into("<I", header, 4, crc16(header))
    key = crc16(name_field, crc16(type_name.encode()))
    out = bytearray()
    for p in body:
        out.append(p ^ (key & 0xFF))
        key = crc16(bytes([p]), key)
    return bytes(header) + bytes(out)
