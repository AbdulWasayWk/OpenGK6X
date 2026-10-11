"""What a key can do: the 32-bit "driver values" the keyboard stores per key (docs/PROTOCOL.md, Key table).

    keyboard key / combo  0x0200KKMM   KK = HID keyboard usage, MM = modifier bits
    mouse button          0x010100BB   BB = button bit
    media / app key       0x0300UUUU   UUUU = HID consumer usage
    lighting control      0x09XX000Y
    switch profile        0x0A07000N   N = 1 standard, 2-4 profiles 1-3
    Space, hold = mod     0x0A0C00MM   tap = Space, hold = modifiers MM
    macro                 0x0A0100SS   SS = macro slot (filled in when the profile is written)
    sleep                 0x0C000002

Every binding has a short text form used in profiles and on the command line: "a", "ctrl+c", "volume_up",
"mouse_left", "profile_2", "space_hold_lctrl", "disabled", or raw hex "0x02001400". `parse()` reads it,
`name()` writes it, `label()` gives a display name.
"""
import re
from dataclasses import dataclass

DISABLED = 0x02000000
MACRO = 0x0A010001

MODIFIERS = [("lctrl", "Left Ctrl"), ("lshift", "Left Shift"), ("lalt", "Left Alt"), ("lwin", "Left Super"),
             ("rctrl", "Right Ctrl"), ("rshift", "Right Shift"), ("ralt", "Right Alt"), ("rwin", "Right Super")]
MODIFIER_BITS = {n: 1 << i for i, (n, _) in enumerate(MODIFIERS)}
MODIFIER_ALIASES = {"ctrl": "lctrl", "control": "lctrl", "shift": "lshift", "alt": "lalt", "win": "lwin",
                    "super": "lwin", "meta": "lwin", "gui": "lwin", "altgr": "ralt", "rsuper": "rwin"}
_MOD_SHORT = {"lctrl": "Ctrl", "lshift": "Shift", "lalt": "Alt", "lwin": "Super",
              "rctrl": "RCtrl", "rshift": "RShift", "ralt": "AltGr", "rwin": "RSuper"}

# HID keyboard usages (USB HID Usage Tables, page 0x07): name, label
KEYS: dict[int, tuple[str, str]] = {
    **{0x04 + i: (chr(97 + i), chr(65 + i)) for i in range(26)},
    **{0x1E + i: (str((i + 1) % 10), str((i + 1) % 10)) for i in range(10)},
    0x28: ("enter", "Enter"), 0x29: ("esc", "Esc"), 0x2A: ("backspace", "Backspace"), 0x2B: ("tab", "Tab"),
    0x2C: ("space", "Space"), 0x2D: ("minus", "-"), 0x2E: ("equal", "="), 0x2F: ("leftbracket", "["),
    0x30: ("rightbracket", "]"), 0x31: ("backslash", "\\"), 0x32: ("nonus_hash", "# (ISO)"),
    0x33: ("semicolon", ";"), 0x34: ("quote", "'"), 0x35: ("grave", "`"), 0x36: ("comma", ","),
    0x37: ("period", "."), 0x38: ("slash", "/"), 0x39: ("capslock", "Caps Lock"),
    **{0x3A + i: (f"f{i + 1}", f"F{i + 1}") for i in range(12)},
    0x46: ("printscreen", "Print Screen"), 0x47: ("scrolllock", "Scroll Lock"), 0x48: ("pause", "Pause"),
    0x49: ("insert", "Insert"), 0x4A: ("home", "Home"), 0x4B: ("pageup", "Page Up"), 0x4C: ("delete", "Delete"),
    0x4D: ("end", "End"), 0x4E: ("pagedown", "Page Down"), 0x4F: ("right", "→"), 0x50: ("left", "←"),
    0x51: ("down", "↓"), 0x52: ("up", "↑"), 0x53: ("numlock", "Num Lock"), 0x54: ("kp_divide", "Num /"),
    0x55: ("kp_multiply", "Num *"), 0x56: ("kp_minus", "Num -"), 0x57: ("kp_plus", "Num +"),
    0x58: ("kp_enter", "Num Enter"), **{0x59 + i: (f"kp_{i + 1}", f"Num {i + 1}") for i in range(9)},
    0x62: ("kp_0", "Num 0"), 0x63: ("kp_period", "Num ."), 0x64: ("nonus_backslash", "\\ (ISO)"),
    0x65: ("menu", "Menu"), 0x67: ("kp_equal", "Num ="),
    **{0x68 + i: (f"f{i + 13}", f"F{i + 13}") for i in range(12)},
    0x85: ("kp_comma", "Num ,"), 0x87: ("intl_ro", "Ro"), 0x88: ("intl_kana", "Kana"), 0x89: ("intl_yen", "¥"),
    0x8A: ("intl_henkan", "Henkan"), 0x8B: ("intl_muhenkan", "Muhenkan"), 0x90: ("lang_hangul", "Han/Eng"),
    0x91: ("lang_hanja", "Hanja"),
}
KEY_ALIASES = {"return": "enter", "escape": "esc", "-": "minus", "=": "equal", "[": "leftbracket",
               "]": "rightbracket", "\\": "backslash", ";": "semicolon", "'": "quote", "`": "grave", ",": "comma",
               ".": "period", "/": "slash", "caps": "capslock", "prtsc": "printscreen", "ins": "insert",
               "del": "delete", "pgup": "pageup", "pgdn": "pagedown", "app": "menu", "apps": "menu"}

