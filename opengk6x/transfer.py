"""Import and export: the official app's files, and OpenGK6X backups.

Official app (all CMF-encoded, see cmf.py):
    .gpr   profiles: a zip of Account/<id>/Devices/<model>/<GUID>.cmf (the app's "export configuration")
    .cmf   one profile (JSON)          .cms   one macro (script text)          .le   one lighting effect (JSON)
    a folder, e.g. a copy of the app's data folder GK6XPlus-CMS (Windows: %APPDATA%\\GK6XPlus-CMS): everything in it

OpenGK6X backup: one JSON file with the profiles of each keyboard model, the macros and the effects.
"""
import io
import json
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import bindings as b
from . import cmf
from .macros import REPEAT_MODES, Macro, from_script, to_script
from .profile import js_parse_int
from .store import SLOT_MODES, Profile, Store, to_official

BACKUP_FORMAT = "opengk6x-backup"
_STOP_MODES = {v: k for k, v in REPEAT_MODES.items()}
_SLOTS = {mode: slot for slot, mode in SLOT_MODES.items() if slot != "standard"}   # official std has no keys
_NAMESPACE = uuid.UUID("5d0f7e2c-9a51-4f6e-8a5e-0c6b8f3e1a77")


@dataclass
class Imported:
    profiles: dict[str, Profile] = field(default_factory=dict)       # slot → profile
    macros: dict[str, Macro] = field(default_factory=dict)
    effects: dict[str, dict] = field(default_factory=dict)            # GUID → effect
    notes: list[str] = field(default_factory=list)


def guid_for(kind: str, name: str) -> str:
    """Stable GUID for something we export (the same name always gets the same GUID)."""
    return str(uuid.uuid5(_NAMESPACE, f"{kind}:{name}")).upper()


# --- Official files → OpenGK6X ------------------------------------------------------------------

def _official_files(paths: list[Path]):
    """(kind, label, plain body) for every official file under `paths`; kind = PROFILE / MACRO / LIGHT."""
    for path in paths:
        files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
        for f in files:
            suffix = f.suffix.lower()
            if suffix == ".gpr" or (suffix == ".zip" and zipfile.is_zipfile(f)):
                with zipfile.ZipFile(f) as z:
                    for member in z.namelist():
                        if member.lower().endswith(".cmf"):
                            yield _decoded(z.read(member), f"{f.name}:{member}", Path(member).stem)
            elif suffix in (".cmf", ".cms", ".le"):
                yield _decoded(f.read_bytes(), str(f), f.stem)


def _decoded(blob: bytes, label: str, stem: str):
    try:
        kind, body = cmf.decode(blob)
    except ValueError:
        return None, label, stem, b""
    return kind, label, stem, body


def profile_from_official(official: dict, default: dict, keymap: list[dict], macro_names: dict[str, str],
                          notes: list[str]) -> Profile:
    """An official offline profile → our profile (only the keys that differ from the model's defaults)."""
    names = {k["LogicCode"]: k["KeyName"] for k in keymap}
    prof = Profile(name=official.get("Name") or "")
    for layer, ours in (("KeySet", prof.keys), ("FnKeySet", prof.fn_keys)):
        defaults = {int(e["Index"]): js_parse_int(e.get("DriverValue"), 16) for e in default.get(layer) or []}
        for e in official.get(layer) or []:
            idx = int(e["Index"])
            value = js_parse_int(e.get("DriverValue"), 16)
            task = e.get("Task") or {}
            key = names.get(idx, f"key {idx}")
            if value == b.MACRO and task.get("Type") == "Macro":
                data = task.get("Data") or {}
                macro = macro_names.get(data.get("GUID"))
                if macro is None:
                    notes.append(f"{prof.name or 'profile'}: {key} uses a macro that wasn't found; left at default")
                    continue
                binding = {"macro": macro, "repeat": _STOP_MODES.get(int(data.get("StopMode") or 1), "times"),
                           "count": max(1, min(255, int(data.get("Repeats") or 1)))}
            elif value is None or task.get("Type") in ("OpenURL", "OpenApp") or not str(e.get("DriverValue", "")) \
                    .lower().startswith("0x"):
                notes.append(f"{prof.name or 'profile'}: {key} opens an app/file (official online mode only); "
                             "left at default")
                continue
            elif value == defaults.get(idx):
                continue
            else:
                binding = b.name(value & 0xFFFFFFFF)
            if idx not in names:
                notes.append(f"{prof.name or 'profile'}: change on hidden key {idx} not imported")
                continue
            ours[names[idx]] = binding
    return prof


