"""Live mode: rendering, typing effects, text and macro key states (no hardware)."""
import unittest

from opengk6x import live
from opengk6x.macros import parse_text

KEYS = [{"KeyName": f"K{i}", "LogicCode": i + 10, "LocationCode": i,
         "Position": {"Left": 42 * i, "Top": 0, "Width": 40, "Height": 40}} for i in range(10)]


class TestRenderer(unittest.TestCase):
    def test_glow_fades(self):
        cfg = live.LiveConfig(typing={"kind": "glow", "color": "0xffffff", "duration": 1000})
        r = live.Renderer(KEYS, None, cfg)
        r.press(13, now=0.0)                              # matrix 13 → LED 3
        self.assertEqual(r.frame(now=0.0)[3], (255, 255, 255))
        self.assertEqual(r.frame(now=0.5)[3], (128, 128, 128))
        self.assertEqual(r.frame(now=1.2)[3], (0, 0, 0))
        self.assertEqual(r.frame(now=0.0)[4], (0, 0, 0))

    def test_glow_color_over_an_effect(self):
        """A pressed key shows the chosen color, not a mix with the effect under it."""
        effect = {"Frames": [{"Data": {str(i): "0xffffff" for i in range(10)}}],
                  "LEConfigs": [{"Type": 0, "Color": "0x00ff00", "Keys": list(range(10))}]}
        cfg = live.LiveConfig(typing={"kind": "glow", "color": "0xff0000", "duration": 1000})
        r = live.Renderer(KEYS, effect, cfg)
        r.press(13, now=0.0)
        self.assertEqual(r.frame(now=0.0)[3], (255, 0, 0))
        self.assertEqual(r.frame(now=0.5)[3], (128, 128, 0))
        self.assertEqual(r.frame(now=0.5)[4], (0, 255, 0))

    def test_ripple_spreads(self):
        cfg = live.LiveConfig(typing={"kind": "ripple", "color": "0xff0000", "duration": 300})
        r = live.Renderer(KEYS, None, cfg)
        r.press(10, now=0.0)                              # LED 0 at x=20
        f = r.frame(now=0.07)                             # radius ≈ 42: the next key
        self.assertGreater(f[1][0], f[5][0])

    def test_effect_speed_and_brightness(self):
        effect = {"Frames": [{"Data": {str(i): "0xffffff" for i in range(10)}}],
                  "LEConfigs": [{"Type": 1, "Count": 4, "Color": "0xff0000", "Keys": list(range(10))}]}
        cfg = live.LiveConfig(typing={"kind": "off"}, brightness=50)
        r = live.Renderer(KEYS, effect, cfg)
        self.assertEqual(r.frame(now=0.0)[0], (128, 0, 0))
        self.assertEqual(r.frame(now=0.1)[0], (0, 128, 128))     # 2 ticks = 180°


class TestKeyStates(unittest.TestCase):
    def test_text(self):
        self.assertEqual(live.text_states("aB!"), [(0, [0x04]), (0, []), (2, [0x05]), (0, []), (2, [0x1E]), (0, [])])

    def test_macro(self):
        ev = live.macro_states(parse_text("+ctrl c -ctrl 50ms click:right"))
        self.assertEqual(ev, [("keys", (1, [])), ("keys", (1, [6])), ("keys", (1, [])), ("keys", (0, [])),
                              ("wait", 50), ("mouse", 2), ("mouse", 0)])

    def test_driver_value(self):
        self.assertEqual(live.driver_key_value(68), 0x0A010045)


if __name__ == "__main__":
    unittest.main()
