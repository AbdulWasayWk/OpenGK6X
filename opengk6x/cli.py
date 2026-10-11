"""`opengk6x …` command line."""
import argparse
import sys

from . import device


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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="opengk6x", description="Configure GK6X keyboards (Skyloong GK104 Pro)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info", help="model and firmware of each connected keyboard (read-only)").set_defaults(func=cmd_info)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
