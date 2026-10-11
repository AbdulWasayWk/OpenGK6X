"""Live mode: what the PC does while the keyboard is in online mode (online.py does the talking).

    ~/.config/opengk6x/<model>/live.json
    {"effect": GUID | null,            lighting effect (library or yours); null = dark (typing effects only)
     "speed": 1.0, "brightness": 100,  effect speed factor, brightness %
     "typing": {"kind": "off" | "glow" | "ripple", "color": "0xRRGGBB", "duration": ms},
     "actions": {"<key name>": {"type": "command" | "url" | "text" | "macro", "value": "..."}},
     "exit": "standard" | "1" | "2" | "3"}      the profile the keyboard goes back to afterwards

Action keys don't type anything in live mode: their entry in the online key table becomes a "driver macro" value
(`0A0100xx`, xx = 1 + matrix index, as the official app writes them) and the PC acts on the key report.
"""
import json
import math
import time
from dataclasses import dataclass, field

from . import effects as fx
from . import protocol as p

ACTION_TYPES = {"command": "Run a command", "url": "Open a URL, file or folder", "text": "Type text",
                "macro": "Play a macro"}
TYPING_KINDS = {"off": "Off", "glow": "Pressed keys light up", "ripple": "Ripple from each key"}
EXIT_MODES = {"standard": p.MODE_STANDARD, "1": 2, "2": 3, "3": 4}


@dataclass
class LiveConfig:
    effect: str | None = None
    speed: float = 1.0
    brightness: int = 100
    typing: dict = field(default_factory=lambda: {"kind": "glow", "color": "0xffffff", "duration": 600})
    actions: dict = field(default_factory=dict)
    exit: str = "standard"

    @classmethod
    def load(cls, root, model: int) -> "LiveConfig":
        f = root / str(model) / "live.json"
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            return cls()
        c = cls()
        for k in ("effect", "speed", "brightness", "typing", "actions", "exit"):
            if k in data:
                setattr(c, k, data[k])
        return c

    def save(self, root, model: int):
        f = root / str(model) / "live.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(self.__dict__, ensure_ascii=False, indent=1))


def driver_key_value(index: int) -> int:
    """Online key-table value for a key the PC handles (doesn't type)."""
    return 0x0A010000 | ((1 + index) & 0xFF)


class Renderer:
    """Lighting frames for live mode: an effect underneath, typing effects on top."""

    def __init__(self, keys: list[dict], effect: dict | None, config: LiveConfig):
        self.keys = [k for k in keys if 0 <= k["LocationCode"] < p.LIVE_LEDS and k.get("Shape") != "knob"]
        self.led_of = {k["LogicCode"]: k["LocationCode"] for k in self.keys}
        self.center = {k["LocationCode"]: (k["Position"]["Left"] + k["Position"]["Width"] / 2,
                                           k["Position"]["Top"] + k["Position"]["Height"] / 2) for k in self.keys}
        self.config = config
        self.player = fx.Player(effect) if effect else None
        self._ticks = 0.0
        self._last = None
        self._base: dict = {}
        self.events: list[tuple[int, float]] = []          # (LED, time pressed)

    def press(self, index: int, now: float | None = None):
        led = self.led_of.get(index)
        if led is not None:
            self.events.append((led, time.monotonic() if now is None else now))

    def frame(self, now: float | None = None) -> dict[int, tuple[int, int, int]]:
        now = time.monotonic() if now is None else now
        if self.player:
            # the effect advances one tick per 50 ms × speed, however often frames are asked for
            if self._last is None:
                self._base = self.player.step()
            else:
                self._ticks += (now - self._last) * 1000 / fx.TICK_MS * max(0.05, float(self.config.speed))
                while self._ticks >= 1:
                    self._base = self.player.step()
                    self._ticks -= 1
            self._last = now
        out = {led: self._base.get(led, (0, 0, 0)) for led in self.center}
        self._typing(out, now)
        scale = max(0, min(100, int(self.config.brightness))) / 100
        return {led: tuple(round(c * scale) for c in rgb) for led, rgb in out.items()}

    def _typing(self, out: dict, now: float):
        t = self.config.typing or {}
        kind = t.get("kind", "off")
        duration = max(50, int(t.get("duration", 600))) / 1000
        self.events = [(led, t0) for led, t0 in self.events if now - t0 < duration * (3 if kind == "ripple" else 1)]
        if kind == "off" or not self.events:
            return
        color = fx.rgb_of(t.get("color", "0xffffff"))
        for led, t0 in self.events:
            age = now - t0
            if kind == "glow":
                _blend(out, led, color, 1 - age / duration)
            elif kind == "ripple":
                radius = age / duration * 180            # key-map pixels (a key is ~42)
                fade = 1 - age / (duration * 3)
                cx, cy = self.center[led]
                for other, (x, y) in self.center.items():
                    d = math.hypot(x - cx, y - cy)
                    a = max(0.0, 1 - abs(d - radius) / 30) * fade
                    if a > 0:
                        _blend(out, other, color, a)


