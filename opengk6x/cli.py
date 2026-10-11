"""`opengk6x …` command line."""
import argparse
import sys
from pathlib import Path

from . import bindings as b
from . import device
from . import protocol as p
from . import session, transfer
from .macros import REPEAT_MODES, Macro, parse_text, to_text
from .store import SLOT_MODES, Profile, Store, check_binding, compile_packets
from .vendordata import VendorData, VendorDataMissing

MODES = {"standard": p.MODE_STANDARD, **SLOT_MODES}


class Abort(Exception):
    pass


wired_keyboard = session.open_wired


def connected_model() -> int:
    with wired_keyboard() as kb:
        return kb.model_id()


def key_name(keymap: list[dict], text: str) -> str:
    """A key's name in the key map, from its name or label (case-insensitive) or matrix index."""
    t = text.strip().lower()
    for k in keymap:
        if t in (k["KeyName"].lower(), k.get("Show", "").lower()) or (t.isdigit() and int(t) == k["LogicCode"]):
            return k["KeyName"]
    raise ValueError(f"no key {text!r} on this keyboard (see `opengk6x keys`)")


def describe(binding) -> str:
    if isinstance(binding, dict):
        mode = binding.get("repeat", "times")
        how = {"times": f"{binding.get('count', 1)}×", "while_held": "while held", "toggle": "until pressed again"}
        return f"macro {binding['macro']} ({how[mode]})"
    return f"{b.label(b.parse(binding))}  [{binding}]"


def confirm(question: str, yes: bool):
    if yes:
        return
    if not sys.stdin.isatty():
        raise Abort(f"{question} (pass --yes to confirm)")
    if input(f"{question} [y/N] ").strip().lower() not in ("y", "yes"):
        raise Abort("cancelled")


# --- device -------------------------------------------------------------------------------------

def cmd_info(args):
    found = device.find()
    if not found:
        print("No GK6X keyboard found (USB 1ea7:0907 wired, 1ea7:0067 dongle).", file=sys.stderr)
        return 1
    status = 0
    for f in found:
        try:
            with device.Keyboard(f) as kb:
                i = kb.info()
        except device.DeviceError as e:
            print(f"{f.link}: {e}", file=sys.stderr)
            status = 1
            continue
        print(f"{i['link']} ({i['path']})")
        print(f"  model id          {i['model_id']}")
        print(f"  firmware id       0x{i['firmware_id']:08x}")
        print(f"  firmware version  {i['firmware_version']}")
        print(f"  key matrix        {i['matrix'][0]} columns × {i['matrix'][1]} rows")
    return status


def cmd_keys(args):
    for k in sorted(VendorData().keymap(connected_model()), key=lambda k: k["LogicCode"]):
        print(f"{k['LogicCode']:4}  {k['KeyName']:24} {k.get('Show', '')}")


def cmd_actions(args):
    words = [w.lower() for w in args.search]
    last = None
    for a in b.catalog():
        text = f"{a.name} {a.label} {a.category}".lower()
        if not all(w in text for w in words):
            continue
        if a.category != last:
            print(f"\n{a.category}")
            last = a.category
        print(f"  {a.name:28} {a.label}")
    print("\nAlso: any combo (ctrl+shift+t), macro:NAME, raw driver values (0x02001400).")


def cmd_mode(args):
    with wired_keyboard() as kb:
        kb.set_mode(MODES[args.slot])
    print(f"switched to {'the standard profile' if args.slot == 'standard' else 'profile ' + args.slot}")


# --- profiles -----------------------------------------------------------------------------------

def _apply(store: Store, model: int, slot: str, profiles: dict, *, yes: bool, dry_run: bool = False):
    """Write a stored profile to the keyboard and remember what was written."""
    vendor = VendorData()
    with wired_keyboard() as kb:
        if dry_run:
            n = len(compile_packets(profiles[slot], slot, vendor, model, kb.matrix(), store.macros()))
            print(f"profile {slot}: {n} packets (dry run, nothing sent)")
            return
        if profiles[slot].applied is None:
            confirm(f"Profile {slot} hasn't been written by OpenGK6X before. Writing replaces whatever the keyboard "
                    f"has in it (e.g. settings from the official app). Continue?", yes)
        r = session.write_profile(kb, store, vendor, model, slot, profiles)
    print(f"wrote profile {slot} ({r.packets} packets, {r.seconds:.1f} s); the keyboard is now on it")
    if r.unexpected:
        print(f"warning: the keyboard answered {r.unexpected} packets with an unexpected status; see {r.log}",
              file=sys.stderr)


