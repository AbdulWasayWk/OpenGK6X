"""Effects: player, generators, and the custom effects list compiled like the official app does."""
import json
import unittest

from opengk6x import effects as fx
from opengk6x import profile as pr
from opengk6x import protocol as p

KEYMAP = [{"KeyName": f"K{i}", "LogicCode": i, "LocationCode": i,
           "Position": {"Left": 40 * (i % 10), "Top": 40 * (i // 10), "Width": 38, "Height": 38}} for i in range(30)]
KEYMAP.append({"KeyName": "Knob", "LogicCode": 113, "LocationCode": 999,
               "Position": {"Left": 0, "Top": 0, "Width": 20, "Height": 20}})


class TestPlayer(unittest.TestCase):
    def test_static_and_unlit(self):
        e = {"Frames": [{"Count": 1, "Data": {"0": "0x123456", "1": "0xffffff"}}],
             "LEConfigs": [{"Type": 0, "Count": 1, "Color": "0xff0000", "Keys": [1]}]}
        self.assertEqual(fx.Player(e).step(), {0: (0x12, 0x34, 0x56), 1: (255, 0, 0)})

    def test_cycle_turns_hue(self):
        e = fx.make("cycle", {"color": "0xff0000", "speed": 4}, KEYMAP, "c")
        pl = fx.Player(e)
        seen = [pl.step()[0] for _ in range(5)]
        self.assertEqual(seen[0], (255, 0, 0))
        self.assertEqual(seen[2], (0, 255, 255))          # 180° after 2 of 4 ticks
        self.assertEqual(seen[4], (255, 0, 0))

    def test_breathing(self):
        e = fx.make("breathing", {"color": "0xff0000", "speed": 2, "hold": 1}, KEYMAP, "b")
        pl = fx.Player(e)
        reds = [pl.step()[0][0] for _ in range(8)]
        self.assertEqual(reds, [0, 128, 255, 255, 128, 0, 0, 128])

    def test_frame_counts(self):
        e = {"Frames": [{"Count": 2, "Data": {"0": "0xff0000"}}, {"Data": {"1": "0x00ff00"}}], "LEConfigs": []}
        pl = fx.Player(e)
        self.assertEqual([sorted(pl.step()) for _ in range(4)], [[0], [0], [1], [0]])


class TestMake(unittest.TestCase):
    def test_kinds_compile(self):
        for kind in fx.KINDS:
            params = {"colors": {"3": "0x00ff00"}, "background": "0x101010"} if kind == "keys" else {}
            e = fx.make(kind, params, KEYMAP, kind)
            self.assertNotIn(999, [int(k) for f in e["Frames"] for k in f["Data"]])
            index, light = pr.light_data({"ModeLE": {"GUID": "G"}, "KeySet": []}, lambda g: json.dumps(e))
            self.assertIsNotNone(light, kind)
            self.assertEqual(e["OpenGK6X"]["kind"], kind)

    def test_keys_background(self):
        e = fx.make("keys", {"colors": {"3": "0x00ff00"}, "background": "0x101010"}, KEYMAP, "k")
        frame = fx.Player(e).step()
        self.assertEqual(frame[3], (0, 255, 0))
        self.assertEqual(frame[4], (16, 16, 16))
        self.assertEqual(len(frame), 30)

    def test_wave_bands(self):
        e = fx.make("wave", {"direction": "right", "speed": 60}, KEYMAP, "w")
        self.assertGreater(len(e["LEConfigs"]), 4)
        self.assertTrue(all(c["Type"] == 1 for c in e["LEConfigs"]))


class TestCustomList(unittest.TestCase):
    def test_standard_profile_packets(self):
        effects = {g: fx.make("solid", {"color": "0x0000ff"}, KEYMAP, g, g) for g in ("A", "B")}
        prof = fx.standard_profile([effects["A"], effects["B"], {"GUID": "MISSING"}])
        data = pr.build(prof, (16, 8), lambda g: json.dumps(effects[g]) if g in effects else None, lambda g: None)
        packets = pr.packets(data)
        ops = [(x[0], x[1]) for x in packets]
        self.assertTrue(all(sub == p.MODE_STANDARD for _, sub in ops))
        self.assertNotIn(p.OP_SET_MODE, [op for op, _ in ops])           # no profile switch
        self.assertNotIn(p.OP_KEYS, [op for op, _ in ops])               # standard keys never written
        self.assertEqual(data.light[:32][16:32].count(0xFF), 0)           # two effect headers, missing one skipped
        self.assertEqual(data.light[32:48], b"\xff" * 16)


if __name__ == "__main__":
    unittest.main()
