"""Lighting effects: playing them (for previews), making new ones, and the custom effects list (Fn + −).

An effect is the official app's JSON (what `.le` files hold and profile.py turns into keyboard data):

    {"GUID": "...", "Name": "...",
     "Frames":    [{"Count": n, "Data": {"<led>": "0xRRGGBB", ...}}, ...],     which LEDs are lit, n ticks each
     "LEConfigs": [{"Type": 0|1|2, "Count": n, "StayCount": n, "Color": "0xRRGGBB", "Keys": [led, ...]}, ...]}

LEDs are LED indexes (the key map's LocationCode, 0-175). Each tick shows one frame: its lit LEDs take the color
of the first LEConfig that lists them (else the frame's own color); unlit LEDs are dark. LEConfig types:
0 = fixed color; 1 = hue turns 360/Count degrees per tick; 2 = breathing: fades in over Count ticks, holds
StayCount ticks, fades out, stays dark StayCount ticks. The official app plays a tick every 50 ms
(src/libs/cmleplayer.js); the keyboard's speed setting (Fn + ← / →) changes its own rate.

Effects made here also carry {"OpenGK6X": {"kind": ..., params}} so they can be edited again.
"""
import colorsys
import copy
import math
import uuid

from .profile import js_parse_int

TICK_MS = 50
LED_COUNT = 176
CUSTOM_SLOTS = 5              # the official app's standard profile has 5 custom effect slots


def rgb_of(text) -> tuple[int, int, int]:
    v = js_parse_int(text, 16) or 0
    return (v >> 16 & 0xFF, v >> 8 & 0xFF, v & 0xFF)


def hex_of(rgb) -> str:
    return "0x%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in rgb)


class Player:
    """Steps through an effect tick by tick, like the official app's player. `step()` → {led: (r, g, b)}."""

    def __init__(self, effect: dict):
        frames = []
        for f in effect.get("Frames") or []:
            count = f.get("Count")
            n = int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) and \
                float(count).is_integer() else 1
            frames += [f.get("Data") or {}] * max(0, n)
        self.frames = frames or [{}]
        self.index = 0
        self.configs = []
        for c in effect.get("LEConfigs") or []:
            leds = set()
            for k in c.get("Keys") or []:
                try:
                    leds.add(int(k))
                except (TypeError, ValueError):
                    pass
            typ = int(c.get("Type") or 0) if str(c.get("Type", "0")).lstrip("-").isdigit() else 0
            r, g, b = rgb_of(c.get("Color"))
            count = _num(c.get("Count"), 1) or 1
            state = {"type": typ, "leds": leds, "rgb": (r, g, b)}
            if typ == 1:
                state["hsv"] = list(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255))
                state["deg"] = 360 / count
            elif typ == 2:
                h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
                state.update(h=h, s=s, top=l, l=0.0, step=l / count, phase="up",
                             stay=int(_num(c.get("StayCount"), 0)), left=int(_num(c.get("StayCount"), 0)))
                state["rgb"] = (0, 0, 0)
            self.configs.append(state)

    def step(self) -> dict[int, tuple[int, int, int]]:
        data = self.frames[self.index % len(self.frames)]
        self.index += 1
        out = {}
        for key, color in data.items():
            try:
                led = int(key)
            except ValueError:
                continue
            cfg = next((c for c in self.configs if led in c["leds"]), None)
            out[led] = cfg["rgb"] if cfg else rgb_of(color)
        for c in self.configs:
            self._advance(c)
        return out

    @staticmethod
    def _advance(c):
        if c["type"] == 1:
            c["hsv"][0] = (c["hsv"][0] + c["deg"] / 360) % 1.0
            c["rgb"] = tuple(round(x * 255) for x in colorsys.hsv_to_rgb(*c["hsv"]))
        elif c["type"] == 2:
            if c["phase"] == "up":
                c["l"] = min(c["top"], c["l"] + c["step"])
                if c["l"] >= c["top"]:
                    c["phase"] = "hold" if c["stay"] else "down"
            elif c["phase"] == "hold":
                c["left"] -= 1
                if c["left"] <= 0:
                    c["phase"], c["left"] = "down", c["stay"]
            elif c["phase"] == "down":
                c["l"] = max(0.0, c["l"] - c["step"])
                if c["l"] <= 0:
                    c["phase"] = "dark" if c["stay"] else "up"
            else:
                c["left"] -= 1
                if c["left"] <= 0:
                    c["phase"], c["left"] = "up", c["stay"]
            c["rgb"] = tuple(round(x * 255) for x in colorsys.hls_to_rgb(c["h"], c["l"], c["s"]))


def _num(v, default):
    try:
        x = float(v)
        return default if math.isnan(x) else x
    except (TypeError, ValueError):
        return default


# --- Making effects ------------------------------------------------------------------------------

KINDS = {"solid": "One color", "keys": "Key colors (paint keys)", "breathing": "Breathing",
         "cycle": "Color cycle", "wave": "Rainbow wave", "sweep": "Sweep"}
DIRECTIONS = {"right": "Left → right", "left": "Right → left", "down": "Top → bottom", "up": "Bottom → top"}


