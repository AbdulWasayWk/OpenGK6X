"""Bindings catalog, macros, profile store and compiler (no hardware, no vendor data)."""
import json
import tempfile
import unittest
from pathlib import Path

from opengk6x import bindings as b
from opengk6x import macros as m
from opengk6x import profile as pr
from opengk6x.store import Profile, Store, to_official

KEYMAP = [{"KeyName": "App", "Show": "App", "LogicCode": 1, "LocationCode": 122},
          {"KeyName": "Caps Lock", "Show": "Caps L", "LogicCode": 62, "LocationCode": 44},
          {"KeyName": "F5", "Show": "F5", "LogicCode": 67, "LocationCode": 7}]
DEFAULT = {"GUID": "", "ModeIndex": 2, "Name": "", "ModeLE": {"GUID": "X", "Name": ""},
           "KeySet": [{"Index": 1, "DriverValue": "0x02006500", "KeyLE": {"GUID": "", "Name": ""}},
                      {"Index": 62, "DriverValue": "0x02003900"}],
           "FnKeySet": [{"Index": 67, "DriverValue": "0x030000E9"}]}


class TestBindings(unittest.TestCase):
    def test_round_trip(self):
        for text in ["a", "f13", "ctrl+shift+t", "lctrl", "rwin", "volume_up", "mouse_back", "profile_2",
                     "space_hold_lctrl_lshift", "sleep", "disabled", "brightness_up", "kp_enter"]:
            self.assertEqual(b.parse(b.name(b.parse(text))), b.parse(text), text)

    def test_values(self):
        self.assertEqual(b.parse("ctrl+c"), 0x02000601)
        self.assertEqual(b.parse("App"), 0x02006500)
        self.assertEqual(b.parse("q"), 0x02001400)
        self.assertEqual(b.parse("mute"), 0x030000E2)
        self.assertEqual(b.parse("mouse_right"), 0x01010002)
        self.assertEqual(b.parse("space_hold_rctrl"), 0x0A0C0010)
        self.assertEqual(b.parse("0x0A130002"), 0x0A130002)
        self.assertEqual(b.label(0x02000601), "Copy (Ctrl+C)")
        self.assertEqual(b.label(0x02000703), "Ctrl+Shift+D")
        self.assertEqual(b.name(0x02001703), "ctrl+shift+t")
        self.assertEqual(b.name(0x02001740), "altgr+t")
        self.assertEqual(b.name(0x02000001), "lctrl")
        with self.assertRaises(ValueError):
            b.parse("ctrl+nosuchkey")
        with self.assertRaises(ValueError):
            b.parse("a+b")

    def test_catalog_unique(self):
        names = [a.name for a in b.catalog()]
        self.assertEqual(len(names), len(set(names)))

    def test_official_functions(self):
        """Every driver value the official app offers has a name (when the unpacked app is around)."""
        f = Path(__file__).parent.parent / "vendor-app/decoded/keyfuncs.json"
        if not f.is_file():
            self.skipTest("vendor-app/decoded/keyfuncs.json not present")
        unnamed = []
        for v in json.loads(f.read_text())["49271"]:
            if v.startswith("0x") and b.name(int(v, 16)).startswith("0x"):
                unnamed.append(v.lower())
        self.assertEqual(sorted(unnamed), ["0x0a080002", "0x0a130002", "0x0a130003", "0x0a130004"])


class TestMacros(unittest.TestCase):
    def test_text(self):
        steps = m.parse_text("+ctrl c -ctrl 100ms enter click:left +shift")
        self.assertEqual(steps[:3], [{"key": "lctrl", "action": "down"}, {"key": "c", "action": "down"},
                                     {"key": "c", "action": "up"}])
        self.assertEqual(m.to_text(steps), "+ctrl c -ctrl 100ms enter click:left +shift")
        with self.assertRaises(ValueError):
            m.parse_text("click:middle")
        self.assertEqual(m.parse_text("ctrl+shift+t"), m.parse_text("+ctrl +shift t -shift -ctrl"))
        with self.assertRaises(ValueError):
            m.parse_text("+ctrl+v")
        with self.assertRaises(ValueError):
            m.validate_step({"key": "ctrl+v", "action": "down"})

    def test_actions(self):
        steps = m.parse_text("+ctrl c -ctrl 300ms click:right")
        self.assertEqual(m.to_actions(steps), [(0, 1, 1, 1), (6, 0, 1, 1), (6, 0, 2, 1), (0, 1, 2, 1),
                                               (44, 1, 0, 3), (2, 0, 1, 2), (2, 0, 2, 2)])

    def test_script_round_trip(self):
        steps = m.parse_text("+ctrl c -ctrl 300ms click:right kp_5 f12")
        script = m.to_script("t", "G", steps)
        self.assertEqual(m.from_script(script), steps)
        # our actions and the official script give the same keyboard data
        self.assertEqual(pr.macro_frame(0, 1, 1, m.to_actions(steps)), pr.macro_frame(0, 1, 1, script))
        with self.assertRaises(ValueError):
            m.to_script("t", "G", m.parse_text("f13"))       # not nameable in the official format

    def test_limit(self):
        with self.assertRaises(ValueError):
            m.to_actions([{"delay": 1}] * 126)


