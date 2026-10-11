"""Shared by the CLI and the GUI: the connected keyboard, what OpenGK6X stored for it, and writing profiles."""
import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import device
from . import protocol as p
from .store import Profile, Store, compile_packets, fingerprint
from .vendordata import VendorData

STATE = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opengk6x"

# Profile status (see `status`)
UNKNOWN = "unknown"            # never set up by OpenGK6X: the keyboard may hold older settings
NOT_WRITTEN = "not_written"    # set up, never written
APPLIED = "applied"            # the keyboard has exactly what's stored
CHANGED = "changed"            # edited since it was written

STATUS_TEXT = {UNKNOWN: "Not set up by OpenGK6X (the keyboard may hold older settings)",
               NOT_WRITTEN: "Not written to the keyboard yet",
               APPLIED: "On the keyboard",
               CHANGED: "Changed since it was written"}


@dataclass
class KeyboardInfo:
    link: str
    model: int
    firmware_id: int
    firmware_version: str
    matrix: tuple[int, int]


@dataclass
class WriteResult:
    packets: int
    seconds: float
    unexpected: int            # replies with a status other than the usual one
    log: Path


def open_wired() -> device.Keyboard:
    found = [f for f in device.find() if f.pid == p.PID_WIRED]
    if not found:
        raise device.DeviceError("keyboard not found on the cable (USB 1ea7:0907); configuration needs the cable")
    return device.Keyboard(found[0])


def identify(kb: device.Keyboard) -> KeyboardInfo:
    i = kb.info()
    return KeyboardInfo(i["link"], i["model_id"], i["firmware_id"], i["firmware_version"], i["matrix"])


def status(store: Store, vendor: VendorData, model: int, slot: str, prof: Profile | None,
           matrix: tuple[int, int]) -> str:
    if prof is None:
        return UNKNOWN
    if prof.applied is None:
        return NOT_WRITTEN
    current = fingerprint(compile_packets(prof, slot, vendor, model, matrix, store.macros()))
    return APPLIED if current == prof.applied else CHANGED


def write_profile(kb: device.Keyboard, store: Store, vendor: VendorData, model: int, slot: str,
                  profiles: dict[str, Profile | None], progress=None) -> WriteResult:
    """Write a stored profile to the keyboard (which then switches to it) and record what was written."""
    if kb.model_id() != model:
        raise device.DeviceError("a different keyboard model is connected")
    prof = profiles[slot]
    packets = compile_packets(prof, slot, vendor, model, kb.matrix(), store.macros())
    t = time.monotonic()
    replies = kb.write(packets, progress)
    seconds = time.monotonic() - t
    unexpected = sum(1 for r in replies if r[0] in (p.OP_CLEAR, p.OP_KEYS, p.OP_FN_KEYS, p.OP_MACROS) and r[1] != 0)
    prof.applied = fingerprint(packets)
    store.save_profiles(model, profiles)
    log = STATE / str(model) / f"profile-{slot}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(f"> {a.hex()}\n< {r.hex()}\n" for a, r in zip(packets, replies)))
    return WriteResult(len(packets), seconds, unexpected, log)