def _load(args, store: Store, model: int, create: bool = False):
    profiles = store.profiles(model)
    if profiles[args.slot] is None:
        if not create:
            raise Abort(f"profile {args.slot} isn't set up yet (bind a key or run `profile reset {args.slot}`)")
        profiles[args.slot] = Profile(name=f"Profile {args.slot}")
    return profiles


def cmd_profile_list(args):
    store, vendor = Store(), VendorData()
    with wired_keyboard() as kb:
        model, matrix = kb.model_id(), kb.matrix()
    for slot, prof in store.profiles(model).items():
        title = f"{prof.name}" if prof and prof.name else ""
        changes = f", {len(prof.keys) + len(prof.fn_keys)} changed keys" if prof else ""
        state = session.STATUS_TEXT[session.status(store, vendor, model, slot, prof, matrix)]
        print(f"profile {slot}: {title}{' — ' if title else ''}{state}{changes}")


def cmd_profile_show(args):
    store, model = Store(), connected_model()
    prof = store.profiles(model)[args.slot]
    if prof is None:
        print(f"profile {args.slot} isn't set up by OpenGK6X yet")
        return
    print(f"profile {args.slot}: {prof.name or '(no name)'}")
    for title, layer in (("keys", prof.keys), ("Fn layer (hold Fn)", prof.fn_keys)):
        print(f"  {title}:" + ("" if layer else " defaults"))
        for k, v in sorted(layer.items()):
            print(f"    {k:22} → {describe(v)}")


def cmd_bind(args):
    store, model = Store(), connected_model()
    keymap = VendorData().keymap(model)
    name = key_name(keymap, args.key)
    if args.binding.lower().startswith("macro:"):
        macro = args.binding[6:]
        if macro not in store.macros():
            raise Abort(f"no macro {macro!r} (see `opengk6x macro list`)")
        binding = {"macro": macro, "repeat": args.repeat, "count": args.count}
    else:
        binding = b.name(b.parse(args.binding))
    check_binding(binding)
    profiles = _load(args, store, model, create=True)
    layer = profiles[args.slot].fn_keys if args.fn else profiles[args.slot].keys
    layer[name] = binding
    store.save_profiles(model, profiles)
    print(f"profile {args.slot}{' Fn+' if args.fn else ' '}{name} → {describe(binding)}")
    if not args.no_apply:
        _apply(store, model, args.slot, profiles, yes=args.yes)


def cmd_unbind(args):
    store, model = Store(), connected_model()
    name = key_name(VendorData().keymap(model), args.key)
    profiles = _load(args, store, model)
    layer = profiles[args.slot].fn_keys if args.fn else profiles[args.slot].keys
    if layer.pop(name, None) is None:
        raise Abort(f"{name} isn't changed in profile {args.slot}")
    store.save_profiles(model, profiles)
    print(f"profile {args.slot}{' Fn+' if args.fn else ' '}{name} → default")
    if not args.no_apply:
        _apply(store, model, args.slot, profiles, yes=args.yes)


def cmd_profile_reset(args):
    store, model = Store(), connected_model()
    profiles = store.profiles(model)
    old = profiles[args.slot]
    profiles[args.slot] = Profile(name=old.name if old else f"Profile {args.slot}",
                                  applied=old.applied if old else None)
    store.save_profiles(model, profiles)
    print(f"profile {args.slot} → all keys default")
    if not args.no_apply:
        _apply(store, model, args.slot, profiles, yes=args.yes)


def cmd_profile_apply(args):
    store, model = Store(), connected_model()
    profiles = _load(args, store, model)
    _apply(store, model, args.slot, profiles, yes=args.yes, dry_run=args.dry_run)


