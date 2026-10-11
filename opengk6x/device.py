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

    def request(self, report: bytes, timeout: float = 1.0) -> bytes:
        """Send one report and return the keyboard's reply to it (same op and sub).

        The keyboard also sends reports nobody asked for (e.g. key callbacks); those are skipped.
        """
        op, sub = report[0], report[1]
        self._dev.write(b"\x00" + report)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = bytes(self._dev.read(p.REPORT_LEN, 100))
            if p.is_reply(r, op, sub):
                if not p.crc_ok(r):
                    raise DeviceError(f"bad CRC in reply to {op:02x} {sub:02x}")
                return r
        raise DeviceError(f"no reply to {op:02x} {sub:02x}")

    def info(self) -> dict:
        buffers = p.parse_buffers(self.request(p.info_request(p.INFO_BUFFERS)))
        fw = p.parse_firmware(self.request(p.info_request(p.INFO_FIRMWARE)))
        model = p.parse_model(self.request(p.info_request(p.INFO_MODEL)))
        return {"link": self.found.link, "path": self.found.path.decode(), "model_id": model,
                "firmware_id": fw.id, "firmware_version": fw.version, "buffers": buffers}
