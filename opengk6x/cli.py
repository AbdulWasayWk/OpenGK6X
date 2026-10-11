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
from .vendordata import VendorData, VendorDataMissing, variant_names

MODES = {"standard": p.MODE_STANDARD, **SLOT_MODES}


class Abort(Exception):
    pass


wired_keyboard = session.open_wired


def connected_model() -> int:
    with wired_keyboard() as kb:
        return kb.model_id()


def key_name(keymap: list[dict], text: str) -> str:
    """A key's name in the key map: by name, else by the label on the key (real keys before the knob /
    split-spacebar variants), case-insensitive; "#N" = matrix index N."""
    t = text.strip().lower()
    from .layouts import LAYOUTS
    words = " ".join(t.replace("_", " ").replace("-", " ").split())
    roles = {"left": ("left", "turn left"), "right": ("right", "turn right"), "press": ("press",)}
    for layout in LAYOUTS.values():          # knob parts: knob1-left, "middle knob press", "right knob turn left"
        for i, knob in enumerate(layout.knobs, 1):
            for role, part in knob.parts().items():
                said = {f"{n} {r}" for n in (f"knob{i}", f"knob {i}", knob.name.lower()) for r in roles[role]}
                if words in said and any(k["KeyName"] == part for k in keymap):
                    return part
    if t.startswith("#") and t[1:].isdigit():
        hits = [k for k in keymap if k["LogicCode"] == int(t[1:])]
    else:
        hits = [k for k in keymap if k["KeyName"].lower() == t] or \
               sorted((k for k in keymap if k.get("Show", "").lower() == t),
                      key=lambda k: k["KeyName"] in variant_names(keymap))
    if not hits:
        raise ValueError(f"no key {text!r} on this keyboard (see `opengk6x keys`)")
    return hits[0]["KeyName"]


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
            if f.pid == p.PID_DONGLE:
                print(f"{f.link}: no answer (the keyboard is configured over its USB cable)")
                continue
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
    from .layouts import knobs
    model = connected_model()
    keymap = VendorData().keymap(model)
    for k in sorted(keymap, key=lambda k: k["LogicCode"]):
        print(f"{k['LogicCode']:4}  {k['KeyName']:24} {k.get('Show', '')}")
    for i, knob in enumerate(knobs(keymap, Store().layout(model)), 1):
        if i == 1:
            print("\nKnobs (left to right):")
        print(f"  knob{i}-left / knob{i}-right / knob{i}-press   {knob.name}: turn left, turn right, press")


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
            n = len(compile_packets(profiles[slot], slot, vendor, model, kb.matrix(), store.macros(),
                                    store.layout(model)))
            print(f"profile {slot}: {n} packets (dry run, nothing sent)")
            return
        if profiles[slot].applied is None:
            if slot == "standard":
                confirm("This changes the keyboard's own (standard) layout, which it also uses over 2.4 GHz and "
                        "Bluetooth. Holding Fn + Esc + Q resets it to the factory layout. Continue?", yes)
            else:
                confirm(f"Profile {slot} hasn't been written by OpenGK6X before. Writing replaces whatever the "
                        f"keyboard has in it (e.g. settings from the official app). Continue?", yes)
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
    from .layouts import display_keys
    labels = {k["KeyName"]: k["Show"] for k in display_keys(VendorData().keymap(model), store.layout(model))
              if k.get("Shape")}
    print(f"profile {args.slot}: {prof.name or '(no name)'}")
    for title, layer in (("keys", prof.keys), ("Fn layer (hold Fn)", prof.fn_keys)):
        print(f"  {title}:" + ("" if layer else " defaults"))
        for k, v in sorted(layer.items()):
            print(f"    {labels.get(k, k):22} → {describe(v)}")


def cmd_bind(args):
    store, model = Store(), connected_model()
    keymap = VendorData().keymap(model)
    name = key_name(keymap, args.key)
    if args.slot == "standard" and (args.fn or args.binding.lower().startswith("macro:")):
        raise Abort("the standard profile takes key changes only; the keyboard refuses its Fn layer and macros "
                    "(use profile 1-3, which work on the cable)")
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


# --- lighting ---------------------------------------------------------------------------------