def read_official(paths: list[Path], model: int, vendor) -> Imported:
    out = Imported()
    items = list(_official_files(paths))
    macro_names: dict[str, str] = {}
    for kind, label, stem, body in items:
        if kind is None:
            out.notes.append(f"{label}: not an official app file, skipped")
        elif kind == "MACRO":
            text = body.decode("utf-8-sig", errors="replace")
            general = dict(line.split("=", 1) for line in text.splitlines() if "=" in line and not line.startswith("["))
            name = (general.get("Name") or stem).strip() or stem
            guid = (general.get("ScriptID") or stem).strip()
            base, n = name, 1
            while name in out.macros and out.macros[name].steps != from_script(text):
                n += 1
                name = f"{base} ({n})"
            out.macros[name] = Macro(name, from_script(text))
            macro_names[guid] = macro_names[stem] = name
        elif kind == "LIGHT":
            try:
                effect = json.loads(body.decode("utf-8-sig"))
            except ValueError:
                out.notes.append(f"{label}: unreadable lighting effect, skipped")
                continue
            effect.setdefault("GUID", stem)
            effect.setdefault("Name", stem)
            out.effects[effect["GUID"]] = effect
    keymap = vendor.keymap(model)
    for kind, label, stem, body in items:
        if kind != "PROFILE":
            continue
        try:
            official = json.loads(body.decode("utf-8-sig"))
        except ValueError:
            out.notes.append(f"{label}: unreadable profile, skipped")
            continue
        if official.get("ModelID") not in (None, 0, model) and str(model) not in label:
            out.notes.append(f"{label}: profile for another keyboard model ({official.get('ModelID')}), skipped")
            continue
        mode = official.get("ModeIndex")
        if mode not in _SLOTS:
            what = {0: "an online-mode profile", 1: "the standard profile (its lighting list)"}.get(mode, "a profile")
            out.notes.append(f"{label}: {what}; not imported yet")
            continue
        slot = _SLOTS[mode]
        if slot in out.profiles:
            out.notes.append(f"{label}: another profile for slot {slot}; this one replaces the earlier one")
        out.profiles[slot] = profile_from_official(official, vendor.base_profile(model), keymap,
                                                   macro_names, out.notes)
        if not out.profiles[slot].name:
            out.profiles[slot].name = f"Profile {slot}"
    return out


# --- OpenGK6X backups ---------------------------------------------------------------------------

def write_backup(store: Store, path: Path) -> dict:
    keyboards = {}
    for d in sorted(p for p in store.root.iterdir() if p.is_dir() and p.name.isdigit()) if store.root.is_dir() else []:
        profiles = store.profiles(int(d.name))
        keyboards[d.name] = {"profiles": {s: p.to_json() for s, p in profiles.items() if p}}
    data = {"format": BACKUP_FORMAT, "version": 1, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "keyboards": keyboards, "macros": {n: m.to_json() for n, m in store.macros().items()},
            "effects": store.effects()}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def read_backup(path: Path, model: int) -> Imported:
    data = json.loads(Path(path).read_text())
    if data.get("format") != BACKUP_FORMAT:
        raise ValueError(f"{path} isn't an OpenGK6X backup")
    out = Imported()
    out.macros = {n: Macro.from_json(n, m) for n, m in data.get("macros", {}).items()}
    out.effects = dict(data.get("effects", {}))
    kb = data.get("keyboards", {}).get(str(model))
    if kb is None:
        others = ", ".join(data.get("keyboards", {})) or "none"
        out.notes.append(f"no profiles for this keyboard model in the backup (it has: {others})")
    else:
        out.profiles = {s: Profile.from_json(p) for s, p in kb.get("profiles", {}).items() if s in SLOT_MODES}
    return out


