"""Offline profiles: the official app's profile JSON → the data blocks and packets it writes to the keyboard.

Mirrors GK6+ 8.0.7 `src/libs/profile.js` (writeDeviceConfig, getMacroData, getLightData, convertMacroData)
byte for byte, including its JavaScript number parsing; `tests/test_profile.py` checks against packets recorded
from the app's own code (`tools/re/golden_profile.js`). Formats: docs/PROTOCOL.md.

A profile is a dict in the app's format: ModeIndex (2-4 = offline profiles 1-3, 1 = standard), KeySet / FnKeySet
([{Index, DriverValue, Task?, KeyLE?}]), ModeLE ({GUID, Params?, LEData?}), LEData, DriverLE.
"""
import json
import math
import re
import struct
from dataclasses import dataclass
from typing import Callable

from . import protocol as p

LED_COUNT = 176             # lighting LED indexes (LocationCode); LED bitmaps are 22 bytes
MACRO_LEN = 512
LIGHT_HEADER_LEN = 512
LIGHT_MAX = 128 * 1024
MACRO_KEY = 0x0A010001      # driver value of a key bound to a macro; the low byte becomes the macro slot

# Macro key names (app src/libs/keymap.js KeyName → KeyCode): HID keyboard usages
MACRO_KEY_CODES = {
    '"Backspace"': 0x2A, '"Tab"': 0x2B, '"Enter"': 0x28, '"Ctrl"': 0xE0, '"Shift"': 0xE1, '"Alt"': 0xE2,
    '"Pause"': 0x48, '"Caps Lock"': 0x39, '"Esc"': 0x29, '"Space"': 0x2C, '"Page Up"': 0x4B, '"Page Down"': 0x4E,
    '"End"': 0x4D, '"Home"': 0x4A, '"Left"': 0x50, '"Up"': 0x52, '"Right"': 0x4F, '"Down"': 0x51,
    '"Print Screen"': 0x46, '"Insert"': 0x49, '"Delete"': 0x4C,
    **{f'"{d}"': 0x27 if d == 0 else 0x1D + d for d in range(10)},
    **{f'"{chr(65 + i)}"': 0x04 + i for i in range(26)},
    '"Left Win"': 0xE3, '"Right Win"': 0xE7,
    '"Num 0"': 0x62, **{f'"Num {d}"': 0x58 + d for d in range(1, 10)},
    '"Num *"': 0x55, '"Num +"': 0x57, '"Num -"': 0x56, '"Num ."': 0x63, '"Num /"': 0x54,
    **{f'"F{n}"': 0x39 + n for n in range(1, 13)},
    '"Num Lock"': 0x53, '"Scroll Lock"': 0x47, '"Right Shift"': 0xE5, '"Right Ctrl"': 0xE4, '"Menu"': 0x65,
    '";"': 0x33, '"="': 0x2E, '","': 0x36, '"-"': 0x2D, '"."': 0x37, '"/"': 0x38, '"`"': 0x35, '"["': 0x2F,
    '"\\"': 0x31, '"]"': 0x30, '"\'"': 0x34,
}
# Modifier names the app turns into modifier bits (data1) instead of key codes
MACRO_MODIFIERS = {'"Left Ctrl"': 0x01, '"Left Shift"': 0x02, '"Left Alt"': 0x04, '"Left Win"': 0x08,
                   '"Right Ctrl"': 0x10, '"Right Shift"': 0x20, '"Right Alt"': 0x40, '"Right Win"': 0x80}


# --- JavaScript number semantics (the app's JSON is loosely typed) ------------------------------

_JS_WS = " \t\n\r\v\f ﻿"


def js_parse_int(value, base: int) -> int | None:
    """parseInt(value, base); None for NaN."""
    if value is None:
        return None
    s = str(value).lstrip(_JS_WS)
    m = re.match(r"([+-]?)(0[xX])?([0-9a-fA-F]*)" if base == 16 else r"([+-]?)()([0-9]*)", s)
    if not m.group(3):
        return None
    n = int(m.group(3), base)
    return -n if m.group(1) == "-" else n