def _effects_by_name(store: Store, vendor: VendorData, model: int) -> list[tuple[str, str, str]]:
    """(GUID, name, where) for the user's effects and the official library."""
    mine = [(g, e.get("Name") or g, "mine") for g, e in store.effects().items()]
    return mine + [(e["GUID"], e["Name"], "library") for e in vendor.effect_library(model)]


def cmd_effects(args):
    store, vendor = Store(), VendorData()
    words = [w.lower() for w in args.search]
    for guid, name, where in _effects_by_name(store, vendor, connected_model()):
        if all(w in name.lower() for w in words):
            print(f"{where:8} {name}")


def cmd_lighting_show(args):
    store, vendor = Store(), VendorData()
    with wired_keyboard() as kb:
        model, matrix = kb.model_id(), kb.matrix()
    names = {g: n for g, n, _ in _effects_by_name(store, vendor, model)}
    data = store.lighting(model)
    print("Custom effects (Fn + −):")
    for i, g in enumerate(data["custom"], 1):
        print(f"  {i}. {names.get(g, g + ' (missing)')}")
    if not data["custom"]:
        print("  (none set)")
    st = session.custom_status(store, vendor, model, matrix)
    print({session.UNKNOWN: "Not written by OpenGK6X yet: the keyboard has its own (e.g. from the official app).",
           session.APPLIED: "On the keyboard.",
           session.CHANGED: "Changed since it was written (run: lighting apply)."}[st])


def cmd_lighting_set(args):
    store, vendor = Store(), VendorData()
    model = connected_model()
    known = _effects_by_name(store, vendor, model)
    guids = []
    for want in args.effects:
        hits = [g for g, n, _ in known if n.lower() == want.lower() or g.lower() == want.lower()]
        if not hits:
            raise Abort(f"no effect called {want!r} (see `opengk6x effects`)")
        guids.append(hits[0])
    if len(guids) > 5:
        raise Abort("the keyboard holds 5 custom effects")
    data = store.lighting(model)
    data["custom"] = guids
    store.save_lighting(model, data)
    print("Custom effects set; write them with: opengk6x lighting apply")


def cmd_lighting_apply(args):
    store, vendor = Store(), VendorData()
    model = connected_model()
    data = store.lighting(model)
    if data["applied"] is None:
        confirm("This replaces the custom effects stored in the keyboard (Fn + −), e.g. ones from the official app; "
                "they can't be read back. Continue?", args.yes)
    with wired_keyboard() as kb:
        r = session.write_custom(kb, store, vendor, model, data["custom"])
    print(f"wrote {len(data['custom'])} custom effects ({r.packets} packets, {r.seconds:.1f} s); cycle with Fn + −")


# --- online mode ------------------------------------------------------------------------------

def cmd_live_test(args):
    """A short, self-ending test of online mode: blue keys, then a PC-rendered rainbow wave; prints key presses."""
    import time
    from . import effects as fx
    from .layouts import display_keys
    from .online import Online
    store, vendor = Store(), VendorData()
    with wired_keyboard() as kb:
        model = kb.model_id()
        keymap = vendor.keymap(model)
        names = {k["LogicCode"]: k.get("Show") or k["KeyName"]
                 for k in display_keys(keymap, store.layout(model))}
        live = Online(kb, vendor.base_profile(model))
        live.on_keys = lambda down, up: [print(f"  key down: {names.get(i, f'#{i}')}") for i in sorted(down)]
        leds = [k["LocationCode"] for k in display_keys(keymap, store.layout(model))
                if 0 <= k["LocationCode"] < 132]
        player = fx.Player(fx.make("wave", {"speed": 60}, display_keys(keymap, store.layout(model)), "test"))
        print(f"Online mode for {args.seconds} s: blue first, then a rainbow wave. Type something; Ctrl+C stops.")
        import signal

        def interrupt(*_):
            raise KeyboardInterrupt
        for sig in (signal.SIGHUP, signal.SIGTERM):          # closing the terminal also switches back
            signal.signal(sig, interrupt)
        try:
            live.start()
            end = time.monotonic() + args.seconds
            blue_until = time.monotonic() + 3
            while time.monotonic() < end:
                t = time.monotonic()
                live.show({led: (0, 60, 255) for led in leds} if t < blue_until else player.step())
                time.sleep(max(0.0, 0.05 - (time.monotonic() - t)))
        except (KeyboardInterrupt, OSError):      # Ctrl+C can also surface as an interrupted read (OSError)
            pass
        finally:
            live.stop()
    print("Back on the standard profile.")


