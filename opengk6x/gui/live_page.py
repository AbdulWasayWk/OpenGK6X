"""Live page: online mode run by the app (lighting at full speed, typing effects, key actions on this PC)."""
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import effects as fx
from .. import live as lv
from .. import protocol as p
from ..online import Online
from .common import AppState, error, hbox, heading, hint
from .effect_widgets import ColorButton

AUTOSTART = Path.home() / ".config/autostart/opengk6x-live.desktop"


class LiveController(QObject):
    """Runs live mode: renders frames on the UI thread, sends them through the keyboard worker."""

    changed = Signal()                     # started / stopped
    _keys = Signal(object, object)         # pressed, released (from the worker thread)
    _mode = Signal(int)

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.config = lv.LiveConfig()
        self.running = False
        self.online: Online | None = None
        self.renderer: lv.Renderer | None = None
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._keys.connect(self._on_keys)
        self._mode.connect(self._on_mode)
        state.model_changed.connect(self.load)
        state.keyboard.connected.connect(lambda info: None if info else self._lost("the keyboard was unplugged"))
        self.load()

    # config
    def load(self):
        if self.state.model is not None:
            fresh = not (self.state.store.root / str(self.state.model) / "live.json").is_file()
            self.config = lv.LiveConfig.load(self.state.store.root, self.state.model)
            if fresh and self.state.vendor:          # start with something nice rather than dark keys
                lib = {e["Name"]: e["GUID"] for e in self.state.vendor.effect_library(self.state.model)}
                self.config.effect = lib.get("Rainbow Waves")

    def save(self):
        if self.state.model is not None:
            self.config.save(self.state.store.root, self.state.model)
        if self.renderer:
            self.renderer.config = self.config

    def _effect(self) -> dict | None:
        guid = self.config.effect
        if not guid:
            return None
        mine = self.state.store.effects()
        if guid in mine:
            return mine[guid]
        text = self.state.vendor.effect(guid)
        return json.loads(text) if text else None

    def _action_indexes(self) -> dict[int, dict]:
        out = {}
        for name, action in self.config.actions.items():
            key = self.state.key(name)
            if key:
                out[key["LogicCode"]] = action
        return out

    # running
    def start(self):
        if self.state.keyboard.info is None:
            error(None, "Connect the keyboard with its USB cable first.")
            return
        self.renderer = lv.Renderer(self.state.display_keys(), self._effect(), self.config)
        base = self.state.vendor.base_profile(self.state.model)
        actions = set(self._action_indexes())

        def job(kb):
            self.online = Online(kb, base)
            self.online.on_keys = lambda down, up: self._keys.emit(down, up)
            self.online.on_mode = lambda m: self._mode.emit(m)
            self.online.start(actions)

        def ok(_):
            self.running = True
            self._timer.start(fx.TICK_MS)
            self.state.message.emit("Live mode on")
            self.changed.emit()

        self.state.keyboard.run(job, ok, lambda e: error(None, f"Couldn't start live mode: {e}"))

    def restart(self):
        if self.running:
            self._timer.stop()
            self.running = False
            self.start()

    def stop(self, then=None, mode: int | None = None):
        """Leave live mode (back to the configured profile, or `mode`), then call `then`."""
        if not self.running:
            if then:
                then()
            return
        self._timer.stop()
        self.running = False
        target = mode if mode is not None else lv.EXIT_MODES.get(self.config.exit, p.MODE_STANDARD)
        online = self.online

        def job(kb):
            online.stop(target)
            kb.on_report = None

        def done(_=None):
            self.state.message.emit("Live mode off")
            self.changed.emit()
            if then:
                then()

        self.state.keyboard.run(job, done, lambda e: done())

    def stop_blocking(self):
        """For quitting: leave online mode before the app exits."""
        if self.running and self.online:
            self._timer.stop()
            self.running = False
            target = lv.EXIT_MODES.get(self.config.exit, p.MODE_STANDARD)
            fut = self.state.keyboard._pool.submit(lambda: self.online.stop(target))
            try:
                fut.result(timeout=3)
            except Exception:
                pass

    def _lost(self, why: str):
        if self.running:
            self._timer.stop()
            self.running = False
            if self.online:
                self.online.active = False
            self.state.message.emit(f"Live mode ended: {why}")
            self.changed.emit()

    def _tick(self):
        if self._busy or not self.running or not self.renderer:
            return
        frame = self.renderer.frame()
        self._busy = True

        def job(kb):
            self.online.show(frame)

        def done(_=None):
            self._busy = False

        def failed(e):
            self._busy = False
            self._lost(str(e))

        self.state.keyboard.run(job, done, failed)

    def _on_mode(self, mode: int):
        if mode != p.MODE_ONLINE:
            self._lost("the keyboard switched to another profile")

    # keys
    def _on_keys(self, pressed, released):
        if self.renderer:
            for i in pressed:
                self.renderer.press(i)
        actions = self._action_indexes()
        for i in pressed:
            if i in actions:
                self._run(actions[i])

    def _run(self, action: dict):
        kind, value = action.get("type"), action.get("value", "")
        if kind == "command" and value:
            subprocess.Popen(["sh", "-c", value], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif kind == "url" and value:
            QDesktopServices.openUrl(QUrl.fromUserInput(value, str(Path.home())))
        elif kind == "text":
            self._play([("keys", s) for s in lv.text_states(value)])
        elif kind == "macro":
            macro = self.state.macros.get(value)
            if macro:
                self._play(lv.macro_states(macro.steps) + [("keys", (0, [])), ("mouse", 0)])

    def _play(self, events: list):
        """Send key states through the keyboard, waiting where the macro says (frames keep going meanwhile)."""
        batch = []
        while events and events[0][0] != "wait":
            batch.append(events.pop(0))
        rest = events[1:] if events else []
        wait = events[0][1] if events else 0

        def job(kb):
            for kind, value in batch:
                if not self.online:
                    return
                if kind == "keys":
                    self.online.send_keys(*value)
                else:
                    self.online.send_mouse(value)

        def next_(_=None):
            if rest and self.running:
                QTimer.singleShot(int(wait), lambda: self._play(list(rest)))

        if batch:
            self.state.keyboard.run(job, next_, lambda e: None)
        else:
            next_()


class ActionDialog(QDialog):
    def __init__(self, state: AppState, parent=None, key: str = "", action: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Key action")
        self.state = state
        f = QFormLayout(self)
        self.key = QComboBox()
        for k in state.display_keys():
            if k["KeyName"] != "Fn":
                self.key.addItem(k.get("Show") or k["KeyName"], k["KeyName"])
        self.key.setCurrentIndex(max(0, self.key.findData(key)))
        f.addRow("Key", self.key)
        self.type = QComboBox()
        for t, text in lv.ACTION_TYPES.items():
            self.type.addItem(text, t)
        f.addRow("Does", self.type)
        self.value = QLineEdit()
        self.macro = QComboBox()
        for name in sorted(state.macros, key=str.lower):
            self.macro.addItem(name)
        f.addRow("", self.value)
        f.addRow("", self.macro)
        self.help = hint("")
        f.addRow("", self.help)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        f.addRow(buttons)
        self.type.currentIndexChanged.connect(self._type_changed)
        if action:
            self.type.setCurrentIndex(max(0, self.type.findData(action.get("type"))))
            if action.get("type") == "macro":
                self.macro.setCurrentText(action.get("value", ""))
            else:
                self.value.setText(action.get("value", ""))
        self._type_changed()

    def _type_changed(self):
        t = self.type.currentData()
        form = self.layout()
        form.setRowVisible(self.value, t != "macro")
        form.setRowVisible(self.macro, t == "macro")
        self.value.setPlaceholderText({"command": "e.g. konsole, or: playerctl play-pause",
                                       "url": "e.g. https://… or ~/Documents", "text": "text to type"}.get(t, ""))
        self.help.setText({"command": "Runs with sh -c, as you.",
                           "url": "Opens with your default app.",
                           "text": "Typed by the keyboard itself (US layout).",
                           "macro": "Played by the PC: any length, from the Macros page."}[t])

    def result_action(self) -> tuple[str, dict]:
        t = self.type.currentData()
        value = self.macro.currentText() if t == "macro" else self.value.text()
        return self.key.currentData(), {"type": t, "value": value}


class LivePage(QWidget):
    title = "Live mode"
    icon = "media-playback-start"

    def __init__(self, state: AppState, controller: LiveController):
        super().__init__()
        self.state = state
        self.live = controller
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.addWidget(heading("Live mode"))
        lay.addWidget(hint("While live mode is on, OpenGK6X drives the keyboard: lighting at full speed, effects "
                           "that react to typing, and keys that do things on this computer. It needs OpenGK6X "
                           "running (closing the window keeps it in the tray) and the USB cable. Applying or "
                           "switching a profile ends it."))
        self.toggle = QPushButton()
        self.toggle.setMinimumHeight(36)
        self.toggle.clicked.connect(lambda: self.live.stop() if self.live.running else self.live.start())
        self.status = QLabel()
        lay.addWidget(hbox(self.toggle, self.status))

        box = QGroupBox("Lighting")
        f = QFormLayout(box)
        self.effect = QComboBox()
        f.addRow("Effect", self.effect)
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(10, 400)
        f.addRow("Speed", self.speed)
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        f.addRow("Brightness", self.brightness)
        lay.addWidget(box)

        box = QGroupBox("Typing effect")
        f = QFormLayout(box)
        self.typing = QComboBox()
        for k, text in lv.TYPING_KINDS.items():
            self.typing.addItem(text, k)
        f.addRow("Effect", self.typing)
        self.typing_color = ColorButton()
        f.addRow("Color", self.typing_color)
        self.duration = QSpinBox()
        self.duration.setRange(100, 5000)
        self.duration.setSingleStep(100)
        self.duration.setSuffix(" ms")
        f.addRow("Fades in", self.duration)
        lay.addWidget(box)

        box = QGroupBox("Key actions (only while live mode is on)")
        v = QVBoxLayout(box)
        self.actions = QTableWidget(0, 2)
        self.actions.setHorizontalHeaderLabels(["Key", "Does"])
        self.actions.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.actions.setSelectionBehavior(QTableWidget.SelectRows)
        self.actions.setMinimumHeight(140)
        self.actions.cellDoubleClicked.connect(lambda row, _c: self._edit_action(row))
        v.addWidget(self.actions)
        add = QPushButton("Add…")
        add.clicked.connect(lambda: self._edit_action(None))
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove_action)
        v.addWidget(hbox(add, remove))
        v.addWidget(hint("Action keys don't type while live mode is on."))
        lay.addWidget(box)

        box = QGroupBox("When live mode ends")
        f = QFormLayout(box)
        self.exit = QComboBox()
        for k, text in (("standard", "Standard profile"), ("1", "Profile 1"), ("2", "Profile 2"), ("3", "Profile 3")):
            self.exit.addItem(text, k)
        f.addRow("Switch the keyboard to", self.exit)
        self.autostart = QCheckBox("Start OpenGK6X in the tray when I log in, with live mode on")
        self.autostart.setChecked(AUTOSTART.is_file())
        self.autostart.toggled.connect(self._autostart)
        f.addRow(self.autostart)
        lay.addWidget(box)
        lay.addStretch(1)

        for w, sig in ((self.effect, "currentIndexChanged"), (self.typing, "currentIndexChanged"),
                       (self.exit, "currentIndexChanged"), (self.speed, "valueChanged"),
                       (self.brightness, "valueChanged"), (self.duration, "valueChanged")):
            getattr(w, sig).connect(self._changed)
        self.typing_color.changed.connect(self._changed)
        controller.changed.connect(self._show_state)
        state.model_changed.connect(self._load)
        state.keyboard.connected.connect(lambda _i: self._show_state())
        self._load()

    def _load(self):
        self._loading = True
        cfg = self.live.config
        self.effect.clear()
        self.effect.addItem("None (dark: typing effect only)", None)
        for guid, e in sorted(self.state.store.effects().items(), key=lambda kv: kv[1].get("Name", "").lower()):
            self.effect.addItem(f"Mine: {e.get('Name') or guid}", guid)
        if self.state.vendor and self.state.model is not None:
            for e in self.state.vendor.effect_library(self.state.model):
                self.effect.addItem(e["Name"], e["GUID"])
        self.effect.setCurrentIndex(max(0, self.effect.findData(cfg.effect)))
        self.speed.setValue(int(float(cfg.speed) * 100))
        self.brightness.setValue(int(cfg.brightness))
        t = cfg.typing or {}
        self.typing.setCurrentIndex(max(0, self.typing.findData(t.get("kind", "off"))))
        self.typing_color.set_color(t.get("color", "0xffffff"))
        self.duration.setValue(int(t.get("duration", 600)))
        self.exit.setCurrentIndex(max(0, self.exit.findData(cfg.exit)))
        self._fill_actions()
        self._loading = False
        self._show_state()

    def _changed(self, *_):
        if getattr(self, "_loading", False):
            return
        cfg = self.live.config
        effect_changed = cfg.effect != self.effect.currentData()
        cfg.effect = self.effect.currentData()
        cfg.speed = self.speed.value() / 100
        cfg.brightness = self.brightness.value()
        cfg.typing = {"kind": self.typing.currentData(), "color": self.typing_color.color(),
                      "duration": self.duration.value()}
        cfg.exit = self.exit.currentData()
        self.live.save()
        if effect_changed and self.live.renderer:
            self.live.renderer = lv.Renderer(self.state.display_keys(), self.live._effect(), cfg)

    def _fill_actions(self):
        self.actions.setRowCount(0)
        labels = {k["KeyName"]: k.get("Show") or k["KeyName"] for k in self.state.display_keys()}
        for name, action in sorted(self.live.config.actions.items()):
            row = self.actions.rowCount()
            self.actions.insertRow(row)
            item = QTableWidgetItem(labels.get(name, name))
            item.setData(Qt.UserRole, name)
            self.actions.setItem(row, 0, item)
            text = f"{lv.ACTION_TYPES.get(action.get('type'), '?')}: {action.get('value', '')}"
            self.actions.setItem(row, 1, QTableWidgetItem(text))

    def _edit_action(self, row):
        name = self.actions.item(row, 0).data(Qt.UserRole) if row is not None else ""
        dlg = ActionDialog(self.state, self, name, self.live.config.actions.get(name))
        if dlg.exec():
            key, action = dlg.result_action()
            if name and name != key:
                self.live.config.actions.pop(name, None)
            self.live.config.actions[key] = action
            self.live.save()
            self._fill_actions()
            self.live.restart()

    def _remove_action(self):
        row = self.actions.currentRow()
        if row >= 0:
            self.live.config.actions.pop(self.actions.item(row, 0).data(Qt.UserRole), None)
            self.live.save()
            self._fill_actions()
            self.live.restart()

    def _show_state(self):
        on = self.live.running
        self.toggle.setText("Stop live mode" if on else "Start live mode")
        self.toggle.setEnabled(on or self.state.keyboard.info is not None)
        self.status.setText("● On" if on else ("○ Off" if self.state.keyboard.info else
                                               "○ Off — connect the keyboard's USB cable"))

    def _autostart(self, on: bool):
        if on:
            exe = shutil.which("opengk6x-gui")
            cmd = f"{shlex.quote(exe)} --tray" if exe else f"{shlex.quote(sys.executable)} -m opengk6x.gui --tray"
            AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=OpenGK6X live mode\n"
                                 f"Exec={cmd}\nIcon=opengk6x\nX-GNOME-Autostart-enabled=true\n")
        else:
            AUTOSTART.unlink(missing_ok=True)