def is_backup(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    try:
        return json.loads(path.read_text()).get("format") == BACKUP_FORMAT
    except (ValueError, AttributeError):
        return False


def merge(store: Store, model: int, imported: Imported) -> list[str]:
    """Add imported items to the store. Profiles replace their slot; the record of what the keyboard has stays
    (so a profile shows as changed until it's applied). Macros with the same name are replaced."""
    done = []
    if imported.profiles:
        profiles = store.profiles(model)
        for slot, prof in sorted(imported.profiles.items()):
            old = profiles[slot]
            prof.applied = old.applied if old else None
            profiles[slot] = prof
            done.append(f"profile {slot}: {prof.name} ({len(prof.keys) + len(prof.fn_keys)} changed keys)")
        store.save_profiles(model, profiles)
    if imported.macros:
        macros = store.macros()
        macros.update(imported.macros)
        store.save_macros(macros)
        done.append(f"{len(imported.macros)} macros: {', '.join(sorted(imported.macros))}")
    for effect in imported.effects.values():
        store.save_effect(effect)
    if imported.effects:
        done.append(f"{len(imported.effects)} lighting effects (kept for the lighting pages)")
    return done


# --- OpenGK6X → official files ------------------------------------------------------------------

def write_official(store: Store, model: int, vendor, out_dir: Path) -> tuple[list[Path], list[str]]:
    """Files the official app can import: profiles .gpr, one .cms per macro, one .le per effect."""
    out_dir = Path(out_dir)
    written, notes = [], []
    macros = store.macros()
    (out_dir / "macros").mkdir(parents=True, exist_ok=True)
    exported_macros = set()
    for name, macro in sorted(macros.items()):
        guid = guid_for("macro", name)
        try:
            script = to_script(name, guid, macro.steps)
        except ValueError as e:
            notes.append(f"macro {name}: {e}; not exported")
            continue
        f = out_dir / "macros" / f"{_safe(name)}.cms"
        f.write_bytes(cmf.encode("MACRO", script.encode("utf-8")))
        written.append(f)
        exported_macros.add(name)

    profiles = {s: p for s, p in store.profiles(model).items() if p and s != "standard"}   # the app can't use it
    if profiles:
        buf = io.BytesIO()
        keymap = vendor.keymap(model)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for slot, prof in profiles.items():
                official = to_official(prof, slot, vendor.base_profile(model), keymap)
                guid = guid_for("profile", f"{model}:{slot}")
                official.update(GUID=guid, ModelID=model, Active=0)
                for layer in ("KeySet", "FnKeySet"):
                    for e in official.get(layer) or []:
                        data = (e.get("Task") or {}).get("Data")
                        if data and data.get("GUID") in macros:
                            if data["GUID"] not in exported_macros:
                                notes.append(f"profile {slot}: macro {data['GUID']} couldn't be exported")
                            data["GUID"] = guid_for("macro", data["GUID"])
                body = json.dumps(official, ensure_ascii=False, indent="\t").encode("utf-8")
                z.writestr(f"{guid}.cmf", cmf.encode("PROFILE", body))
        f = out_dir / f"OpenGK6X-{model}.gpr"
        f.write_bytes(buf.getvalue())
        written.append(f)

    effects = store.effects()
    if effects:
        (out_dir / "effects").mkdir(exist_ok=True)
        for guid, effect in effects.items():
            f = out_dir / "effects" / f"{_safe(effect.get('Name') or guid)}.le"
            f.write_bytes(cmf.encode("LIGHT", json.dumps(effect, ensure_ascii=False).encode("utf-8")))
            written.append(f)
    return written, notes


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_.()+" else "_" for c in name).strip() or "unnamed"