def cmd_live_run(args):
    """Live mode without the GUI, with the settings from the Live page (~/.config/opengk6x/<model>/live.json)."""
    import json
    import signal
    import subprocess
    import time
    from . import live as lv
    from .layouts import display_keys
    from .online import Online
    store, vendor = Store(), VendorData()
    with wired_keyboard() as kb:
        model = kb.model_id()
        cfg = lv.LiveConfig.load(store.root, model)
        keys = display_keys(vendor.keymap(model), store.layout(model))
        mine = store.effects()
        effect = mine.get(cfg.effect) if cfg.effect in mine else \
            (json.loads(vendor.effect(cfg.effect) or "null") if cfg.effect else None)
        renderer = lv.Renderer(keys, effect, cfg)
        actions = {k["LogicCode"]: cfg.actions[k["KeyName"]] for k in vendor.keymap(model) if k["KeyName"] in cfg.actions}
        live = Online(kb, vendor.base_profile(model))
        pending = []

        def on_keys(down, _up):
            for i in down:
                renderer.press(i)
                if i in actions:
                    pending.append(actions[i])
        live.on_keys = on_keys
        stop = []
        live.on_mode = lambda m: stop.append(m) if m != p.MODE_ONLINE else None

        def interrupt(*_):
            raise KeyboardInterrupt
        for sig in (signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, interrupt)
        print("Live mode on; Ctrl+C stops." + (f" Key actions: {len(actions)}." if actions else ""))
        try:
            live.start(set(actions))
            while not stop:
                t = time.monotonic()
                live.show(renderer.frame())
                while pending:
                    a = pending.pop(0)
                    if a.get("type") == "command":
                        subprocess.Popen(["sh", "-c", a.get("value", "")], start_new_session=True)
                    elif a.get("type") == "url":
                        subprocess.Popen(["xdg-open", a.get("value", "")], start_new_session=True)
                    elif a.get("type") in ("text", "macro"):
                        events = [("keys", s) for s in lv.text_states(a.get("value", ""))] if a["type"] == "text" \
                            else lv.macro_states(store.macros()[a["value"]].steps) if a["value"] in store.macros() else []
                        for kind, value in events + [("keys", (0, [])), ("mouse", 0)]:
                            if kind == "wait":
                                time.sleep(value / 1000)
                            elif kind == "keys":
                                live.send_keys(*value)
                            else:
                                live.send_mouse(value)
                time.sleep(max(0.0, 0.05 - (time.monotonic() - t)))
        except (KeyboardInterrupt, OSError):
            pass
        finally:
            if stop:
                live.active = False
                print("The keyboard switched profile; live mode ended.")
            else:
                live.stop(lv.EXIT_MODES.get(cfg.exit, p.MODE_STANDARD))
                print("Live mode off.")


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

    c = command(sub, "effects", cmd_effects, "lighting effects: yours and the official library")
    c.add_argument("search", nargs="*")
    light = command(sub, "lighting", None, "the custom effects list (Fn + −)").add_subparsers(dest="action",
                                                                                              required=True)
    command(light, "show", cmd_lighting_show, "the custom effects list and whether the keyboard has it")
    c = command(light, "set", cmd_lighting_set, "set the list (up to 5 effect names, in order)")
    c.add_argument("effects", nargs="*")
    c = command(light, "apply", cmd_lighting_apply, "write the list to the keyboard (replaces what it has)")
    c.add_argument("--yes", "-y", action="store_true")

    live = command(sub, "live", None, "online mode: the PC drives the keyboard while it runs").add_subparsers(
        dest="action", required=True)
    c = command(live, "test", cmd_live_test, "short test: live lighting + key reports, then back to standard")
    c.add_argument("--seconds", type=int, default=20)
    command(live, "run", cmd_live_run, "run live mode with the Live page's settings until Ctrl+C")

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