def _blend(out: dict, led: int, color, a: float):
    """Fade the LED from what's under it towards `color` (a = 0..1)."""
    a = max(0.0, min(1.0, a))
    r, g, b = out.get(led, (0, 0, 0))
    out[led] = (round(r * (1 - a) + color[0] * a), round(g * (1 - a) + color[1] * a),
                round(b * (1 - a) + color[2] * a))


# --- Typing text and playing macros through the keyboard (15 02 key states) ---------------------

_SHIFTED = {'!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
            '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'", '~': '`', '<': ',', '>': '.',
            '?': '/'}
_PLAIN = {**{chr(97 + i): 0x04 + i for i in range(26)}, **{str((i + 1) % 10): 0x1E + i for i in range(10)},
          ' ': 0x2C, '\n': 0x28, '\t': 0x2B, '-': 0x2D, '=': 0x2E, '[': 0x2F, ']': 0x30, '\\': 0x31, ';': 0x33,
          "'": 0x34, '`': 0x35, ',': 0x36, '.': 0x37, '/': 0x38}
SHIFT = 0x02


def text_states(text: str) -> list[tuple[int, list[int]]]:
    """Text → key states (modifier bits, keys held) to send one after another (US layout); unknown chars skipped."""
    out = []
    for ch in text:
        if ch in _PLAIN:
            out.append((0, [_PLAIN[ch]]))
        elif ch.isalpha() and ch.lower() in _PLAIN:
            out.append((SHIFT, [_PLAIN[ch.lower()]]))
        elif ch in _SHIFTED:
            out.append((SHIFT, [_PLAIN[_SHIFTED[ch]]]))
        else:
            continue
        out.append((0, []))
    return out


def macro_states(steps: list[dict]) -> list[tuple[str, object]]:
    """Macro steps → ("keys", (mods, [keys])) / ("mouse", buttons) / ("wait", ms) events, tracking what's held."""
    from . import bindings as b
    mods, held, buttons, out = 0, [], 0, []
    for s in steps:
        if "delay" in s:
            out.append(("wait", s["delay"]))
            continue
        down = s["action"] == "down"
        if "mouse" in s:
            bit = {"left": 1, "right": 2}[s["mouse"]]
            buttons = buttons | bit if down else buttons & ~bit
            out.append(("mouse", buttons))
            continue
        if s["key"] in b.MODIFIER_BITS:
            bit = b.MODIFIER_BITS[s["key"]]
            mods = mods | bit if down else mods & ~bit
        else:
            usage = b.parse(s["key"]) >> 8 & 0xFF
            if down and usage not in held:
                held = (held + [usage])[-5:]
            elif not down:
                held = [u for u in held if u != usage]
        out.append(("keys", (mods, list(held))))
    return out


def key_state_packet(mods: int, keys: list[int]) -> bytes:
    return p.packet(p.OP_DRIVER_INPUT, 0x02, payload=bytes([mods] + keys[:5]))


def mouse_packet(buttons: int) -> bytes:
    return p.packet(p.OP_DRIVER_INPUT, 0x01, payload=bytes([buttons]))

