"""`opengk6x …` command line."""
import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

from . import device, keycodes
from . import profile as pr
from . import protocol as p
from .vendordata import VendorData, VendorDataMissing

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opengk6x"
SLOTS = {"standard": p.MODE_STANDARD, "1": 2, "2": 3, "3": 4}


def wired_keyboard() -> device.Keyboard:
    found = [f for f in device.find() if f.pid == p.PID_WIRED]
    if not found:
        raise device.DeviceError("keyboard not found on the cable (USB 1ea7:0907); configuration needs the cable")
    return device.Keyboard(found[0])


def find_key(keymap: list[dict], name: str) -> dict:
    """A key by matrix index or by name (KeyName or label, case-insensitive)."""
    if name.isdigit():
        hits = [k for k in keymap if k["LogicCode"] == int(name)]
    else:
        hits = [k for k in keymap if name.lower() in (k["KeyName"].lower(), k.get("Show", "").lower())]
    if not hits:
        raise ValueError(f"no key {name!r} (see `opengk6x keys`)")
    return hits[0]


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
    with wired_keyboard() as kb:
        model = kb.model_id()
    for k in sorted(VendorData().keymap(model), key=lambda k: k["LogicCode"]):
        print(f"{k['LogicCode']:4}  {k['KeyName']:24} {k.get('Show', '')}")


def cmd_mode(args):
    with wired_keyboard() as kb:
        reply = kb.set_mode(SLOTS[args.slot])
    print(f"switched to {'standard' if args.slot == 'standard' else 'profile ' + args.slot} "
          f"(reply {reply[:8].hex(' ')})")


def cmd_profile_write(args):
    vd = VendorData()
    mode = SLOTS[args.slot]
    with wired_keyboard() as kb:
        model = kb.model_id()
        profile = json.loads(Path(args.file).read_text(encoding="utf-8-sig")) if args.file \
            else vd.default_profile(model, args.slot)
        profile["ModeIndex"] = mode
        keymap = vd.keymap(model)
        for item in args.set:
            name, _, value = item.partition("=")
            key = find_key(keymap, name)
            v = f"0x{keycodes.parse(value):08X}"
            keyset = profile.setdefault("KeySet", [])
            entry = next((e for e in keyset if int(e["Index"]) == key["LogicCode"]), None)
            if entry is None:
                keyset.append({"Index": key["LogicCode"], "DriverValue": v})
            else:
                entry.update(DriverValue=v)
                entry.pop("Task", None)
            print(f"  {key['KeyName']} (index {key['LogicCode']}) → {v}")
        data = pr.build(profile, kb.matrix(), vd.effect, vd.macro)
        packets = pr.packets(data)
        counts = collections.Counter(f"{x[0]:02x}" for x in packets)
        print(f"profile {args.slot}: {len(packets)} packets ({', '.join(f'{k}×{v}' for k, v in counts.items())})")
        if args.dump:
            for x in packets:
                print(" ", x.hex(" "))
        if args.dry_run:
            return 0
        t = time.monotonic()
        replies = kb.write(packets)
        took = time.monotonic() - t
    summary = collections.Counter(r[:3].hex(" ") for r in replies)
    print(f"written in {took:.1f} s; replies (op sub byte2): "
          + ", ".join(f"{k} ×{v}" for k, v in sorted(summary.items())))
    out = STATE / str(model)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"profile-{args.slot}.json").write_text(json.dumps(profile, ensure_ascii=False, indent=1))
    (out / f"profile-{args.slot}.log").write_text(
        "".join(f"> {a.hex()}\n< {b.hex()}\n" for a, b in zip(packets, replies)))
    if mode != p.MODE_STANDARD:
        print(f"The keyboard is now on profile {args.slot}. Back to standard: opengk6x mode standard")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="opengk6x", description="Configure GK6X keyboards (Skyloong GK104 Pro)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="model and firmware of each connected keyboard (read-only)").set_defaults(func=cmd_info)
    sub.add_parser("keys", help="key names and matrix indexes of the connected keyboard").set_defaults(func=cmd_keys)
    m = sub.add_parser("mode", help="switch to the standard profile or offline profile 1-3")
    m.add_argument("slot", choices=list(SLOTS))
    m.set_defaults(func=cmd_mode)
    prof = sub.add_parser("profile", help="offline profiles stored in the keyboard").add_subparsers(dest="action",
                                                                                                     required=True)
    w = prof.add_parser("write", help="write offline profile 1-3 (default: the official app's default profile)")
    w.add_argument("slot", choices=["1", "2", "3"])
    w.add_argument("--from", dest="file", help="profile JSON (official app format)")
    w.add_argument("--set", action="append", default=[], metavar="KEY=BINDING",
                   help='rebind a key, e.g. --set App=q, --set "Caps Lock=esc", --set Pause=mute (repeatable)')
    w.add_argument("--dry-run", action="store_true", help="build the packets but don't send them")
    w.add_argument("--dump", action="store_true", help="print every packet")
    w.set_defaults(func=cmd_profile_write)
    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (device.DeviceError, VendorDataMissing, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
