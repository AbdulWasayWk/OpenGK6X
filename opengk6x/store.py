"""What OpenGK6X keeps on disk, and turning it into what the keyboard stores.

The keyboard can't be read back, so these files are the only record of what's in it:

    ~/.config/opengk6x/<model>/profiles.json   offline profiles 1-3: name + changes from the defaults
    ~/.config/opengk6x/macros.json             macro library (shared by all profiles)
    ~/.config/opengk6x/effects/<GUID>.json     lighting effects (official .le format), e.g. imported ones

A profile only lists keys that differ from the model's default profile:

    {"name": "Gaming", "keys": {"Caps Lock": "esc", "F5": {"macro": "build", "repeat": "times", "count": 1}},
     "fn_keys": {"1": "profile_standard"}, "applied": "<sha256 of the packets last written>" | null}
"""
import copy
import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import bindings as b
from . import profile as pr
from .macros import REPEAT_MODES, Macro, to_actions

CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opengk6x"
SLOT_MODES = {"1": 2, "2": 3, "3": 4}


@dataclass
class Profile:
    name: str = ""
    keys: dict = field(default_factory=dict)       # key name → binding (text, or {"macro", "repeat", "count"})
    fn_keys: dict = field(default_factory=dict)
    applied: str | None = None                     # fingerprint of what OpenGK6X last wrote to this slot
    # keyboards whose profiles have their own lighting (model config hasModeLe): {"effect": GUID | "" (off) |
    # absent (the model's default), "key_effects": {key name: GUID}} (an effect played when that key is pressed)
    lighting: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        out = {"name": self.name, "keys": self.keys, "fn_keys": self.fn_keys, "applied": self.applied}
        if self.lighting:
            out["lighting"] = self.lighting
        return out

    @classmethod
    def from_json(cls, data: dict) -> "Profile":
        return cls(data.get("name", ""), dict(data.get("keys", {})), dict(data.get("fn_keys", {})),
                   data.get("applied"), dict(data.get("lighting", {})))


def check_binding(binding) -> None:
    """Raise ValueError if a binding (text or macro dict) isn't valid."""
    if isinstance(binding, dict):
        if not binding.get("macro"):
            raise ValueError(f"macro binding needs a macro name: {binding}")
        if binding.get("repeat", "times") not in REPEAT_MODES:
            raise ValueError(f"repeat must be one of {', '.join(REPEAT_MODES)}")
        if not 1 <= int(binding.get("count", 1)) <= 255:
            raise ValueError("count must be 1-255")
    else:
        b.parse(binding)


class Store:
    def __init__(self, root: Path = CONFIG):
        self.root = Path(root)

    # profiles
    def _profiles_file(self, model: int) -> Path:
        return self.root / str(model) / "profiles.json"

    def profiles(self, model: int) -> dict[str, Profile | None]:
        """Slot "1"-"3" → Profile, or None if OpenGK6X has never set that slot up (its content is unknown)."""
        f = self._profiles_file(model)
        data = json.loads(f.read_text()) if f.is_file() else {}
        return {s: Profile.from_json(data[s]) if data.get(s) else None for s in SLOT_MODES}

    def save_profiles(self, model: int, profiles: dict[str, Profile | None]):
        f = self._profiles_file(model)
        f.parent.mkdir(parents=True, exist_ok=True)
        data = {s: p.to_json() if p else None for s, p in profiles.items()}
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(f)

    # lighting effects (official .le JSON: {GUID, Name, Frames, LEConfigs}), kept for the lighting pages
    def effects(self) -> dict[str, dict]:
        d = self.root / "effects"
        return {f.stem: json.loads(f.read_text()) for f in sorted(d.glob("*.json"))} if d.is_dir() else {}

    def save_effect(self, effect: dict):
        d = self.root / "effects"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{effect['GUID']}.json").write_text(json.dumps(effect, ensure_ascii=False, indent=1))

    # the custom effects list (Fn + −), stored in the keyboard's standard profile
    def lighting(self, model: int) -> dict:
        """{"custom": [GUID, ...] (up to 5), "applied": fingerprint | None (None: never written by OpenGK6X)}"""
        f = self.root / str(model) / "lighting.json"
        data = json.loads(f.read_text()) if f.is_file() else {}
        return {"custom": list(data.get("custom", [])), "applied": data.get("applied")}

    def save_lighting(self, model: int, data: dict):
        f = self.root / str(model) / "lighting.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, indent=1))

    def delete_effect(self, guid: str):
        (self.root / "effects" / f"{guid}.json").unlink(missing_ok=True)

    # physical layout of the user's keyboard (layouts.py)
    def layout(self, model: int) -> str:
        from .layouts import default_layout
        f = self.root / str(model) / "keyboard.json"
        try:
            return json.loads(f.read_text()).get("layout") or default_layout(model)
        except (OSError, ValueError):
            return default_layout(model)

    def set_layout(self, model: int, name: str):
        f = self.root / str(model) / "keyboard.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"layout": name}, indent=1))

    # macros
    def _macros_file(self) -> Path:
        return self.root / "macros.json"

    def macros(self) -> dict[str, Macro]:
        f = self._macros_file()
        data = json.loads(f.read_text()) if f.is_file() else {}
        return {n: Macro.from_json(n, m) for n, m in data.items()}

    def save_macros(self, macros: dict[str, Macro]):
        f = self._macros_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({n: m.to_json() for n, m in sorted(macros.items())}, ensure_ascii=False, indent=1))
        tmp.replace(f)


# --- Compiling ---------------------------------------------------------------------------------

