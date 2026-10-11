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
OP_SET_MODE = 0x0B
OP_PING = 0x0C
OP_CLEAR = 0x21         # sub = mode, header = data type
OP_KEYS = 0x22
OP_LEDATA = 0x24        # per-key static colors
OP_MACROS = 0x25
OP_LIGHT_KEYS = 0x26    # key-press lighting index
OP_LIGHT_DATA = 0x27
OP_FN_KEYS = 0x31

# OP_INFO sub-commands (byte 1)
INFO_FIRMWARE = 0x01
INFO_DEVICE_ID = 0x02
INFO_MODEL = 0x08
INFO_MATRIX = 0x09

# Modes (profile slots) for OP_SET_MODE and profile writes
MODE_STANDARD = 1
MODE_OFFLINE = (2, 3, 4)    # offline profiles 1-3
MODE_ONLINE = 5

# OP_CLEAR data types
DATA_KEYS = 1
DATA_LEDATA = 3
DATA_MACROS = 4
DATA_LIGHT_KEYS = 5
DATA_LIGHT_DATA = 6
DATA_FN_KEYS = 7

# Online ("driver") mode
OP_DRIVER_INPUT = 0x15          # 01 mouse buttons, 02 key state, 03 key reports on/off; 04 = key report (keyboard → PC)
OP_DRIVER_KEYS = 0x16           # online key table: type 1 keys, 3 key-press lighting index
OP_DRIVER_LE = 0x17             # 01 = lighting config
OP_LIVE_LIGHT = 0x1A            # 01 = frame data, 02 = show
LIVE_LEDS = 132                 # LEDs in a live frame (22 × 6 grid)

# Writes whose header is (len << 24) + 24-bit address; the others use (len << 16) + 16-bit address
LONG_ADDRESS_OPS = {0x16, 0x1A, OP_LIGHT_DATA}

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


# --- Profile writes ----------------------------------------------------------------------------

def set_mode(mode: int) -> bytes:
    return packet(OP_SET_MODE, mode)


def clear(mode: int, data_type: int) -> bytes:
    return packet(OP_CLEAR, mode, struct.pack("<I", data_type))


def ping() -> bytes:
    return packet(OP_PING, 0)


def key_reports(on: bool) -> bytes:
    return packet(OP_DRIVER_INPUT, 0x03, payload=bytes([1 if on else 0]))


def driver_le_config(model=240, sub=1, brightness=18, speed=3, direction=0, rgb=(0, 0, 0), enable=15) -> bytes:
    """`17 01`: the lighting config the app sends when entering online mode (fixed values in the app)."""
    return packet(OP_DRIVER_LE, 0x01, payload=bytes([model, sub, brightness, speed, direction,
                                                     *(-(-c // 2) for c in rgb), enable]))


def live_frame(colors: dict[int, tuple[int, int, int]]) -> list[bytes]:
    """`1A 01` chunks for one frame (LED index → RGB; others dark), then `1A 02` to show it."""
    data = bytearray(LIVE_LEDS * 4)
    for led, (r, g, b) in colors.items():
        if 0 <= led < LIVE_LEDS:
            data[led * 4:led * 4 + 4] = bytes([r, g, b, 100])
    return chunks(OP_LIVE_LIGHT, 0x01, bytes(data)) + [packet(OP_LIVE_LIGHT, 0x02)]


def parse_key_report(report: bytes) -> set[int] | None:
    """`15 04` from the keyboard: the matrix indexes of the keys held down now."""
    if len(report) < 24 or report[0] != OP_DRIVER_INPUT or report[1] != 0x04:
        return None
    return {(i - 8) * 8 + j for i in range(8, 24) for j in range(8) if report[i] >> j & 1}


def chunks(op: int, mode: int, data: bytes) -> list[bytes]:
    """Split `data` into write reports of up to 56 bytes, each carrying its address and length."""
    shift = 24 if op in LONG_ADDRESS_OPS else 16
    out = []
    for addr in range(0, len(data), PAYLOAD_LEN):
        part = data[addr:addr + PAYLOAD_LEN]
        out.append(packet(op, mode, struct.pack("<I", (len(part) << shift) + addr), part))
    return out


# --- Info (handshake) --------------------------------------------------------------------------

def info_request(sub: int) -> bytes:
    return packet(OP_INFO, sub)


@dataclass(frozen=True)
class Firmware:
    id: int          # e.g. 0x84223311; matches "FWID" in the vendor app's model list
    version_raw: int # u16; the app shows it as v<high byte>.<low byte>

    @property
    def version(self) -> str:
        return f"v{self.version_raw >> 8}.{self.version_raw & 0xFF}"


def parse_firmware(report: bytes) -> Firmware:
    return Firmware(*struct.unpack_from("<IH", report, PAYLOAD_OFFSET))


def parse_model(report: bytes) -> int:
    """Model ID (u32), followed by u16 0xFFFF and a CRC16 of those 6 bytes."""
    model, _, check = struct.unpack_from("<IHH", report, PAYLOAD_OFFSET)
    if crc16(report[PAYLOAD_OFFSET:PAYLOAD_OFFSET + 6]) != check:
        raise ValueError("model id check failed")
    return model


def parse_matrix(report: bytes) -> tuple[int, int]:
    """Key matrix (columns, rows). Key tables have columns × rows entries of 4 bytes."""
    return report[PAYLOAD_OFFSET], report[PAYLOAD_OFFSET + 1]
