"""Shared GUI plumbing: the app state, background keyboard access, small helpers."""
import json
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QWidget

from .. import device, session
from ..store import CONFIG, SLOT_MODES, Profile, Store
from ..vendordata import VendorData, VendorDataMissing

SETTINGS = CONFIG / "gui.json"
VARIANT_WORDS = ("VOL", "MUTE", "Vol", "Mute", "Left Space", "Right Space")     # knob / split-space key variants


def is_variant(key: dict) -> bool:
    return any(w in key["KeyName"] for w in VARIANT_WORDS)


class Settings:
    def __init__(self):
        try:
            self.data = json.loads(SETTINGS.read_text())
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(self.data, indent=1))


class Keyboard(QObject):
    """Runs keyboard calls on one background thread (never interleaved, never blocking the UI) and delivers the
    results on the UI thread. Watches for the keyboard being plugged in or out."""

    connected = Signal(object)         # session.KeyboardInfo, or None when it goes away
    _done = Signal(object, object, object, object)

    def __init__(self):
        super().__init__()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gk6x")
        self._kb: device.Keyboard | None = None
        self.info: session.KeyboardInfo | None = None
        self._done.connect(self._deliver)
        self._watch = QTimer(self)
        self._watch.timeout.connect(self._check)
        self._watch.start(1500)
        QTimer.singleShot(0, self._check)

    def run(self, fn: Callable[[device.Keyboard], object], ok: Callable | None = None, err: Callable | None = None):
        def job():
            try:
                if self._kb is None:
                    raise device.DeviceError("the keyboard isn't connected (it needs the USB cable)")
                return fn(self._kb), None
            except Exception as e:
                traceback.print_exc()
                if isinstance(e, (OSError, device.DeviceError)):
                    self._drop_sync()
                return None, e
        self._pool.submit(job).add_done_callback(lambda f: self._done.emit(ok, err, *f.result()))

    def _deliver(self, ok, err, value, error):
        if error is not None:
            if err:
                err(error)
        elif ok:
            ok(value)

    def _check(self):
        def job():
            present = [f for f in device.find() if f.pid == device.p.PID_WIRED]
            if self._kb is not None:
                if not any(f.path == self._kb.found.path for f in present):
                    self._drop_sync()
                return None, None
            if not present:
                return None, None
            try:
                self._kb = device.Keyboard(present[0])
                self.info = session.identify(self._kb)
                self.connected.emit(self.info)
            except Exception as e:
                self._drop_sync()
                return None, e
            return None, None
        self._pool.submit(job)

    def _drop_sync(self):
        if self._kb is not None:
            try:
                self._kb.close()
            except Exception:
                pass
            self._kb = None
        if self.info is not None:
            self.info = None
            self.connected.emit(None)

    def shutdown(self):
        self._watch.stop()
        self._pool.submit(self._drop_sync)
        self._pool.shutdown(wait=True, cancel_futures=True)


class AppState(QObject):
    """What the pages share: the keyboard model's data and OpenGK6X's stored profiles and macros."""

    profiles_changed = Signal()
    macros_changed = Signal()
    model_changed = Signal()
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = Settings()
        self.store = Store()
        try:
            self.vendor: VendorData | None = VendorData()
        except VendorDataMissing:
            self.vendor = None
        self.keyboard = Keyboard()
        self.model: int | None = None
        self.keymap: list[dict] = []
        self.config: dict = {}
        self.profiles: dict[str, Profile | None] = {s: None for s in SLOT_MODES}
        self.macros = self.store.macros()
        self.matrix = tuple(self.settings.get("matrix", (16, 8)))
        self.keyboard.connected.connect(self._on_connected)
        last = self.settings.get("model")
        if last:
            self.set_model(int(last))

    # model / keyboard
    def set_model(self, model: int):
        if self.vendor is None:
            return
        try:
            self.keymap = self.vendor.keymap(model)
            self.config = self.vendor.model_config(model)
        except VendorDataMissing as e:
            self.message.emit(str(e))
            return
        self.model = model
        self.profiles = self.store.profiles(model)
        self.settings.set("model", model)
        self.model_changed.emit()
        self.profiles_changed.emit()

    def _on_connected(self, info):
        if info is None:
            self.message.emit("Keyboard disconnected")
            return
        self.matrix = info.matrix
        self.settings.set("matrix", list(info.matrix))
        if info.model != self.model:
            self.set_model(info.model)
        else:
            self.profiles_changed.emit()
        self.message.emit(f"Keyboard connected (firmware {info.firmware_version})")

    # data
    def save_profiles(self):
        self.store.save_profiles(self.model, self.profiles)
        self.profiles_changed.emit()

    def save_macros(self):
        self.store.save_macros(self.macros)
        self.macros_changed.emit()
        self.profiles_changed.emit()          # profiles using a macro now differ from the keyboard

    def status(self, slot: str) -> str:
        try:
            return session.status(self.store, self.vendor, self.model, slot, self.profiles[slot], self.matrix)
        except ValueError:
            return session.CHANGED                 # e.g. a macro it uses was deleted: needs attention anyway

    def key(self, name: str) -> dict | None:
        return next((k for k in self.keymap if k["KeyName"] == name), None)

    def default_binding(self, slot: str, key_name: str, fn: bool) -> int | None:
        """What the key does in this slot by default (the model's default profile)."""
        key = self.key(key_name)
        if key is None or self.vendor is None:
            return None
        layer = self.vendor.base_profile(self.model).get("FnKeySet" if fn else "KeySet") or []
        for e in layer:
            if int(e["Index"]) == key["LogicCode"]:
                try:
                    return int(e["DriverValue"], 16)
                except (TypeError, ValueError):
                    return None
        return None


# --- small helpers ------------------------------------------------------------------------------

def hbox(*widgets, stretch=True, margins=0) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(margins, margins, margins, margins)
    for x in widgets:
        if isinstance(x, int):
            lay.addSpacing(x)
        else:
            lay.addWidget(x)
    if stretch:
        lay.addStretch(1)
    return w


def heading(text: str) -> QLabel:
    lbl = QLabel(text)
    f = lbl.font()
    f.setPointSizeF(f.pointSizeF() * 1.35)
    f.setBold(True)
    lbl.setFont(f)
    return lbl


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: palette(placeholder-text);")
    return lbl


def confirm(parent, title: str, text: str, ok: str = "Continue") -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Cancel, parent)
    button = box.addButton(ok, QMessageBox.AcceptRole)
    box.setDefaultButton(QMessageBox.Cancel)
    box.exec()
    return box.clickedButton() is button


def error(parent, text: str):
    QMessageBox.warning(parent, "OpenGK6X", text)


def info(parent, text: str):
    QMessageBox.information(parent, "OpenGK6X", text)