def js_number(value) -> float:
    """Number(value) (`value * 1` in the app); NaN when it isn't a number."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip(_JS_WS)
        if not s:
            return 0.0
        try:
            return float(int(s, 16)) if s[:2].lower() == "0x" else float(s)
        except ValueError:
            return math.nan
    return math.nan


def _index(value, size: int) -> int | None:
    """A buffer index as JS uses it: in range and integral, else the assignment does nothing."""
    n = js_number(value)
    return int(n) if n.is_integer() and 0 <= n < size else None


def _u8(value) -> int:
    """Buffer.writeUInt8 value coercion: NaN → 0, out of range → error."""
    n = js_number(value)
    if math.isnan(n):
        return 0
    if not 0 <= n <= 0xFF:
        raise ValueError(f"value {value!r} doesn't fit in a byte")
    return int(n)


def _u16(value) -> int:
    n = js_number(value)
    if math.isnan(n):
        return 0
    if not 0 <= n <= 0xFFFF:
        raise ValueError(f"value {value!r} doesn't fit in 16 bits")
    return int(n)


def _hex32(value) -> int:
    """parseInt(value, 16) as the app then uses it: (v >> n) & 0xFF on a 32-bit int; NaN → 0."""
    n = js_parse_int(value, 16)
    return 0 if n is None else n & 0xFFFFFFFF


# --- Blocks ------------------------------------------------------------------------------------

def key_table(keyset: list, size: int, macro_index: bytes | None) -> bytes:
    """Driver value per matrix index (u32 LE), unset = FF FF FF FF. macro_index None = the app's Fn-layer bug
    (it reads past its macro index table, which gives 0)."""
    table = bytearray(b"\xff" * size)
    for key in keyset[:128]:
        idx = _index(key.get("Index"), size // 4)
        if idx is None:
            continue
        v = _hex32(key.get("DriverValue"))
        low = (macro_index[idx] if macro_index is not None else 0) if v == MACRO_KEY else v & 0xFF
        table[idx * 4:idx * 4 + 4] = bytes([low, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF])
    return bytes(table)


def color_block(colors) -> bytes:
    """Per-LED colors {led: "0xRRGGBB"} → 176 × `R G B 100`; LEDs not listed stay all zero."""
    block = bytearray(LED_COUNT * 4)
    for key in (range(len(colors)) if isinstance(colors, list) else (colors or {})):
        led = js_parse_int(key, 10)
        if led is None or not 0 <= led < LED_COUNT:
            continue
        v = _hex32(colors[led] if isinstance(colors, list) else colors.get(str(led)))
        block[led * 4:led * 4 + 4] = bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, 100])
    return bytes(block)


def parse_macro_script(text: str) -> list[tuple[str, str]]:
    """`.cms` text → [(taskName, taskValue)] for the [Script] section (app macro.js stringToJson)."""
    tasks, state = [], ""
    for line in re.split(r"[\r\n]+", text):
        if not line:
            continue
        m = re.search(r"\s*\[(.+)\]\s*", line)
        if m:
            state = m.group(1)
        elif state == "Script":
            parts = line.split(" ")
            tasks.append((line, "") if len(parts) == 1 else (parts[0], " ".join(parts[1:])))
    return tasks


def _macro_action(name: str, value: str) -> tuple:
    """(data0, data1, status, type); None = field not written."""
    d0 = d1 = status = None
    if value == "":
        typ = 0x02
        status = 0x01 if "Down" in name else 0x02 if "Up" in name else None
        d0 = 0x01 if "Left" in name else 0x02 if "Right" in name else None
    elif name == "Delay":
        typ = 0x03
        ms = js_parse_int(value, 10)
        if ms is not None:
            d1, d0 = math.floor(ms / 256), math.fmod(ms, 256)
    else:
        typ = 0x01
        status = 0x01 if name == "KeyDown" else 0x02 if name == "KeyUp" else None
        if value in MACRO_MODIFIERS:
            d1 = MACRO_MODIFIERS[value]
        else:
            d0 = MACRO_KEY_CODES.get(value)
    return d0, d1, status, typ


def macro_frame(slot: int, stop_mode, repeats, script: str) -> bytes:
    """One 512-byte macro: header (AA 55, CRC, count, slot, stop mode, repeats) + 4-byte actions."""
    actions = [_macro_action(n, v) for n, v in parse_macro_script(script) + [("Delay", "5")]]
    frame = bytearray(MACRO_LEN)
    for i, fields in enumerate(actions):
        for j, value in enumerate(fields):
            if value:                                   # the app skips falsy fields
                off = 8 + 4 * i + j
                if off >= MACRO_LEN:
                    raise ValueError("macro has too many steps")
                frame[off] = _u8(value)
    crc = p.crc16(frame[8:8 + len(actions) * 4])
    struct.pack_into("<HHBBBB", frame, 0, 0x55AA, crc, _u8(len(actions)), _u8(slot), _u8(stop_mode), _u8(repeats))
    return bytes(frame)


def macro_data(profile: dict, load_macro: Callable[[str], str | None]) -> tuple[bytes, bytes]:
    """(macro frames, 256-byte slot index by matrix index; FF = none). Main and Fn keys share one index."""
    guids, frames, index = [], [], bytearray(b"\xff" * 256)
    for key in (profile.get("KeySet") or []) + (profile.get("FnKeySet") or []):
        task = key.get("Task")
        if not task or task.get("Type") != "Macro":
            continue
        data = task.get("Data") or {}
        guid = data.get("GUID")
        idx = _index(key.get("Index"), 256)
        if idx is None:
            raise ValueError(f"bad key index {key.get('Index')!r}")
        if guid in guids:
            index[idx] = guids.index(guid)
            continue
        guids.append(guid)
        index[idx] = len(guids) - 1
        script = load_macro(guid)
        if script is None:
            raise ValueError(f"macro {guid} not found")   # the app aborts the whole write here
        frames.append(macro_frame(len(guids) - 1, data.get("StopMode"), data.get("Repeats"), script))
    return b"".join(frames), bytes(index)


def _effect_entries(profile: dict) -> tuple[list[tuple], object, bytearray]:
    """(effects as (GUID, color overrides), static colors for a GUID-less ModeLE, 128-byte press-light index)."""
    entries, static, index = [], None, bytearray(b"\xff" * 128)
    mode_le, keyset = profile.get("ModeLE"), profile.get("KeySet")
    if mode_le and isinstance(mode_le.get("GUID"), str) and isinstance(keyset, list):
        if mode_le["GUID"]:
            entries.append((mode_le["GUID"], (mode_le.get("Params") or {}).get("LEConfigs")))
        else:
            entries.append((None, None))                  # the app's 'invailed' marker: static colors
            static = mode_le.get("LEData")
        for key in keyset:
            key_le = key.get("KeyLE") or {}
            if not key_le.get("GUID"):
                continue
            entry = (key_le["GUID"], (key_le.get("Params") or {}).get("LEConfig"))   # sic: singular
            if entry not in entries:
                entries.append(entry)
            idx = _index(key.get("Index"), 128)
            if idx is None:
                raise ValueError(f"bad key index {key.get('Index')!r}")
            index[idx] = _u8(entries.index(entry))
    elif isinstance(profile.get("DriverLE"), list):
        for le in profile["DriverLE"]:
            if le.get("GUID"):
                entry = (le["GUID"], le.get("LEConfigs"))
                if entry not in entries:
                    entries.append(entry)
    return entries, static, index


def _bitmap(leds) -> bytearray:
    """22-byte LED bitmap. Like the app: LEDs ≥ 176 are dropped, fractional ones count as their floor."""
    bits = bytearray(22)
    for led in leds:
        if led is None or math.isnan(led) or led < 0:
            continue
        led = math.floor(led)
        if led < LED_COUNT:
            bits[led // 8] |= 1 << (led % 8)
    return bits


def _per_count(total: int, count: float) -> int:
    """Math.floor(total / Count) as the app writes it: NaN → 0, Count 0 → error."""
    if math.isnan(count):
        return 0
    if count == 0:
        raise ValueError("lighting effect has Count 0")
    return _u16(math.floor(total / count))


def _effect_block(effect: dict, frame_address: int) -> tuple[tuple, bytes]:
    """One effect → (header fields, frames + logic block)."""
    frames = []
    for frame in effect["Frames"]:
        count = frame.get("Count")
        integral = isinstance(count, (int, float)) and not isinstance(count, bool) and float(count).is_integer()
        frames += [frame] * (int(count) if integral else 1)
    out = bytearray()
    for frame in frames:
        out += struct.pack("<HH", 3, 22) + _bitmap(js_parse_int(k, 10) for k in (frame.get("Data") or {}))
    logic_address = frame_address + 26 * len(frames)
    for cfg in effect["LEConfigs"]:
        bits = _bitmap(js_number(k) for k in cfg.get("Keys", []))
        v = _hex32(cfg.get("Color"))
        typ, count = js_number(cfg.get("Type")), js_number(cfg.get("Count"))
        data0 = data1 = 0
        if typ == 1:
            data0 = _per_count(360, count)
        elif typ == 2:
            stay = js_number(cfg.get("StayCount"))
            data1 = 0 if math.isnan(stay) else _u16(stay)
            data0 = _per_count(100, count)
        out += struct.pack("<BB", int(typ) if typ in (1, 2) else 0, 32) + bits \
            + bytes([(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF, 0]) + struct.pack("<HH", data0, data1)
    return (frame_address, len(frames), logic_address, len(effect["LEConfigs"])), bytes(out)


def light_data(profile: dict, load_effect: Callable[[str], str | None]) -> tuple[bytes, bytes | None]:
    """(128-byte press-light index, lighting data or None)."""
    entries, static, index = _effect_entries(profile)
    headers, blocks, address = [], [], LIGHT_HEADER_LEN
    for guid, overrides in entries:
        if guid is None:
            block = bytearray(4 + LED_COUNT * 4)
            struct.pack_into("<HH", block, 0, 0, LED_COUNT * 4)
            block[4:] = color_block(static)
            headers.append((address, 1, 0, 0))
            blocks.append(bytes(block))
            address += len(block)
            continue
        text = load_effect(guid)
        try:
            effect = json.loads(text)
        except (TypeError, ValueError):
            continue                                       # the app skips effects it can't load
        if overrides and len(effect["LEConfigs"]) == len(overrides):
            for cfg, o in zip(effect["LEConfigs"], overrides):
                cfg["Color"] = o.get("Color")
        header, block = _effect_block(effect, address)
        headers.append(header)
        blocks.append(block)
        address = header[2] + 32 * header[3]
    if not headers or sum(map(len, blocks)) > LIGHT_MAX - LIGHT_HEADER_LEN:
        return bytes(index), None
    data = bytearray(b"\xff" * (LIGHT_HEADER_LEN + sum(map(len, blocks))))
    pos = LIGHT_HEADER_LEN
    for block in blocks:
        data[pos:pos + len(block)] = block
        pos += len(block)
    for i, header in enumerate(headers):
        if i * 16 + 16 <= len(data):
            data[i * 16:i * 16 + 16] = struct.pack("<4I", *header)
    return bytes(index), bytes(data)


# --- Whole profile -----------------------------------------------------------------------------

@dataclass
class ProfileData:
    mode: int
    matrix: tuple[int, int]
    keys: bytes | None          # None: not written (no KeySet)
    fn_keys: bytes | None
    colors: bytes | None        # per-key static colors (LEData)
    macros: bytes
    light_keys: bytes
    light: bytes | None


def build(profile: dict, matrix: tuple[int, int], load_effect, load_macro) -> ProfileData:
    cols, rows = matrix
    size = cols * rows * 4
    macros, macro_index = macro_data(profile, load_macro)
    light_keys, light = light_data(profile, load_effect)
    keyset, fn_keyset = profile.get("KeySet"), profile.get("FnKeySet")
    return ProfileData(
        mode=_u8(profile.get("ModeIndex")),
        matrix=matrix,
        keys=key_table(keyset, size, macro_index) if isinstance(keyset, list) else None,
        fn_keys=key_table(fn_keyset, size, None) if isinstance(fn_keyset, list) else None,
        colors=color_block(profile["LEData"]) if isinstance(profile.get("LEData"), (dict, list)) or
        ("LEData" in profile and profile["LEData"] is None) else None,
        macros=macros,
        light_keys=light_keys,
        light=light,
    )


def packets(data: ProfileData) -> list[bytes]:
    """The writes, in the app's order (after its `01 09` matrix query). Ends by switching to the profile."""
    m = data.mode
    out = []
    if data.keys is not None:
        out += [p.clear(m, p.DATA_KEYS)] + p.chunks(p.OP_KEYS, m, data.keys)
    if data.fn_keys is not None:
        out += [p.clear(m, p.DATA_FN_KEYS)] + p.chunks(p.OP_FN_KEYS, m, data.fn_keys)
    if data.colors is not None:
        out += [p.clear(m, p.DATA_LEDATA)] + p.chunks(p.OP_LEDATA, m, data.colors)
    out += [p.clear(m, p.DATA_MACROS)] + p.chunks(p.OP_MACROS, m, data.macros)
    out.append(p.clear(m, p.DATA_LIGHT_KEYS))
    n = data.matrix[0] * data.matrix[1]
    for addr in range(0, n, p.PAYLOAD_LEN):
        part = data.light_keys[addr:min(addr + p.PAYLOAD_LEN, n)]
        out.append(p.packet(p.OP_LIGHT_KEYS, m, struct.pack("<I", (len(part) << 16) + addr), part))
    out.append(p.clear(m, p.DATA_LIGHT_DATA))
    if data.light is not None:
        out += p.chunks(p.OP_LIGHT_DATA, m, data.light)
    if m != p.MODE_STANDARD:
        out.append(p.set_mode(m))
    return out
