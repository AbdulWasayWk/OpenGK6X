"""Import/export: OpenGK6X data → official app files → back gives the same profiles and macros."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from opengk6x import cmf, transfer
from opengk6x.macros import Macro, parse_text
from opengk6x.store import Profile, Store

from .test_model import DEFAULT, KEYMAP

MODEL = 656802056


class FakeVendor:
    def keymap(self, model):
        return KEYMAP

    def base_profile(self, model):
        return json.loads(json.dumps(DEFAULT))


class TestTransfer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "config")
        profiles = self.store.profiles(MODEL)
        profiles["1"] = Profile("Work", {"App": "q", "F5": {"macro": "greet", "repeat": "toggle", "count": 1}},
                                {"Caps Lock": "ctrl+shift+t"}, applied="abc")
        profiles["3"] = Profile("Games", {"Caps Lock": "esc"})
        self.store.save_profiles(MODEL, profiles)
        self.store.save_macros({"greet": Macro("greet", parse_text("+shift h -shift i 50ms enter")),
                                "f13": Macro("f13", parse_text("f13"))})

    def tearDown(self):
        self.tmp.cleanup()

    def test_official_round_trip(self):
        out = self.root / "export"
        files, notes = transfer.write_official(self.store, MODEL, FakeVendor(), out)
        self.assertIn(out / f"OpenGK6X-{MODEL}.gpr", files)
        self.assertEqual(notes, ["macro f13: the official app can't store key 'f13' in a macro; not exported"])
        with zipfile.ZipFile(out / f"OpenGK6X-{MODEL}.gpr") as z:
            kind, body = cmf.decode(z.read(z.namelist()[0]))
        self.assertEqual(kind, "PROFILE")
        self.assertEqual(json.loads(body)["ModelID"], MODEL)

        imported = transfer.read_official([out], MODEL, FakeVendor())
        self.assertEqual(imported.notes, [])
        self.assertEqual(set(imported.profiles), {"1", "3"})
        for slot in ("1", "3"):
            ours = self.store.profiles(MODEL)[slot]
            got = imported.profiles[slot]
            self.assertEqual((got.name, got.keys, got.fn_keys), (ours.name, ours.keys, ours.fn_keys))
        self.assertEqual(imported.macros["greet"].steps, self.store.macros()["greet"].steps)

    def test_backup_round_trip(self):
        f = self.root / "backup.json"
        transfer.write_backup(self.store, f)
        self.assertTrue(transfer.is_backup(f))
        other = Store(self.root / "other")
        imported = transfer.read_backup(f, MODEL)
        transfer.merge(other, MODEL, imported)
        a, b = self.store.profiles(MODEL), other.profiles(MODEL)
        self.assertEqual(b["1"].keys, a["1"].keys)
        self.assertIsNone(b["1"].applied)          # the other machine never wrote it
        self.assertIsNone(b["2"])
        self.assertEqual(other.macros().keys(), self.store.macros().keys())

    def test_online_and_standard_profiles_are_noted(self):
        d = self.root / "official"
        d.mkdir()
        for mode in (0, 1):
            (d / f"m{mode}.cmf").write_bytes(cmf.encode("PROFILE", json.dumps({"ModeIndex": mode}).encode()))
        (d / "junk.cmf").write_bytes(b"not cmf")
        imported = transfer.read_official([d], MODEL, FakeVendor())
        self.assertEqual(imported.profiles, {})
        self.assertEqual(len(imported.notes), 3)


if __name__ == "__main__":
    unittest.main()
