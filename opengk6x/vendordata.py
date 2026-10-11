"""Per-model data, lighting effects and macros from the user's copy of the official app.

That data is the vendor's (proprietary), so it isn't shipped. It's read from the app's `resources` folder, found at
(first match): $OPENGK6X_VENDOR_DIR, ~/.local/share/opengk6x/vendor, or vendor-app/asar/resources in this checkout.
"""
import json
import os
from pathlib import Path

from . import cmf

SEARCH = [
    os.environ.get("OPENGK6X_VENDOR_DIR"),
    Path.home() / ".local/share/opengk6x/vendor",
    Path(__file__).resolve().parent.parent / "vendor-app/asar/resources",
]


class VendorDataMissing(Exception):
    pass


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class VendorData:
    def __init__(self, root: Path | None = None):
        if root is None:
            root = next((Path(p) for p in SEARCH if p and (Path(p) / "device/modellist.json").is_file()), None)
            if root is None:
                raise VendorDataMissing("official app data not found; extract GK6X Setup 8.0.7 (see README)")
        self.root = Path(root)

    def model_dir(self, model_id: int) -> Path:
        d = self.root / "device" / str(model_id)
        if not d.is_dir():
            raise VendorDataMissing(f"no data for keyboard model {model_id} in {self.root}")
        return d

    def model_config(self, model_id: int) -> dict:
        return _read_json(self.model_dir(model_id) / "config.json")

    def keymap(self, model_id: int) -> list[dict]:
        """Keys: KeyName, Show, LogicCode (= matrix index), LocationCode (= LED index), Position."""
        return _read_json(self.model_dir(model_id) / "data/keymap.js")

    def default_profile(self, model_id: int, slot: str) -> dict:
        """slot: 'std', '1', '2', '3' (offline profiles) or 'online'."""
        name = "profile_online_1.json" if slot == "online" else f"profile_offline_{slot}.json"
        return _read_json(self.model_dir(model_id) / "data" / name)

    def effect(self, guid: str) -> str | None:
        """A lighting effect's JSON text, or None if the library doesn't have it."""
        path = self.root / "res/data/le" / f"{guid}.le"
        return cmf.decode_text(path.read_bytes()) if path.is_file() else None

    def macro(self, guid: str) -> str | None:
        """A macro's script text, or None if the library doesn't have it."""
        path = self.root / "res/data/macro" / f"{guid}.cms"
        return cmf.decode_text(path.read_bytes()) if path.is_file() else None