def _apply(entries: list, keymap_by_name: dict, changes: dict, layer: str):
    by_index = {int(e["Index"]): e for e in entries}
    for key_name, binding in changes.items():
        key = keymap_by_name.get(key_name)
        if key is None:
            raise ValueError(f"{layer}: no key {key_name!r} on this keyboard")
        check_binding(binding)
        entry = by_index.get(key["LogicCode"])
        if entry is None:
            entry = {"Index": key["LogicCode"], "MenuPID": "", "MenuID": "", "MenuName": ""}
            entries.append(entry)
            by_index[key["LogicCode"]] = entry
        entry.pop("Task", None)
        if isinstance(binding, dict):
            entry["DriverValue"] = f"0x{b.MACRO:08X}"
            entry["Task"] = {"Type": "Macro", "Data": {"GUID": binding["macro"], "Repeats": int(binding.get("count", 1)),
                                                       "StopMode": REPEAT_MODES[binding.get("repeat", "times")]}}
        else:
            entry["DriverValue"] = f"0x{b.parse(binding):08X}"


def to_official(profile: Profile, slot: str, default: dict, keymap: list[dict]) -> dict:
    """Our profile → the official app's profile JSON (the model's default profile with our changes)."""
    out = copy.deepcopy(default)
    out["ModeIndex"] = SLOT_MODES[slot]
    out["Name"] = profile.name
    by_name = {k["KeyName"]: k for k in keymap}
    _apply(out.setdefault("KeySet", []), by_name, profile.keys, "keys")
    _apply(out.setdefault("FnKeySet", []), by_name, profile.fn_keys, "Fn keys")
    light = profile.lighting or {}
    if "effect" in light:
        out["ModeLE"] = {"GUID": light["effect"] or "", "Name": ""}
        out.pop("LEData", None)
    if light.get("key_effects"):
        entries = {int(e["Index"]): e for e in out["KeySet"]}
        for key_name, guid in light["key_effects"].items():
            key = by_name.get(key_name)
            if key is None:
                raise ValueError(f"key lighting: no key {key_name!r} on this keyboard")
            entry = entries.get(key["LogicCode"])
            if entry is not None:
                entry["KeyLE"] = {"GUID": guid or "", "Name": ""}
    return out


def compile_packets(profile: Profile, slot: str, vendor, model: int, matrix: tuple[int, int],
                    macros: dict[str, Macro], layout: str | None = None, load_effect=None) -> list[bytes]:
    """The packets that write `profile` into `slot` (ends by switching the keyboard to it)."""
    from .layouts import default_layout, spare_indexes
    keymap, base = vendor.keymap(model), vendor.base_profile(model)
    official = to_official(profile, slot, base, keymap)
    spare = spare_indexes(keymap, base, layout or default_layout(model))
    has_lighting = bool(vendor.model_config(model).get("hasModeLe"))

    def load_macro(name):
        if name not in macros:
            raise ValueError(f"macro {name!r} doesn't exist (see `opengk6x macro list`)")
        return to_actions(macros[name].steps)

    data = pr.build(official, matrix, load_effect or vendor.effect, load_macro, lighting=has_lighting, spare=spare)
    return pr.packets(data)


def presets(vendor, model: int) -> dict[str, Profile]:
    """Ready-made starting points besides the standard layout: the official app's profile 2 / 3 defaults where
    they differ (on the GK104 Pro profile 2 is a Mac layout), as changes from the standard layout."""
    from .profile import js_parse_int
    from . import bindings as b
    names = {k["LogicCode"]: k["KeyName"] for k in vendor.keymap(model)}
    base = vendor.base_profile(model)
    out = {}
    for slot in ("2", "3"):
        try:
            other = vendor.default_profile(model, slot)
        except (OSError, ValueError):
            continue
        prof = Profile()
        for layer, ours in (("KeySet", prof.keys), ("FnKeySet", prof.fn_keys)):
            before = {int(e["Index"]): js_parse_int(e.get("DriverValue"), 16) for e in base.get(layer) or []}
            for e in other.get(layer) or []:
                v = js_parse_int(e.get("DriverValue"), 16)
                if int(e["Index"]) in names and v is not None and v != before.get(int(e["Index"])):
                    ours[names[int(e["Index"])]] = b.name(v & 0xFFFFFFFF)
        if not (prof.keys or prof.fn_keys):
            continue
        mac = prof.keys.get("Left Alt") == "lwin" and prof.keys.get("Left GUI") == "lalt"
        prof.name = "Mac" if mac else f"Official {slot}"
        title = ("Mac layout" if mac else f"the official app's profile {slot} default") + \
            (f" (the official app's profile {slot} default)" if mac else "")
        if all(p.keys != prof.keys or p.fn_keys != prof.fn_keys for p in out.values()):
            out[title] = prof
    return out


def effect_loader(store: Store, vendor):
    """GUID → effect JSON text: the user's effects first, then the official library."""
    mine = store.effects()

    def load(guid):
        if guid in mine:
            return json.dumps(mine[guid])
        return vendor.effect(guid)
    return load


def compile_custom(store: Store, vendor, model: int, matrix: tuple[int, int], guids: list[str]) -> list[bytes]:
    """The packets that replace the custom effects list (the standard profile's lighting). Effects that can't be
    found are skipped, as the app does."""
    from .effects import standard_profile
    profile = standard_profile([{"GUID": g} for g in guids if g])
    data = pr.build(profile, matrix, effect_loader(store, vendor), lambda g: None, lighting=True)
    return pr.packets(data)


def fingerprint(packets: list[bytes]) -> str:
    return hashlib.sha256(b"".join(packets)).hexdigest()