class TestStore(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            self.assertEqual(store.profiles(1), {"standard": Profile(name="Standard"), "1": None, "2": None,
                                                 "3": None})
            profiles = store.profiles(1)
            profiles["2"] = Profile("Gaming", {"App": "q"}, {}, "abc")
            store.save_profiles(1, profiles)
            self.assertEqual(store.profiles(1)["2"], profiles["2"])
            store.save_macros({"x": m.Macro("x", m.parse_text("a b"))})
            self.assertEqual(store.macros()["x"].steps, m.parse_text("a b"))

    def test_to_official(self):
        prof = Profile("P", {"App": "q", "F5": {"macro": "build", "repeat": "toggle", "count": 1}},
                       {"Caps Lock": "esc"})
        out = to_official(prof, "3", DEFAULT, KEYMAP)
        self.assertEqual(out["ModeIndex"], 4)
        keys = {e["Index"]: e for e in out["KeySet"]}
        self.assertEqual(keys[1]["DriverValue"], "0x02001400")
        self.assertEqual(keys[1]["KeyLE"], {"GUID": "", "Name": ""})        # other fields kept
        self.assertEqual(keys[67]["Task"], {"Type": "Macro", "Data": {"GUID": "build", "Repeats": 1, "StopMode": 3}})
        self.assertEqual({e["Index"]: e["DriverValue"] for e in out["FnKeySet"]},
                         {67: "0x030000E9", 62: "0x02002900"})
        self.assertEqual(DEFAULT["KeySet"][0]["DriverValue"], "0x02006500")   # the default isn't modified
        with self.assertRaises(ValueError):
            to_official(Profile("P", {"Nope": "a"}), "1", DEFAULT, KEYMAP)


class TestStandardProfile(unittest.TestCase):
    class Vendor:
        def keymap(self, model):
            return KEYMAP

        def base_profile(self, model):
            return json.loads(json.dumps(DEFAULT))

        def model_config(self, model):
            return {}

    def test_keys_only(self):
        from opengk6x import protocol as p
        from opengk6x.store import compile_packets
        packets = compile_packets(Profile("S", {"App": "q"}), "standard", self.Vendor(), 1, (16, 8), {}, "full")
        ops = [(x[0], x[1]) for x in packets]
        self.assertEqual(ops[0], (p.OP_CLEAR, 1))
        self.assertEqual(packets[0][2], p.DATA_KEYS)
        self.assertEqual(ops[1:-1], [(p.OP_KEYS, 1)] * 10)
        self.assertEqual(ops[-1], (p.OP_SET_MODE, 1))
        self.assertEqual(packets[1][8 + 4:8 + 8], bytes([0, 0x14, 0, 2]))          # App (index 1) = q
        with self.assertRaises(ValueError):
            compile_packets(Profile("S", fn_keys={"App": "q"}), "standard", self.Vendor(), 1, (16, 8), {}, "full")
        with self.assertRaises(ValueError):
            compile_packets(Profile("S", {"App": {"macro": "m"}}), "standard", self.Vendor(), 1, (16, 8),
                            {}, "full")


class TestModels(unittest.TestCase):
    def test_variant_names(self):
        from opengk6x.vendordata import variant_names
        keymap = [{"KeyName": n} for n in ("Escape", "Escape VOLU", "Tab", "Tab +", "Tab -", "Page Down",
                                            "Page Down mute", "Delete", "Delete mute **", "F11", "F11VolUp",
                                            "Keypad -", "Keypad +", "Mute", "Left Space", "Space")]
        self.assertEqual(variant_names(keymap), {"Escape VOLU", "Tab +", "Tab -", "Page Down mute",
                                                 "Delete mute **", "F11VolUp", "Left Space"})

    def test_profile_lighting_to_official(self):
        prof = Profile("P", {"App": "q"}, lighting={"effect": "E1", "key_effects": {"App": "E2"}})
        out = to_official(prof, "1", DEFAULT, KEYMAP)
        self.assertEqual(out["ModeLE"], {"GUID": "E1", "Name": ""})
        self.assertEqual(next(e for e in out["KeySet"] if e["Index"] == 1)["KeyLE"], {"GUID": "E2", "Name": ""})
        off = to_official(Profile("P", lighting={"effect": ""}), "1", DEFAULT, KEYMAP)
        self.assertEqual(off["ModeLE"]["GUID"], "")
        untouched = to_official(Profile("P"), "1", DEFAULT, KEYMAP)
        self.assertEqual(untouched["ModeLE"], DEFAULT["ModeLE"])
        self.assertEqual(Profile.from_json(prof.to_json()), prof)

    def test_knob(self):
        from opengk6x import layouts
        self.assertEqual(set(layouts.knob_keys("gk104pro")), set(layouts.KNOB_ROLES))
        self.assertEqual(layouts.knob_keys("full"), {})
        values = [b.parse(v) for v, _ in layouts.KNOB_ACTIONS]      # every choice is a known action, once
        self.assertEqual(len(values), len(set(values)))


if __name__ == "__main__":
    unittest.main()
