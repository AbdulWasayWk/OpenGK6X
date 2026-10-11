"""Physical layouts: which of a model's key-map entries are real keys on a given keyboard, and where.

The official key map for a model is a template covering several hardware variants (volume-knob positions, split
spacebar, navigation keys). A layout says which keys a keyboard really has, moves/renames some (the GK104 Pro's
knob sits where Print Screen / Scroll Lock / Pause are), and adds decorations (its screen).

A knob is three key-map entries (turn left, turn right, press), each bound like a key; the picture and the Keys
page show them as one knob.
"""
import copy
import re
from dataclasses import dataclass

from .vendordata import variant_names


@dataclass(frozen=True)
class Knob:
    name: str                                # shown in the picture and the editor ("Knob")
    left: str                                # key-map names of its three actions
    right: str
    press: str
    at: tuple[str, ...] = ()                 # keys whose area it takes (default: its own three entries)

    def parts(self) -> dict[str, str]:
        return {"left": self.left, "right": self.right, "press": self.press}


@dataclass(frozen=True)
class Layout:
    label: str
    hide: tuple[str, ...] = ()
    knobs: tuple[Knob, ...] = ()
    template_knobs: bool = False                               # every knob variant in the key map (find_knobs)
    screen_over: tuple[str, ...] = ()                          # keys whose area is a screen instead
    unsupported: frozenset[str] = frozenset()                  # binding categories the firmware ignores
    wireless_standard_only: bool = False                       # over 2.4 GHz / Bluetooth only the standard profile


NAV = ("Insert", "Home", "Page Up", "Delete", "End", "Page Down")

LAYOUTS = {
    "gk104pro": Layout(
        "Skyloong GK104 Pro (knob and screen)",
        hide=("Print Screen", "Scroll Lock", "Pause") + NAV,
        knobs=(Knob("Knob", left="Scroll Lock VOLU", right="Scroll Lock VOLD", press="Scroll Lock MUTE",
                    at=("Print Screen", "Scroll Lock", "Pause")),),     # tested 2026-10-11 (matrix 125, 126, 124)
        screen_over=NAV,
        unsupported=frozenset({"Space dual-role"}),      # tested 2026-10-11: long press just repeats Space
        wireless_standard_only=True),                    # tested 2026-10-11: profile 1 remaps not used on 2.4 GHz
    "full": Layout("Full-size, 104 keys"),
    "all": Layout("Every key in the template (knob positions, split spacebar)", template_knobs=True),
}
DEFAULT = {656802056: "gk104pro"}

KNOB_ROLES = {"left": "Turn left", "right": "Turn right", "press": "Press"}

# Actions suggested first for a knob (binding names); everything else is in the full list
KNOB_ACTIONS = [
    ("volume_down", "Volume down"), ("volume_up", "Volume up"), ("mute", "Mute"),
    ("brightness_down", "Brightness −"), ("brightness_up", "Brightness +"), ("lighting_toggle", "Lighting on/off"),
    ("lighting_pause", "Pause lighting"), ("effect_slower", "Effect speed −"), ("effect_faster", "Effect speed +"),
    ("previous_track", "Previous track"), ("next_track", "Next track"), ("play_pause", "Play / pause"),
    ("ctrl+minus", "Zoom out (Ctrl −)"), ("ctrl+equal", "Zoom in (Ctrl +)"), ("ctrl+0", "Reset zoom (Ctrl 0)"),
    ("left", "Arrow left"), ("right", "Arrow right"), ("up", "Arrow up"), ("down", "Arrow down"),
    ("pageup", "Page up"), ("pagedown", "Page down"),
    ("ctrl+shift+tab", "Previous tab"), ("ctrl+tab", "Next tab"),
    ("ctrl+z", "Undo"), ("ctrl+shift+z", "Redo"),
    ("mouse_middle", "Middle click"), ("enter", "Enter"), ("disabled", "Nothing"),
]


KNOB_VARIANT = re.compile(r"^(?P<key>.+?)\s*(?P<what>volu|volup|vold|voldown|mute)[\s*]*$", re.IGNORECASE)