def new_guid() -> str:
    return str(uuid.uuid4()).upper()


def _leds(keymap: list[dict], leds=None) -> list[dict]:
    """Keys with a real LED (LocationCode < 176; not knobs), optionally only the given LEDs."""
    keys = [k for k in keymap if 0 <= k["LocationCode"] < LED_COUNT and k.get("Shape") != "round"]
    return [k for k in keys if leds is None or k["LocationCode"] in leds]


def _position(k: dict, direction: str) -> float:
    p = k["Position"]
    x, y = p["Left"] + p["Width"] / 2, p["Top"] + p["Height"] / 2
    return {"right": x, "left": -x, "down": y, "up": -y}[direction]


def make(kind: str, params: dict, keymap: list[dict], name: str, guid: str | None = None) -> dict:
    """Build an effect. params by kind:
        solid:     color, leds (None = all)
        keys:      colors {led: "0xRRGGBB"}, background (color for the other keys, or None = dark)
        breathing: color, speed (ticks to fade in), hold (ticks), leds
        cycle:     color (start), speed (ticks per full turn), leds
        wave:      speed (ticks per full turn), direction, length (how many rainbows across), leds
        sweep:     color, speed (ticks per step), width (bands), direction, leds   (a band of light on dark keys)
    The keyboard stores only which LEDs each frame lights; colors come from the LEConfigs.
    """
    leds = params.get("leds")
    keys = _leds(keymap, set(leds) if leds is not None else None)
    all_leds = sorted(k["LocationCode"] for k in keys)
    frame = {str(n): "0xffffff" for n in all_leds}
    color = params.get("color", "0xff0000")
    configs, frames = [], [{"Count": 1, "Name": "frame0", "Data": frame}]
    if kind == "solid":
        configs = [{"Type": 0, "Count": 1, "Color": color, "Keys": all_leds}]
    elif kind == "keys":
        groups: dict[str, list[int]] = {}
        painted = {int(led): col.lower() for led, col in (params.get("colors") or {}).items()}
        background = params.get("background")
        if background:
            painted = {**{led: background.lower() for led in all_leds}, **painted}
        for led, col in painted.items():
            groups.setdefault(col, []).append(led)
        frame = {str(led): col for col, ls in groups.items() for led in ls}
        frames = [{"Count": 1, "Name": "frame0", "Data": frame}]
        configs = [{"Type": 0, "Count": 1, "Color": col, "Keys": sorted(ls)} for col, ls in groups.items()]
    elif kind == "breathing":
        configs = [{"Type": 2, "Count": int(params.get("speed", 20)), "StayCount": int(params.get("hold", 5)),
                    "Color": color, "Keys": all_leds}]
    elif kind == "cycle":
        configs = [{"Type": 1, "Count": int(params.get("speed", 120)), "Color": color, "Keys": all_leds}]
    elif kind == "wave":
        direction = params.get("direction", "right")
        bands = 16
        pos = {k["LocationCode"]: _position(k, direction) for k in keys}
        lo, hi = (min(pos.values()), max(pos.values())) if pos else (0, 1)
        span = (hi - lo) or 1
        length = float(params.get("length", 1.0)) or 1.0
        groups = {}
        for led, x in pos.items():
            band = min(bands - 1, int((x - lo) / span * bands))
            groups.setdefault(band, []).append(led)
        for band, ls in sorted(groups.items()):
            hue = (-band / bands * length) % 1.0          # earlier bands lead, so the colors travel forward
            configs.append({"Type": 1, "Count": int(params.get("speed", 120)),
                            "Color": hex_of(tuple(x * 255 for x in colorsys.hsv_to_rgb(hue, 1, 1))),
                            "Keys": sorted(ls)})
    elif kind == "sweep":
        direction = params.get("direction", "right")
        steps = 14
        pos = {k["LocationCode"]: _position(k, direction) for k in keys}
        lo, hi = (min(pos.values()), max(pos.values())) if pos else (0, 1)
        span = (hi - lo) or 1
        width = max(1, int(params.get("width", 2)))
        frames = []
        for s in range(steps + width):
            lit = [led for led, x in pos.items() if s - width < int((x - lo) / span * (steps - 1) + 0.5) <= s]
            frames.append({"Count": max(1, int(params.get("speed", 2))), "Name": f"frame{s}",
                           "Data": {str(led): color for led in lit}})
        configs = [{"Type": 0, "Count": 1, "Color": color, "Keys": all_leds}]
    else:
        raise ValueError(f"unknown effect kind {kind!r}")
    return {"GUID": guid or new_guid(), "Name": name, "Frames": frames, "LEConfigs": configs,
            "OpenGK6X": {"kind": kind, **copy.deepcopy(params)}}


# --- The custom effects list (standard profile, Fn + −) ---------------------------------------------

def standard_profile(effects: list[dict]) -> dict:
    """The official standard profile (ModeIndex 1) whose lighting data is the custom effects list."""
    return {"GUID": "", "ModeIndex": 1, "Name": "standard", "Active": 0,
            "DriverLE": [{"GUID": e["GUID"], "Name": e.get("Name", "")} for e in effects]}