MEDIA: dict[int, tuple[str, str]] = {
    0x00B5: ("next_track", "Next Track"), 0x00B6: ("previous_track", "Previous Track"), 0x00B7: ("stop", "Stop"),
    0x00CC: ("eject", "Eject"), 0x00CD: ("play_pause", "Play/Pause"), 0x00E2: ("mute", "Mute"),
    0x00E9: ("volume_up", "Volume Up"), 0x00EA: ("volume_down", "Volume Down"),
    0x0183: ("media_player", "Media Player"), 0x018A: ("email", "Email"), 0x0192: ("calculator", "Calculator"),
    0x0194: ("file_manager", "My Computer"), 0x0221: ("web_search", "Web Search"),
    0x0223: ("web_home", "Web Home"), 0x0224: ("web_back", "Web Back"), 0x0225: ("web_forward", "Web Forward"),
    0x0226: ("web_stop", "Web Stop"), 0x0227: ("web_refresh", "Web Refresh"),
    0x022A: ("web_favorites", "Web Favorites"),
}
MOUSE: dict[int, tuple[str, str]] = {0x01: ("mouse_left", "Left Click"), 0x02: ("mouse_right", "Right Click"),
                                     0x04: ("mouse_middle", "Middle Click"), 0x08: ("mouse_back", "Mouse Back"),
                                     0x10: ("mouse_forward", "Mouse Forward")}
SPECIAL: dict[int, tuple[str, str, str]] = {
    0x09010010: ("toggle_custom_lighting", "Switch custom lighting", "Lighting"),
    0x09010011: ("toggle_key_lighting", "Switch key-press lighting", "Lighting"),
    0x09020001: ("brightness_up", "Brightness +", "Lighting"),
    0x09020002: ("brightness_down", "Brightness −", "Lighting"),
    0x09030001: ("effect_faster", "Effect speed +", "Lighting"),
    0x09030002: ("effect_slower", "Effect speed −", "Lighting"),
    0x09060001: ("lighting_pause", "Pause lighting", "Lighting"),
    0x09060002: ("lighting_toggle", "Lighting on/off", "Lighting"),
    0x0A070001: ("profile_standard", "Switch to standard profile", "Profiles"),
    0x0A070002: ("profile_1", "Switch to profile 1", "Profiles"),
    0x0A070003: ("profile_2", "Switch to profile 2", "Profiles"),
    0x0A070004: ("profile_3", "Switch to profile 3", "Profiles"),
    0x0C000002: ("sleep", "Sleep", "System"),
}


@dataclass(frozen=True)
class Action:
    value: int
    name: str
    label: str
    category: str


def _space_hold_name(mods: int) -> str:
    return "space_hold_" + "_".join(n for n, _ in MODIFIERS if mods & MODIFIER_BITS[n])