def find_knobs(keymap: list[dict]) -> list[Knob]:
    """The template's knob variants: a key's VOLU/VOLD/MUTE (or VolUp/VolDown/Mute) entries, drawn above it with
    turn left on the left, turn right on the right and the press below (as on the GK104 Pro)."""
    by_name = {k["KeyName"]: k for k in keymap}
    groups: dict[str, dict[str, list[str]]] = {}
    for n in variant_names(keymap):
        m = KNOB_VARIANT.match(n)
        if m and m["key"].strip() in by_name:
            kind = "press" if m["what"].lower() == "mute" else "turn"
            groups.setdefault(m["key"].strip(), {}).setdefault(kind, []).append(n)
    out = []
    for key, g in groups.items():
        if len(g.get("press", ())) == 1 and len(g.get("turn", ())) == 2:
            left, right = sorted(g["turn"], key=lambda n: by_name[n]["Position"]["Left"])
            out.append(Knob(f"Knob ({key})", left, right, g["press"][0]))
    return sorted(out, key=lambda k: (by_name[k.press]["Position"]["Top"], by_name[k.press]["Position"]["Left"]))


def knobs(keymap: list[dict], name: str) -> list[Knob]:
    """The knobs of a keyboard with this layout."""
    layout = LAYOUTS.get(name, LAYOUTS["full"])
    present = {k["KeyName"] for k in keymap}
    found = find_knobs(keymap) if layout.template_knobs else layout.knobs
    return [k for k in found if all(n in present for n in k.parts().values())]


def _union(rects: list[dict]) -> dict | None:
    if not rects:
        return None
    left, top = min(r["Left"] for r in rects), min(r["Top"] for r in rects)
    right = max(r["Left"] + r["Width"] for r in rects)
    bottom = max(r["Top"] + r["Height"] for r in rects)
    return {"Left": left, "Top": top, "Width": right - left, "Height": bottom - top}


def default_layout(model: int | None) -> str:
    return DEFAULT.get(model, "full")


def display_keys(keymap: list[dict], name: str) -> list[dict]:
    """The keys this keyboard has (copies of key-map entries). A knob's three entries all get the knob's area and
    "Shape": "knob", "Knob": its name, "KnobRole": left / right / press; the picture draws them as one knob."""
    layout = LAYOUTS.get(name, LAYOUTS["full"])
    by_name = {k["KeyName"]: k for k in keymap}
    variants = variant_names(keymap)
    parts = {}
    for knob in knobs(keymap, name):
        area = _union([by_name[n]["Position"] for n in knob.at or knob.parts().values() if n in by_name])
        for role, n in knob.parts().items():
            parts[n] = (knob, role, area)
    out = []
    for k in keymap:
        if k["KeyName"] in parts:
            knob, role, area = parts[k["KeyName"]]
            k = copy.deepcopy(k)
            k.update(Position=dict(area), Shape="knob", Knob=knob.name, KnobRole=role,
                     Show=f"{knob.name} {KNOB_ROLES[role].lower()}")
        elif k["KeyName"] in layout.hide or (name != "all" and k["KeyName"] in variants):
            continue
        out.append(k)
    return out


def screen_area(keymap: list[dict], name: str) -> dict | None:
    """{Left, Top, Width, Height} of the layout's screen, if it has one."""
    layout = LAYOUTS.get(name, LAYOUTS["full"])
    return _union([k["Position"] for k in keymap if k["KeyName"] in layout.screen_over])


def spare_indexes(keymap: list[dict], base_profile: dict, name: str) -> list[int]:
    """Matrix positions with no key on this keyboard, best first: never used by any model, then keys this layout
    doesn't have. Used to make the firmware run Fn-layer macros (see profile.build)."""
    used = {k["LogicCode"] for k in keymap}
    for layer in ("KeySet", "FnKeySet"):
        used |= {int(e["Index"]) for e in base_profile.get(layer) or []}
    shown = {k["KeyName"] for k in display_keys(keymap, name)}
    absent = sorted(k["LogicCode"] for k in keymap if k["KeyName"] not in shown)
    return sorted(set(range(128)) - used) + absent