def cmd_profile_rename(args):
    store, model = Store(), connected_model()
    profiles = _load(args, store, model)
    profiles[args.slot].name = args.name
    store.save_profiles(model, profiles)


# --- macros -------------------------------------------------------------------------------------

def cmd_macro_list(args):
    macros = Store().macros()
    if not macros:
        print('no macros yet; e.g.: opengk6x macro set copy-paste "+ctrl c v -ctrl"')
    for m in macros.values():
        print(f"{m.name:20} {len(m.steps):3} steps  {to_text(m.steps)[:60]}")


def cmd_macro_set(args):
    store = Store()
    macros = store.macros()
    steps = parse_text(" ".join(args.steps))
    macros[args.name] = Macro(args.name, steps)
    store.save_macros(macros)
    print(f"macro {args.name}: {to_text(steps)}")
    print("Profiles using it need `opengk6x profile apply SLOT` to pick up the change.")


def cmd_macro_delete(args):
    store = Store()
    macros = store.macros()
    if macros.pop(args.name, None) is None:
        raise Abort(f"no macro {args.name!r}")
    store.save_macros(macros)


# --- setup ------------------------------------------------------------------------------------

def cmd_setup_data(args):
    from .vendorsetup import DATA_DIR, install
    r = install(Path(args.installer), Path(args.dest) if args.dest else DATA_DIR)
    print(f"Copied {r['files']} files ({r['models']} keyboard models) into {r['dir']}")


# --- import / export ----------------------------------------------------------------------------

def cmd_export(args):
    store = Store()
    if args.official:
        model = connected_model() if args.model is None else args.model
        files, notes = transfer.write_official(store, model, VendorData(), Path(args.path))
        for f in files:
            print(f"wrote {f}")
        for n in notes:
            print(f"note: {n}")
        print("In the official app: profiles → its import-configuration button (.gpr); macros and effects → "
              "the import buttons on the Macro and LE pages.")
    else:
        transfer.write_backup(store, Path(args.path))
        print(f"wrote {args.path}")


