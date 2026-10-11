"""Macros: our step format, the keyboard's 4-byte actions, and the official app's `.cms` script text.

Steps (JSON): {"key": "a", "action": "down"|"up"}, {"mouse": "left"|"right", "action": "down"|"up"},
{"delay": 50} (ms). Keys are binding names (bindings.KEYS) or modifiers ("lctrl", "rshift", …).

Compact text (CLI): "+ctrl c -ctrl 100ms enter click:left" = press ctrl, tap c, release ctrl, wait 100 ms,
tap enter, click the left button. `+x` press, `-x` release, `x` tap, `Nms` wait, `click:b` / `+click:b` / `-click:b`,
and `ctrl+v` = hold ctrl, tap v, release ctrl.
"""
import re
from dataclasses import dataclass, field

from . import bindings as b
from .profile import MACRO_KEY_CODES, MACRO_MODIFIERS, parse_macro_script

REPEAT_MODES = {"times": 1, "while_held": 2, "toggle": 3}     # official StopMode values
MOUSE_BUTTONS = {"left": 1, "right": 2}                        # what the firmware's mouse action takes (app)
MAX_ACTIONS = 125                                              # 126 slots, minus the trailing Delay 5 the app adds

_MOD_TO_SCRIPT = {bit: name for name, bit in MACRO_MODIFIERS.items()}
_USAGE_TO_SCRIPT = {}
for _n, _u in MACRO_KEY_CODES.items():
    _USAGE_TO_SCRIPT.setdefault(_u, _n)


@dataclass
class Macro:
    name: str
    steps: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"steps": self.steps}

    @classmethod
    def from_json(cls, name: str, data: dict) -> "Macro":
        steps = data.get("steps", [])
        for s in steps:
            validate_step(s)
        return cls(name, steps)


def validate_step(step: dict):
    if "delay" in step:
        if not (isinstance(step["delay"], int) and 0 <= step["delay"] <= 0xFFFF):
            raise ValueError(f"delay must be 0-65535 ms: {step}")
        return
    if step.get("action") not in ("down", "up"):
        raise ValueError(f"step needs action down/up: {step}")
    if "mouse" in step:
        if step["mouse"] not in MOUSE_BUTTONS:
            raise ValueError(f"mouse button must be left or right: {step}")
        return
    key = step.get("key", "")
    if key not in b.MODIFIER_BITS:
        value = b.parse(key)
        if value >> 16 != 0x0200 or value & 0xFF or not value >> 8 & 0xFF:
            raise ValueError(f"not a single key: {step}")


