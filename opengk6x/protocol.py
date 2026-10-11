"""GK6X keyboard protocol: packet framing, CRC and response parsers (pure, no I/O).

Every command is one 64-byte output report on the vendor interface (usage page 0xFF00, no report IDs;
hidapi: write 0x00 + 64 B). The keyboard answers each one with a 64-byte input report. Layout of both:

    [0] op   [1] sub   [2..5] op-specific (result code / offset / length)   [6..7] CRC16 (LE)   [8..63] payload

The CRC is CRC-16/CCITT-FALSE over all 64 bytes with the CRC field zeroed. See docs/PROTOCOL.md.
"""
import struct
from dataclasses import dataclass

VID = 0x1EA7
PID_WIRED = 0x0907      # keyboard on the cable
PID_DONGLE = 0x0067     # 2.4 GHz receiver (nRF52); same vendor interface, not verified yet
USAGE_PAGE = 0xFF00

REPORT_LEN = 64
CRC_OFFSET = 6
PAYLOAD_OFFSET = 8
PAYLOAD_LEN = REPORT_LEN - PAYLOAD_OFFSET   # 56 (0x38) bytes per report

# Opcodes (byte 0)
OP_INFO = 0x01
OP_PING = 0x0C

# OP_INFO sub-commands (byte 1)
INFO_FIRMWARE = 0x01
INFO_MODEL = 0x08
INFO_BUFFERS = 0x09

RESULT_OK = 1


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final xor)."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
        crc &= 0xFFFF
    return crc


def packet(op: int, sub: int = 0, header: bytes = b"", payload: bytes = b"") -> bytes:
    """Build one 64-byte report. `header` fills bytes 2..5, `payload` bytes 8..63."""
    if len(header) > 4 or len(payload) > PAYLOAD_LEN:
        raise ValueError("header or payload too long")
    buf = bytearray(REPORT_LEN)
    buf[0], buf[1] = op, sub
    buf[2:2 + len(header)] = header
    buf[PAYLOAD_OFFSET:PAYLOAD_OFFSET + len(payload)] = payload
    struct.pack_into("<H", buf, CRC_OFFSET, crc16(buf))
    return bytes(buf)


def crc_ok(report: bytes) -> bool:
    if len(report) < REPORT_LEN:
        return False
    buf = bytearray(report[:REPORT_LEN])
    (stored,) = struct.unpack_from("<H", buf, CRC_OFFSET)
    buf[CRC_OFFSET:CRC_OFFSET + 2] = b"\0\0"
    return crc16(buf) == stored


def is_reply(report: bytes, op: int, sub: int) -> bool:
    return len(report) >= REPORT_LEN and report[0] == op and report[1] == sub


def payload(report: bytes) -> bytes:
    return bytes(report[PAYLOAD_OFFSET:REPORT_LEN])


# --- Info (handshake) --------------------------------------------------------------------------

def info_request(sub: int) -> bytes:
    return packet(OP_INFO, sub)


@dataclass(frozen=True)
class Firmware:
    id: int          # e.g. 0x84223311; matches "FWID" in the vendor app's model list
    minor: int
    major: int

    @property
    def version(self) -> str:
        return f"{self.major}.{self.minor}"


def parse_firmware(report: bytes) -> Firmware:
    fw_id, minor, major = struct.unpack_from("<IBB", report, PAYLOAD_OFFSET)
    return Firmware(fw_id, minor, major)


def parse_model(report: bytes) -> int:
    """Model ID (u32), followed by u16 0xFFFF and a CRC16 of those 6 bytes."""
    model, _, check = struct.unpack_from("<IHH", report, PAYLOAD_OFFSET)
    if crc16(report[PAYLOAD_OFFSET:PAYLOAD_OFFSET + 6]) != check:
        raise ValueError("model id check failed")
    return model


def parse_buffers(report: bytes) -> tuple[int, int]:
    """Two buffer-size bytes the vendor app uses to size key/light data (meaning not fully known)."""
    return report[PAYLOAD_OFFSET], report[PAYLOAD_OFFSET + 1]
