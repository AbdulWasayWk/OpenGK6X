"""Physical layouts: which of a model's key-map entries are real keys on a given keyboard, and where.

The official key map for a model is a template covering several hardware variants (volume-knob positions, split
spacebar, navigation keys). A layout says which keys a keyboard really has, moves/renames some (the GK104 Pro's
knob sits where Print Screen / Scroll Lock / Pause are), and adds decorations (its screen).
"""
import copy
from dataclasses import dataclass, field

from .vendordata import variant_names


@dataclass(frozen=True)
class Place:
    at: str                  # draw this key where that key would be
    label: str
    round: bool = False


@dataclass(frozen=True)
class Layout:
    label: str
    hide: tuple[str, ...] = ()
    show: dict[str, Place] = field(default_factory=dict)      # variant keys this keyboard has
    screen_over: tuple[str, ...] = ()                          # keys whose area is a screen instead
    unsupported: frozenset[str] = frozenset()                  # binding categories the firmware ignores
    wireless_standard_only: bool = False                       # over 2.4 GHz / Bluetooth only the standard profile


NAV = ("Insert", "Home", "Page Up", "Delete", "End", "Page Down")

LAYOUTS = {
    "gk104pro": Layout(
        "Skyloong GK104 Pro (knob and screen)",
        hide=("Print Screen", "Scroll Lock", "Pause") + NAV,
        show={"Scroll Lock VOLU": Place("Print Screen", "Knob ⟲", True),
              "Scroll Lock MUTE": Place("Scroll Lock", "Knob press", True),
              "Scroll Lock VOLD": Place("Pause", "Knob ⟳", True)},
        screen_over=NAV,
        unsupported=frozenset({"Space dual-role"}),      # tested 2026-10-11: long press just repeats Space
        wireless_standard_only=True),                    # tested 2026-10-11: profile 1 remaps not used on 2.4 GHz
    "full": Layout("Full-size, 104 keys"),
    "all": Layout("Every key in the template (knob positions, split spacebar)"),
}
DEFAULT = {656802056: "gk104pro"}


def default_layout(model: int | None) -> str:
    return DEFAULT.get(model, "full")


def display_keys(keymap: list[dict], name: str) -> list[dict]:
    """The keys to draw: copies of key-map entries, moved/relabelled for the layout; "Shape": "round" for knobs."""
    layout = LAYOUTS.get(name, LAYOUTS["full"])
    by_name = {k["KeyName"]: k for k in keymap}
    variants = variant_names(keymap)
    out = []
    for k in keymap:
        place = layout.show.get(k["KeyName"])
        if place:
            k = copy.deepcopy(k)
            target = by_name.get(place.at)
            if target:
                k["Position"] = dict(target["Position"])
            k["Show"] = place.label
            if place.round:
                k["Shape"] = "round"
        elif k["KeyName"] in layout.hide or (name != "all" and k["KeyName"] in variants):
            continue
        out.append(k)
    return out


def screen_area(keymap: list[dict], name: str) -> dict | None:
    """{Left, Top, Width, Height} of the layout's screen, if it has one."""
    layout = LAYOUTS.get(name, LAYOUTS["full"])
    rects = [k["Position"] for k in keymap if k["KeyName"] in layout.screen_over]
    if not rects:
        return None
    left, top = min(r["Left"] for r in rects), min(r["Top"] for r in rects)
    right = max(r["Left"] + r["Width"] for r in rects)
    bottom = max(r["Top"] + r["Height"] for r in rects)
    return {"Left": left, "Top": top, "Width": right - left, "Height": bottom - top}


def spare_indexes(keymap: list[dict], base_profile: dict, name: str) -> list[int]:
    """Matrix positions with no key on this keyboard, best first: never used by any model, then keys this layout
    doesn't have. Used to make the firmware run Fn-layer macros (see profile.build)."""
    used = {k["LogicCode"] for k in keymap}
    for layer in ("KeySet", "FnKeySet"):
        used |= {int(e["Index"]) for e in base_profile.get(layer) or []}
    shown = {k["KeyName"] for k in display_keys(keymap, name)}
    absent = sorted(k["LogicCode"] for k in keymap if k["KeyName"] not in shown)
    return sorted(set(range(128)) - used) + absent
