"""Online ("driver") mode: the PC drives the keyboard while OpenGK6X runs (docs/PROTOCOL.md, online mode).

Entering it mirrors the official app (src/libs/driver.js setOnlineMode / setOnLineProfile): ping, `0B 05`, ping,
key reports on (`15 03 01`), then the online key table (`16 01`, same 512-byte format as profile key tables), the
key-press lighting index (`16 03`, all FF) and the lighting config (`17 01`). While online the keyboard expects a
ping at least every 2 s, sends `15 04` key reports, and shows frames sent with `1A`. Leaving (app sdk.js
ChangeMode): key reports off, 200 ms, then `0B <mode>`.
"""
import time

from . import device
from . import profile as pr
from . import protocol as p

PING_EVERY = 2.0


class Online:
    def __init__(self, kb: device.Keyboard, base_profile: dict):
        self.kb = kb
        self.base = base_profile
        self.held: set[int] = set()
        self.on_keys = None             # callback(pressed: set, released: set)
        self._last_ping = 0.0
        self.active = False
        kb.on_report = self._report

    def _report(self, r: bytes):
        held = p.parse_key_report(r)
        if held is None:
            return
        pressed, released = held - self.held, self.held - held
        self.held = held
        if self.on_keys and (pressed or released):
            self.on_keys(pressed, released)

    def start(self):
        kb = self.kb
        kb.request(p.ping(), match_sub=False, check_crc=False)
        kb.set_mode(p.MODE_ONLINE)
        self.active = True
        kb.request(p.ping(), match_sub=False, check_crc=False)
        kb.request(p.key_reports(True), match_sub=False, check_crc=False)
        cols, rows = kb.matrix()
        table = pr.key_table(self.base.get("KeySet") or [], cols * rows * 4, lambda i, k: 0xFF, fill=0)
        light_index = b"\xff" * (cols * rows)
        kb.write(p.chunks(p.OP_DRIVER_KEYS, 0x01, table) + p.chunks(p.OP_DRIVER_KEYS, 0x03, light_index) +
                 [p.driver_le_config()])
        self._last_ping = time.monotonic()

    def show(self, colors: dict[int, tuple[int, int, int]]):
        """Show one lighting frame (LED index → RGB)."""
        self.kb.write(p.live_frame(colors))
        self.tick()

    def tick(self):
        """Keep the keyboard online and collect key reports; call often."""
        if time.monotonic() - self._last_ping >= PING_EVERY:
            self.kb.request(p.ping(), match_sub=False, check_crc=False)
            self._last_ping = time.monotonic()
        self.kb.poll()

    def stop(self, mode: int = p.MODE_STANDARD):
        """Leave online mode. Ctrl+C can't interrupt this (a half-done exit leaves the keyboard in online mode)."""
        if not self.active:
            return
        import signal
        import threading
        main = threading.current_thread() is threading.main_thread()
        old = signal.signal(signal.SIGINT, signal.SIG_IGN) if main else None
        try:
            try:
                self.kb.request(p.key_reports(False), match_sub=False, check_crc=False)
            except (OSError, device.DeviceError):
                pass
            time.sleep(0.2)
            self.kb.set_mode(mode)
            self.active = False
        finally:
            if main:
                signal.signal(signal.SIGINT, old)
