"""Names for key-binding "driver values" (docs/PROTOCOL.md, Key table).

    keyboard key   0x0200KKMM   KK = HID keyboard usage, MM = modifier bits
    mouse button   0x010100BB   BB = button bit
    media key      0x0300UUUU   UUUU = HID consumer usage

`parse("ctrl+c")` → 0x02000601; also accepts raw hex ("0x02001400").
"""
import re

MODIFIERS = {"lctrl": 0x01, "ctrl": 0x01, "lshift": 0x02, "shift": 0x02, "lalt": 0x04, "alt": 0x04,
             "lwin": 0x08, "win": 0x08, "super": 0x08, "rctrl": 0x10, "rshift": 0x20, "ralt": 0x40, "altgr": 0x40,
             "rwin": 0x80}

KEYS = {
    **{chr(ord("a") + i): 0x04 + i for i in range(26)},
    **{str(d): 0x1E + d - 1 for d in range(1, 10)}, "0": 0x27,
    "enter": 0x28, "return": 0x28, "esc": 0x29, "escape": 0x29, "backspace": 0x2A, "tab": 0x2B, "space": 0x2C,
    "minus": 0x2D, "-": 0x2D, "equal": 0x2E, "=": 0x2E, "[": 0x2F, "]": 0x30, "backslash": 0x31, "\\": 0x31,
    "semicolon": 0x33, ";": 0x33, "quote": 0x34, "'": 0x34, "grave": 0x35, "`": 0x35, "comma": 0x36, ",": 0x36,
    "period": 0x37, ".": 0x37, "slash": 0x38, "/": 0x38, "capslock": 0x39,
    **{f"f{n}": 0x3A + n - 1 for n in range(1, 13)},
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48, "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
    "delete": 0x4C, "end": 0x4D, "pagedown": 0x4E, "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "numlock": 0x53, "kp/": 0x54, "kp*": 0x55, "kp-": 0x56, "kp+": 0x57, "kpenter": 0x58,
    **{f"kp{d}": 0x59 + d - 1 for d in range(1, 10)}, "kp0": 0x62, "kp.": 0x63,
    "iso\\": 0x64, "menu": 0x65, "app": 0x65,
    **{f"f{n}": 0x68 + n - 13 for n in range(13, 25)},
}

MEDIA = {"mute": 0x00E2, "volumeup": 0x00E9, "volumedown": 0x00EA, "playpause": 0x00CD, "stop": 0x00B7,
         "next": 0x00B5, "previous": 0x00B6, "mediaplayer": 0x0183, "mail": 0x018A, "calculator": 0x0192,
         "mycomputer": 0x0194, "browser": 0x0223, "websearch": 0x0221}

MOUSE = {"mouseleft": 0x01, "mouseright": 0x02, "mousemiddle": 0x04, "mouseback": 0x08, "mouseforward": 0x10}

DISABLED = 0x02000000


def parse(text: str) -> int:
    """A binding: raw hex, "disabled", a key with optional modifiers ("ctrl+shift+t", "ctrl"), a media key, a mouse
    button."""
    t = text.strip().lower().replace(" ", "")
    if re.fullmatch(r"0x[0-9a-f]{1,8}", t):
        return int(t, 16)
    if t in ("disabled", "none", "off"):
        return DISABLED
    if t in MEDIA:
        return 0x03000000 | MEDIA[t]
    if t in MOUSE:
        return 0x01010000 | MOUSE[t]
    parts = t.split("+") if t != "+" else ["+"]
    mods, key = 0, 0
    for part in parts:
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif part in KEYS and not key:
            key = KEYS[part]
        else:
            raise ValueError(f"unknown key {part!r} in {text!r}")
    return 0x02000000 | key << 8 | mods