def catalog() -> list[Action]:
    """Every action the official app offers, grouped for a picker (combos and macros are built separately)."""
    out = [Action(DISABLED, "disabled", "Disabled (does nothing)", "Basic")]
    out += [Action(0x02000000 | u << 8, n, lbl, "Keys") for u, (n, lbl) in KEYS.items()]
    out += [Action(0x02000000 | MODIFIER_BITS[n], n, lbl, "Modifiers") for n, lbl in MODIFIERS]
    out += [Action(0x02000601, "ctrl+c", "Copy (Ctrl+C)", "Shortcuts"),
            Action(0x02001901, "ctrl+v", "Paste (Ctrl+V)", "Shortcuts"),
            Action(0x02001B01, "ctrl+x", "Cut (Ctrl+X)", "Shortcuts"),
            Action(0x02001D01, "ctrl+z", "Undo (Ctrl+Z)", "Shortcuts")]
    out += [Action(0x03000000 | u, n, lbl, "Media") for u, (n, lbl) in MEDIA.items()]
    out += [Action(0x01010000 | b, n, lbl, "Mouse") for b, (n, lbl) in MOUSE.items()]
    out += [Action(v, n, lbl, cat) for v, (n, lbl, cat) in SPECIAL.items()]
    for side in (0, 4):                                  # left-hand or right-hand modifier sets, as the app offers
        for combo in range(1, 16):
            mods = combo << side
            names = [_MOD_SHORT[n] for n, _ in MODIFIERS if mods & MODIFIER_BITS[n]]
            out.append(Action(0x0A0C0000 | mods, _space_hold_name(mods),
                              f"Space, hold for {'+'.join(names)}", "Space dual-role"))
    return out


_BY_NAME = {a.name: a for a in catalog()}
_BY_VALUE = {}
for _a in catalog():
    _BY_VALUE.setdefault(_a.value, _a)


def _key_usage(name: str) -> int | None:
    name = KEY_ALIASES.get(name, name)
    return next((u for u, (n, _) in KEYS.items() if n == name), None)


def parse(text: str) -> int:
    """Text form → driver value. Accepts catalog names, key combos ("ctrl+shift+t", "ctrl"), raw hex."""
    t = text.strip().lower().replace(" ", "")
    if re.fullmatch(r"0x[0-9a-f]{1,8}", t):
        return int(t, 16)
    if t in ("none", "off"):
        return DISABLED
    if t in _BY_NAME and "+" not in t:
        return _BY_NAME[t].value
    mods, key = 0, None
    for part in (t.split("+") if t != "+" else ["+"]):
        mod = MODIFIER_ALIASES.get(part, part)
        if mod in MODIFIER_BITS:
            mods |= MODIFIER_BITS[mod]
            continue
        usage = _key_usage(part)
        if usage is None or key is not None:
            raise ValueError(f"unknown binding {text!r} (see `opengk6x actions`)")
        key = usage
    return 0x02000000 | (key or 0) << 8 | mods


def name(value: int) -> str:
    """Driver value → text form (round-trips through parse)."""
    if value != MACRO and value in _BY_VALUE:
        return _BY_VALUE[value].name
    if value >> 16 == 0x0200:
        usage, mods = value >> 8 & 0xFF, value & 0xFF
        parts = [n for n, _ in MODIFIERS if mods & MODIFIER_BITS[n]]
        if usage in KEYS:
            parts.append(KEYS[usage][0])
        elif usage:
            return f"0x{value:08x}"
        return "+".join(parts) or "disabled"
    return f"0x{value:08x}"


def label(value: int) -> str:
    """Driver value → display name ("Ctrl+C", "Volume Up", …)."""
    if value != MACRO and value in _BY_VALUE:
        return _BY_VALUE[value].label
    if value >> 16 == 0x0200:
        usage, mods = value >> 8 & 0xFF, value & 0xFF
        parts = [_MOD_SHORT[n] for n, _ in MODIFIERS if mods & MODIFIER_BITS[n]]
        if usage in KEYS:
            parts.append(KEYS[usage][1])
        elif usage:
            parts.append(f"Key 0x{usage:02X}")
        return "+".join(parts)
    if value >> 16 == 0x0A01:
        return "Macro"
    return f"0x{value:08X}"

