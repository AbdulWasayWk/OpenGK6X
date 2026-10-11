"""Profile writer vs the official app: tests/golden/*.json are the packets GK6+ 8.0.7's own profile.js writes for
tests/fixtures/profiles/*.json (regenerate with tools/re/make_goldens.sh)."""
import json
import unittest
from pathlib import Path

from opengk6x import profile as pr
from opengk6x import protocol as p

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
MATRIX = (16, 8)


def load_effect(guid):
    f = FIXTURES / "le" / f"{guid}.json"
    return f.read_text() if f.is_file() else None


def load_macro(guid):
    f = FIXTURES / "macro" / f"{guid}.cms"
    return f.read_bytes().decode("utf-8") if f.is_file() else None


def our_packets(profile):
    data = pr.build(profile, MATRIX, load_effect, load_macro, app_compatible=True)
    return [p.info_request(p.INFO_MATRIX).hex()] + [x.hex() for x in pr.packets(data)]


class TestAgainstOfficialApp(unittest.TestCase):
    def test_golden_profiles(self):
        names = sorted(f.stem for f in (HERE / "golden").glob("*.json"))
        self.assertEqual(names, ["full", "keys-only", "standard", "static"])
        for name in names:
            with self.subTest(name):
                profile = json.loads((FIXTURES / "profiles" / f"{name}.json").read_text())
                golden = json.loads((HERE / "golden" / f"{name}.json").read_text())
                ours = our_packets(profile)
                for i, (a, b) in enumerate(zip(ours, golden)):
                    self.assertEqual(a, b, f"packet {i}")
                self.assertEqual(len(ours), len(golden))

    def test_standard_profile_doesnt_switch_or_write_keys(self):
        profile = json.loads((FIXTURES / "profiles" / "standard.json").read_text())
        ops = {bytes.fromhex(x)[0] for x in our_packets(profile)}
        self.assertNotIn(p.OP_KEYS, ops)
        self.assertNotIn(p.OP_FN_KEYS, ops)
        self.assertNotIn(p.OP_SET_MODE, ops)


class TestBlocks(unittest.TestCase):
    def test_key_table(self):
        table = pr.key_table([{"Index": 1, "DriverValue": "0x02000601"}, {"Index": 300, "DriverValue": "0x1"}],
                             512, lambda i, k: 0)
        self.assertEqual(table[4:8], bytes([0x01, 0x06, 0x00, 0x02]))
        self.assertEqual(table[:4], b"\xff" * 4)

    def test_macro_frame(self):
        frame = pr.macro_frame(2, 1, 5, '[Script]\nKeyDown "A"\nDelay 300\nKeyUp "A"\n')
        self.assertEqual(frame[:2], b"\xaa\x55")
        self.assertEqual(frame[4:8], bytes([4, 2, 1, 5]))       # 3 steps + the appended Delay 5
        self.assertEqual(frame[8:24], bytes([0x04, 0, 1, 1, 44, 1, 0, 3, 0x04, 0, 2, 1, 5, 0, 0, 3]))

    def test_macro_errors(self):
        with self.assertRaises(ValueError):
            pr.macro_frame(0, 1, 1, "[Script]\nDelay 70000\n")    # the app's writeUInt8 throws too
        with self.assertRaises(ValueError):
            pr.macro_data({"KeySet": [{"Index": 1, "DriverValue": "0x0A010001",
                                       "Task": {"Type": "Macro", "Data": {"GUID": "nope"}}}]}, lambda g: None)

    def test_macro_slots_fixed(self):
        """Our default: every macro key, main or Fn, gets its own macro's slot (the app gives Fn keys slot 0)."""
        profile = json.loads((FIXTURES / "profiles" / "full.json").read_text())
        data = pr.build(profile, MATRIX, load_effect, load_macro)
        slot = lambda table, i: table[i * 4]
        self.assertEqual([slot(data.keys, i) for i in (5, 6, 7)], [0, 1, 0])     # COMBO, MOUSE, COMBO
        self.assertEqual(slot(data.fn_keys, 2), 0)                                # Fn+2 → COMBO = slot 0
        profile["FnKeySet"][1]["Task"]["Data"]["GUID"] = "TEST-MACRO-MOUSE"
        data = pr.build(profile, MATRIX, load_effect, load_macro)
        self.assertEqual(slot(data.fn_keys, 2), 1)
        self.assertEqual(slot(data.keys, 5), 0)                                   # unaffected by Fn+2's macro

    def test_without_lighting(self):
        profile = json.loads((FIXTURES / "profiles" / "full.json").read_text())
        ops = {x[0] for x in pr.packets(pr.build(profile, MATRIX, load_effect, load_macro, lighting=False))}
        self.assertFalse(ops & {p.OP_LIGHT_KEYS, p.OP_LIGHT_DATA})

    def test_js_parse_int(self):
        self.assertEqual(pr.js_parse_int("0x0A010001", 16), 0x0A010001)
        self.assertEqual(pr.js_parse_int("C:\\x", 16), 0xC)
        self.assertIsNone(pr.js_parse_int("xyz", 16))
        self.assertEqual(pr.js_parse_int("12abc", 10), 12)


if __name__ == "__main__":
    unittest.main()
