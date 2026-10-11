"""Lighting widgets: an animated effect preview on the keyboard picture, a color button, the effect editor."""
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from .. import effects as fx
from .common import hint
from .keyboard_view import KeyboardView, KeyLook


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color: str = "0xff0000", parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 26)
        self.setObjectName("swatch")
        self.clicked.connect(self._pick)
        self.set_color(color)

    def set_color(self, color: str):
        self._color = fx.hex_of(fx.rgb_of(color))
        self.setStyleSheet(f"QPushButton#swatch {{ background: #{self._color[2:]}; border: 1px solid #777;"
                           f" border-radius: 4px; }}")

    def color(self) -> str:
        return self._color

    def _pick(self):
        c = QColorDialog.getColor(QColor(f"#{self._color[2:]}"), self.window(), "Pick a color")
        if c.isValid():
            self.set_color("0x%02x%02x%02x" % (c.red(), c.green(), c.blue()))
            self.changed.emit(self._color)


class EffectPreview(QWidget):
    """The keyboard picture playing an effect (one tick every 50 ms × speed)."""

    key_clicked = Signal(str, int)       # key name, LED index (-1 if it has none)

    def __init__(self, keys: list[dict] = (), screen: dict | None = None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = KeyboardView()
        self.view.key_clicked.connect(self._clicked)
        lay.addWidget(self.view)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.player: fx.Player | None = None
        self.marked: set[int] = set()            # LEDs drawn with a selection outline (editor)
        self.set_keys(list(keys), screen)

    def set_keys(self, keys: list[dict], screen: dict | None = None):
        """Keys as drawn (layouts.display_keys); knobs have no LED and stay unlit."""
        self.keymap = keys
        self.view.set_keys(keys, screen)
        self._by_led = {k["LocationCode"]: k["KeyName"] for k in keys
                        if 0 <= k["LocationCode"] < fx.LED_COUNT and k.get("Shape") != "knob"}
        self.view.set_looks({k["KeyName"]: KeyLook("") for k in keys})

    def play(self, effect: dict | None, speed: float = 1.0):
        self.player = fx.Player(effect) if effect else None
        if self.player:
            self.timer.start(max(10, int(fx.TICK_MS / speed)))
            self._tick()
        else:
            self.timer.stop()
            self.view.set_colors({})

    def stop(self):
        self.timer.stop()

    def _tick(self):
        if self.player is None:
            return
        leds = self.player.step()
        colors = {name: QColor(*leds.get(led, (0, 0, 0))) for led, name in self._by_led.items()}
        self.view.set_colors(colors)
        self.view.set_looks({name: KeyLook("●" if led in self.marked else "") for led, name in self._by_led.items()})

    def _clicked(self, name: str):
        led = next((k["LocationCode"] for k in self.keymap if k["KeyName"] == name), -1)
        self.key_clicked.emit(name, led)


class EffectEditor(QDialog):
    """Make or change an effect from a few settings, with a live preview. Click keys to choose which ones light
    up (or, for key colors, to paint them)."""

    def __init__(self, keymap: list[dict], effect: dict | None = None, parent=None, screen: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Lighting effect")
        self.resize(1100, 720)
        self.keymap = keymap
        params = dict((effect or {}).get("OpenGK6X") or {})
        self.guid = (effect or {}).get("GUID")
        self.result_effect: dict | None = None
        leds_all = sorted(k["LocationCode"] for k in keymap if 0 <= k["LocationCode"] < fx.LED_COUNT
                          and k.get("Shape") != "knob")
        self.selection = set(params.get("leds") or leds_all)
        self.colors: dict[str, str] = dict(params.get("colors") or {})

        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit((effect or {}).get("Name") or "My effect")
        form.addRow("Name", self.name)
        self.kind = QComboBox()
        for k, text in fx.KINDS.items():
            self.kind.addItem(text, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(params.get("kind", "wave"))))
        form.addRow("Effect", self.kind)
        self.color = ColorButton(params.get("color", "0x00a0ff"))
        form.addRow("Color", self.color)
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.2, 60)
        self.speed.setSingleStep(0.5)
        self.speed.setSuffix(" s")
        form.addRow("Speed", self.speed)
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0, 10)
        self.hold.setSingleStep(0.25)
        self.hold.setSuffix(" s")
        form.addRow("Hold", self.hold)
        self.direction = QComboBox()
        for k, text in fx.DIRECTIONS.items():
            self.direction.addItem(text, k)
        self.direction.setCurrentIndex(max(0, self.direction.findData(params.get("direction", "right"))))
        form.addRow("Direction", self.direction)
        self.length = QDoubleSpinBox()
        self.length.setRange(0.25, 4)
        self.length.setSingleStep(0.25)
        self.length.setValue(float(params.get("length", 1.0)))
        form.addRow("Rainbows across", self.length)
        self.width = QSpinBox()
        self.width.setRange(1, 8)
        self.width.setValue(int(params.get("width", 2)))
        form.addRow("Band width", self.width)
        self.keys_widget = QWidget()
        keys_row = QHBoxLayout(self.keys_widget)
        keys_row.setContentsMargins(0, 0, 0, 0)
        self.scope = QButtonGroup(self)
        self.all_keys = QRadioButton("All keys")
        self.some_keys = QRadioButton("Only the keys I pick (click keys below)")
        self.scope.addButton(self.all_keys)
        self.scope.addButton(self.some_keys)
        (self.some_keys if params.get("leds") else self.all_keys).setChecked(True)
        keys_row.addWidget(self.all_keys)
        keys_row.addWidget(self.some_keys)
        keys_row.addStretch(1)
        form.addRow("Keys", self.keys_widget)
        self.paint_hint = hint("Click keys to paint them with the color above; click again to clear.")
        form.addRow("", self.paint_hint)
        self.bg_widget = QWidget()
        bg_row = QHBoxLayout(self.bg_widget)
        bg_row.setContentsMargins(0, 0, 0, 0)
        self.bg_on = QRadioButton("Off")
        self.bg_color_on = QRadioButton("Color:")
        bg_group = QButtonGroup(self)
        bg_group.addButton(self.bg_on)
        bg_group.addButton(self.bg_color_on)
        self.bg_color = ColorButton(params.get("background") or "0x202020")
        (self.bg_color_on if params.get("background") else self.bg_on).setChecked(True)
        for w in (self.bg_on, self.bg_color_on, self.bg_color):
            bg_row.addWidget(w)
        bg_row.addStretch(1)
        form.addRow("Other keys", self.bg_widget)
        lay.addLayout(form)

        self.preview = EffectPreview(keymap, screen)
        self.preview.key_clicked.connect(self._key_clicked)
        lay.addWidget(self.preview, 1)
        lay.addWidget(hint("Times are approximate: the keyboard plays effects at its own pace, which Fn + ← / → "
                           "changes."))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._speed_defaults = {"breathing": 1.0, "cycle": 6.0, "wave": 6.0, "sweep": 0.1}
        kind = params.get("kind", "wave")
        ticks = params.get("speed")
        self.speed.setValue(ticks * fx.TICK_MS / 1000 if ticks else self._speed_defaults.get(kind, 1.0))
        self.hold.setValue(params.get("hold", 5) * fx.TICK_MS / 1000)
        for w in (self.kind, self.direction):
            w.currentIndexChanged.connect(self._update)
        for w in (self.speed, self.hold, self.length):
            w.valueChanged.connect(self._update)
        self.width.valueChanged.connect(self._update)
        self.color.changed.connect(self._update)
        self.all_keys.toggled.connect(self._update)
        self.bg_color_on.toggled.connect(self._update)
        self.bg_color.changed.connect(self._update)
        self._last_kind = kind
        self._update()

    def _params(self) -> dict:
        kind = self.kind.currentData()
        ticks = lambda secs: max(1, round(secs * 1000 / fx.TICK_MS))
        p = {"color": self.color.color()}
        if kind == "keys":
            return {"colors": dict(self.colors),
                    "background": self.bg_color.color() if self.bg_color_on.isChecked() else None}
        if kind in ("breathing", "cycle", "wave", "sweep"):
            p["speed"] = ticks(self.speed.value())
        if kind == "breathing":
            p["hold"] = round(self.hold.value() * 1000 / fx.TICK_MS)
        if kind in ("wave", "sweep"):
            p["direction"] = self.direction.currentData()
        if kind == "wave":
            p["length"] = self.length.value()
            p.pop("color")
        if kind == "sweep":
            p["width"] = self.width.value()
        if self.some_keys.isChecked():
            p["leds"] = sorted(self.selection)
        return p

    def _update(self):
        kind = self.kind.currentData()
        if kind != self._last_kind and kind in self._speed_defaults:
            self.speed.blockSignals(True)
            self.speed.setValue(self._speed_defaults[kind])
            self.speed.blockSignals(False)
        self._last_kind = kind
        shown = {"color": kind in ("solid", "keys", "breathing", "cycle", "sweep"),
                 "speed": kind in ("breathing", "cycle", "wave", "sweep"), "hold": kind == "breathing",
                 "direction": kind in ("wave", "sweep"), "length": kind == "wave", "width": kind == "sweep",
                 "keys": kind != "keys", "paint": kind == "keys"}
        form = self.layout().itemAt(0).layout()
        for widget, key in ((self.color, "color"), (self.speed, "speed"), (self.hold, "hold"),
                            (self.direction, "direction"), (self.length, "length"), (self.width, "width"),
                            (self.paint_hint, "paint")):
            form.setRowVisible(widget, shown[key])
        form.setRowVisible(self.keys_widget, shown["keys"])
        form.setRowVisible(self.bg_widget, shown["paint"])
        self.speed.setToolTip({"breathing": "Time to fade in (and out)", "cycle": "Time for one full color turn",
                               "wave": "Time for the colors to go round once", "sweep": "Time per step"}.get(kind, ""))
        self.preview.marked = self.selection if (self.some_keys.isChecked() and kind != "keys") else set()
        self.preview.play(fx.make(kind, self._params(), self.keymap, self.name.text()))

    def _key_clicked(self, _name: str, led: int):
        if led < 0 or led >= fx.LED_COUNT:
            return
        if self.kind.currentData() == "keys":
            key = str(led)
            if self.colors.get(key) == self.color.color():
                del self.colors[key]
            else:
                self.colors[key] = self.color.color()
        else:
            self.some_keys.setChecked(True)
            self.selection ^= {led}
        self._update()

    def _save(self):
        name = self.name.text().strip() or "My effect"
        self.result_effect = fx.make(self.kind.currentData(), self._params(), self.keymap, name, self.guid)
        self.preview.stop()
        self.accept()

    def reject(self):
        self.preview.stop()
        super().reject()