def cmd_import(args):
    store = Store()
    model = connected_model() if args.model is None else args.model
    paths = [Path(p) for p in args.paths]
    for path in paths:
        if not path.exists():
            raise Abort(f"{path} doesn't exist")
    if len(paths) == 1 and transfer.is_backup(paths[0]):
        imported = transfer.read_backup(paths[0], model)
    else:
        imported = transfer.read_official(paths, model, VendorData())
    for n in imported.notes:
        print(f"note: {n}")
    if not (imported.profiles or imported.macros or imported.effects):
        raise Abort("nothing to import")
    current = store.profiles(model)
    replaced = [s for s in imported.profiles if current[s] and current[s].to_json() != imported.profiles[s].to_json()]
    if replaced and not args.dry_run:
        confirm(f"Replace your OpenGK6X profile {', '.join(replaced)} with the imported one?", args.yes)
    if args.dry_run:
        for slot, prof in sorted(imported.profiles.items()):
            print(f"profile {slot}: {prof.name}")
            for layer, title in ((prof.keys, ""), (prof.fn_keys, "Fn+")):
                for k, v in sorted(layer.items()):
                    print(f"    {title}{k:22} → {describe(v)}")
        print(f"macros: {', '.join(sorted(imported.macros)) or 'none'}; effects: {len(imported.effects)}")
        return
    for line in transfer.merge(store, model, imported):
        print(f"imported {line}")
    if imported.profiles:
        print("Nothing was written to the keyboard. To use an imported profile: opengk6x profile apply SLOT")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="opengk6x", description="Configure GK6X keyboards (Skyloong GK104 Pro)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def command(parent, name, func, help):
        c = parent.add_parser(name, help=help, description=help)
        c.set_defaults(func=func)
        return c

    def writes(c):
        c.add_argument("--no-apply", action="store_true", help="only save; write to the keyboard later")
        c.add_argument("--yes", "-y", action="store_true", help="don't ask before replacing unknown keyboard data")

    c = command(sub, "setup-data", cmd_setup_data, "copy the keyboard model data out of the official app's "
                "installer (GK6X Setup 8.0.7.exe or its .zip); needed once")
    c.add_argument("installer")
    c.add_argument("--dest", help=argparse.SUPPRESS)
    command(sub, "info", cmd_info, "model and firmware of each connected keyboard (read-only)")
    command(sub, "keys", cmd_keys, "key names of the connected keyboard")
    c = command(sub, "actions", cmd_actions, "what a key can be bound to")
    c.add_argument("search", nargs="*")
    c = command(sub, "mode", cmd_mode, "switch to the standard profile or profile 1-3")
    c.add_argument("slot", choices=list(MODES))

    c = command(sub, "bind", cmd_bind, "change what a key does in profile 1-3 (saved, then written)")
    c.add_argument("slot", choices=list(SLOT_MODES))
    c.add_argument("key", help='key name or label, e.g. "Caps Lock", F5, App')
    c.add_argument("binding", help="e.g. esc, ctrl+c, volume_up, mouse_left, profile_2, macro:NAME")
    c.add_argument("--fn", action="store_true", help="the Fn layer (key held together with Fn)")
    c.add_argument("--repeat", choices=list(REPEAT_MODES), default="times", help="macro: how it repeats")
    c.add_argument("--count", type=int, default=1, help="macro: how many times (repeat=times)")
    writes(c)
    c = command(sub, "unbind", cmd_unbind, "set a key back to its default in profile 1-3")
    c.add_argument("slot", choices=list(SLOT_MODES))
    c.add_argument("key")
    c.add_argument("--fn", action="store_true")
    writes(c)

    prof = command(sub, "profile", None, "offline profiles 1-3 stored in the keyboard").add_subparsers(
        dest="action", required=True)
    command(prof, "list", cmd_profile_list, "the profiles and whether the keyboard has them")
    c = command(prof, "show", cmd_profile_show, "a profile's changed keys")
    c.add_argument("slot", choices=list(SLOT_MODES))
    c = command(prof, "apply", cmd_profile_apply, "write a profile to the keyboard")
    c.add_argument("slot", choices=list(SLOT_MODES))
    c.add_argument("--dry-run", action="store_true")
    c.add_argument("--yes", "-y", action="store_true")
    c = command(prof, "reset", cmd_profile_reset, "set every key of a profile back to default")
    c.add_argument("slot", choices=list(SLOT_MODES))
    writes(c)
    c = command(prof, "rename", cmd_profile_rename, "name a profile")
    c.add_argument("slot", choices=list(SLOT_MODES))
    c.add_argument("name")

    mac = command(sub, "macro", None, "macro library").add_subparsers(dest="action", required=True)
    command(mac, "list", cmd_macro_list, "all macros")
    c = command(mac, "set", cmd_macro_set,
                'create or replace a macro: "+ctrl c -ctrl 100ms enter click:left" '
                "(+x press, -x release, x tap, Nms wait)")
    c.add_argument("name")
    c.add_argument("steps", nargs="+")
    c = command(mac, "delete", cmd_macro_delete, "delete a macro")
    c.add_argument("name")

    c = command(sub, "export", cmd_export, "save everything to an OpenGK6X backup (.json), or with --official "
                "write files the official app can import")
    c.add_argument("path", help="backup file, or a folder with --official")
    c.add_argument("--official", action="store_true")
    c.add_argument("--model", type=int, help="keyboard model id (default: the connected keyboard)")
    c = command(sub, "import", cmd_import, "import an OpenGK6X backup, or the official app's files: .gpr/.cmf "
                "profiles, .cms macros, .le effects, or a copy of its GK6XPlus-CMS folder")
    c.add_argument("paths", nargs="+")
    c.add_argument("--dry-run", action="store_true", help="show what would be imported")
    c.add_argument("--yes", "-y", action="store_true")
    c.add_argument("--model", type=int, help="keyboard model id (default: the connected keyboard)")

    args = ap.parse_args(argv)
    try:
        return args.func(args) or 0
    except (device.DeviceError, VendorDataMissing, ValueError, Abort, RuntimeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
