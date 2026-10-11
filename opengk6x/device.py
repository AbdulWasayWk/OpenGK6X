"""hidapi transport for the GK6X vendor interface: open, request/response, read-only info."""
import time
from dataclasses import dataclass

import hid

from . import protocol as p


@dataclass(frozen=True)
class Found:
    path: bytes
    pid: int
    product: str

    @property
    def link(self) -> str:
        return "wired" if self.pid == p.PID_WIRED else "2.4 GHz dongle"


def find() -> list[Found]:
    """Vendor (config) interfaces of every connected keyboard/dongle, wired first."""
    out = []
    for pid in (p.PID_WIRED, p.PID_DONGLE):
        for info in hid.enumerate(p.VID, pid):
            if info["usage_page"] == p.USAGE_PAGE:
                out.append(Found(info["path"], pid, info["product_string"] or ""))
    return out


class DeviceError(Exception):
    pass


class Keyboard:
    def __init__(self, found: Found):
        self.found = found
        self.on_report = None          # called with reports nobody asked for (key reports, mode changes)
        self._dev = hid.device()
        try:
            self._dev.open_path(found.path)
        except OSError as e:
            raise DeviceError(f"can't open {found.path.decode()} ({found.link}): {e}. "
                              "Install packaging/70-opengk6x.rules (see README).") from e

    def close(self):
        self._dev.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def request(self, report: bytes, timeout: float = 2.0, match_sub: bool = True, check_crc: bool = True) -> bytes:
        """Send one report and return the keyboard's reply to it (same op, and same sub unless match_sub=False).

        The keyboard also sends reports nobody asked for (e.g. key callbacks, `0B` when the user switches profile);
        those are skipped.
        """
        op, sub = report[0], report[1]
        self._dev.write(b"\x00" + report)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = bytes(self._dev.read(p.REPORT_LEN, 100))
            if len(r) >= p.REPORT_LEN and r[0] == op and (r[1] == sub or not match_sub):
                if check_crc and not p.crc_ok(r):
                    raise DeviceError(f"bad CRC in reply to {op:02x} {sub:02x}")
                return r
            if r and self.on_report:
                self.on_report(r)
        raise DeviceError(f"no reply to {op:02x} {sub:02x}")

    def poll(self, timeout_ms: int = 1, limit: int = 64):
        """Hand reports the keyboard sent on its own (key reports in online mode) to `on_report`. Waits at most
        `timeout_ms` for each (note: hidapi's read with timeout 0 blocks until something arrives)."""
        for _ in range(limit):
            r = bytes(self._dev.read(p.REPORT_LEN, max(1, timeout_ms)))
            if not r:
                return
            if self.on_report:
                self.on_report(r)

    def matrix(self) -> tuple[int, int]:
        return p.parse_matrix(self.request(p.info_request(p.INFO_MATRIX)))

    def model_id(self) -> int:
        return p.parse_model(self.request(p.info_request(p.INFO_MODEL)))

    def set_mode(self, mode: int) -> bytes:
        return self.request(p.set_mode(mode), match_sub=False, check_crc=False)

    def write(self, packets: list[bytes], progress=None) -> list[bytes]:
        """Send write packets one by one, each after the previous one's reply (like the app, which also pauses
        1 ms between chunks on this firmware). Returns the replies. Write replies aren't documented, so they're
        returned as they are rather than checked; a missing reply stops the write."""
        replies = []
        for i, pkt in enumerate(packets):
            replies.append(self.request(pkt, match_sub=False, check_crc=False))
            time.sleep(0.001)
            if progress:
                progress(i + 1, len(packets))
        return replies

    def info(self) -> dict:
        fw = p.parse_firmware(self.request(p.info_request(p.INFO_FIRMWARE)))
        model = self.model_id()
        matrix = self.matrix()
        return {"link": self.found.link, "path": self.found.path.decode(), "model_id": model,
                "firmware_id": fw.id, "firmware_version": fw.version, "matrix": matrix}