def to_actions(steps: list[dict]) -> list[tuple]:
    """Steps → (data0, data1, status, type) actions as the firmware stores them (docs/PROTOCOL.md, Macros)."""
    if len(steps) > MAX_ACTIONS:
        raise ValueError(f"macro has {len(steps)} steps; the keyboard holds at most {MAX_ACTIONS}")
    out = []
    for s in steps:
        validate_step(s)
        if "delay" in s:
            out.append((s["delay"] % 256, s["delay"] // 256, 0, 3))
            continue
        status = 1 if s["action"] == "down" else 2
        if "mouse" in s:
            out.append((MOUSE_BUTTONS[s["mouse"]], 0, status, 2))
        elif s["key"] in b.MODIFIER_BITS:
            out.append((0, b.MODIFIER_BITS[s["key"]], status, 1))
        else:
            out.append((b.parse(s["key"]) >> 8 & 0xFF, 0, status, 1))
    return out


def parse_text(text: str) -> list[dict]:
    """Compact text → steps (see module doc)."""
    steps = []
    for tok in text.split():
        t = tok.lower()
        if m := re.fullmatch(r"(\d+)ms", t):
            steps.append({"delay": int(m.group(1))})
            continue
        prefix = t[0] if t[0] in "+-" and len(t) > 1 else ""
        body = t[len(prefix):]
        actions = {"+": ["down"], "-": ["up"], "": ["down", "up"]}[prefix]
        if body.startswith("click:"):
            target = {"mouse": body[6:]}
        elif "+" in body and len(body) > 1:
            if prefix:
                raise ValueError(f"{tok}: a shortcut can only be tapped (write it without + or -)")
            value = b.parse(body)
            if value >> 16 != 0x0200:
                raise ValueError(f"{tok} isn't a key combination")
            mods = [n for n, _ in b.MODIFIERS if value & b.MODIFIER_BITS[n]]
            usage = value >> 8 & 0xFF
            steps += [{"key": m, "action": "down"} for m in mods]
            if usage:
                steps += [{"key": b.KEYS[usage][0], "action": a} for a in ("down", "up")]
            steps += [{"key": m, "action": "up"} for m in reversed(mods)]
            continue
        else:
            target = {"key": b.MODIFIER_ALIASES.get(body, body)}
            if target["key"] not in b.MODIFIER_BITS:
                b.parse(target["key"])                   # raises on unknown keys
                target["key"] = b.name(b.parse(target["key"]))
        for a in actions:
            steps.append({**target, "action": a})
    for s in steps:
        validate_step(s)
    return steps


def to_text(steps: list[dict]) -> str:
    """Steps → compact text (a press directly followed by its release becomes a tap)."""
    out, i = [], 0
    while i < len(steps):
        s = steps[i]
        if "delay" in s:
            out.append(f"{s['delay']}ms")
            i += 1
            continue
        what = b.FRIENDLY.get(s.get("key"), s.get("key")) or f"click:{s['mouse']}"
        nxt = steps[i + 1] if i + 1 < len(steps) else {}
        if s["action"] == "down" and nxt.get("action") == "up" and nxt.get("key") == s.get("key") \
                and nxt.get("mouse") == s.get("mouse"):
            out.append(what)
            i += 2
            continue
        out.append(("+" if s["action"] == "down" else "-") + what)
        i += 1
    return " ".join(out)


# --- Official .cms scripts ----------------------------------------------------------------------

def from_script(text: str) -> list[dict]:
    """Official macro script → steps. Unsupported lines (Wheel, middle button, unknown keys) are dropped."""
    steps = []
    for name, value in parse_macro_script(text):
        if name == "Delay":
            if value.strip().isdigit():
                steps.append({"delay": min(int(value), 0xFFFF)})
        elif value == "":
            button = "left" if "Left" in name else "right" if "Right" in name else None
            action = "down" if "Down" in name else "up" if "Up" in name else None
            if button and action:
                steps.append({"mouse": button, "action": action})
        elif name in ("KeyDown", "KeyUp"):
            action = "down" if name == "KeyDown" else "up"
            if value in MACRO_MODIFIERS:
                mod = next(n for n, bit in b.MODIFIER_BITS.items() if bit == MACRO_MODIFIERS[value])
                steps.append({"key": mod, "action": action})
            elif value in MACRO_KEY_CODES:
                usage = MACRO_KEY_CODES[value]
                if 0xE0 <= usage <= 0xE7:            # "Ctrl"/"Shift"/"Alt" as keys: same as the left modifiers
                    steps.append({"key": ["lctrl", "lshift", "lalt", "lwin", "rctrl", "rshift", "ralt",
                                          "rwin"][usage - 0xE0], "action": action})
                else:
                    steps.append({"key": b.KEYS[usage][0], "action": action})
    return steps


def to_script(name: str, guid: str, steps: list[dict]) -> str:
    """Steps → official macro script. Keys the official format can't name raise ValueError."""
    lines = ["[General]", f"Name={name}", f"ScriptID={guid}", "Repeats=1", "StopMode=1", "", "[Script]"]
    for s in steps:
        if "delay" in s:
            lines.append(f"Delay {s['delay']}")
        elif "mouse" in s:
            lines.append(f"{s['mouse'].capitalize()}{s['action'].capitalize()}")
        else:
            verb = "KeyDown" if s["action"] == "down" else "KeyUp"
            if s["key"] in b.MODIFIER_BITS:
                lines.append(f"{verb} {_MOD_TO_SCRIPT[b.MODIFIER_BITS[s['key']]]}")
            else:
                usage = b.parse(s["key"]) >> 8 & 0xFF
                if usage not in _USAGE_TO_SCRIPT:
                    raise ValueError(f"the official app can't store key {s['key']!r} in a macro")
                lines.append(f"{verb} {_USAGE_TO_SCRIPT[usage]}")
    return "\r\n".join(lines) + "\r\n"
