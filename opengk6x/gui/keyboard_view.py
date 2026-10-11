"""A picture of the keyboard, drawn from the model's key positions (keymap.js), with clickable keys.

A knob (layouts.display_keys: its three entries share one area) is drawn as one control: the dial in the middle
is the press, the sides are turn left / turn right; each part is clicked and labelled like a key."""
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

KNOB_ARROWS = {"left": "⟲", "right": "⟳"}


@dataclass
class KeyLook:
    text: str                       # what the key does (shown big)
    changed: bool = False           # differs from the default
    tooltip: str = ""


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() * (1 - t) + b.red() * t), round(a.green() * (1 - t) + b.green() * t),
                  round(a.blue() * (1 - t) + b.blue() * t))


class KeyboardView(QWidget):
    key_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumHeight(220)
        self._keys: list[dict] = []
        self._looks: dict[str, KeyLook] = {}
        self._colors: dict[str, QColor] = {}
        self._selected: str | None = None
        self._hover: str | None = None
        self._rects: dict[str, QRectF] = {}
        self._knobs: dict[str, dict] = {}       # knob name → {"rect": QRectF, "parts": {role: key name}}
        self._screen: dict | None = None
        self._screen_rect: QRectF | None = None

    # data
    def set_keys(self, keys: list[dict], screen: dict | None = None):
        """Keys to draw (layouts.display_keys) and the keyboard's screen area, if any."""
        self._keys = list(keys)
        self._screen = screen
        self._fit_height()
        self._layout()
        self.update()

    def set_looks(self, looks: dict[str, KeyLook]):
        self._looks = looks
        self.update()

    def set_colors(self, colors: dict[str, QColor]):
        """Per-key LED colors (lighting preview); empty for the normal look."""
        self._colors = colors
        self.update()

    def set_selected(self, name: str | None):
        self._selected = name
        self.update()

    # geometry
    def sizeHint(self) -> QSize:
        return QSize(960, 340)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        b = self._bounds()
        return int(w * b.height() / b.width()) + 16 if b.width() else 300

    def _bounds(self) -> QRectF:
        r = QRectF()
        for p in [k["Position"] for k in self._keys] + ([self._screen] if self._screen else []):
            r = r.united(QRectF(p["Left"], p["Top"], p["Width"], p["Height"]))
        return r.adjusted(-14, -14, 14, 14)

    def _layout(self):
        self._rects = {}
        self._knobs = {}
        b = self._bounds()
        if not self._keys or b.width() <= 0:
            return
        s = min(self.width() / b.width(), self.height() / b.height())
        ox = (self.width() - b.width() * s) / 2 - b.left() * s
        oy = (self.height() - b.height() * s) / 2 - b.top() * s
        self._scale = s
        self._panel = QRectF(ox + b.left() * s, oy + b.top() * s, b.width() * s, b.height() * s)
        for k in self._keys:
            p = k["Position"]
            r = QRectF(ox + p["Left"] * s, oy + p["Top"] * s, p["Width"] * s,
                       p["Height"] * s).adjusted(1.5 * s, 1.5 * s, -1.5 * s, -1.5 * s)
            if k.get("Shape") == "knob":
                self._knobs.setdefault(k["Knob"], {"rect": r, "parts": {}})["parts"][k["KnobRole"]] = k["KeyName"]
            else:
                self._rects[k["KeyName"]] = r
        p = self._screen
        self._screen_rect = QRectF(ox + p["Left"] * s, oy + p["Top"] * s, p["Width"] * s, p["Height"] * s
                                   ).adjusted(3 * s, 3 * s, -3 * s, -3 * s) if p else None

    max_height = 440          # tall keyboards (numpads) get narrower instead of taking the whole window

    def _fit_height(self):
        """Keep the keyboard's shape: as tall as the width needs, up to max_height (the page gives the rest to
        other widgets)."""
        if self._keys and self.width() > 0:
            want = min(self.heightForWidth(self.width()), self.max_height)
            if want != self.minimumHeight() or want != self.maximumHeight():
                self.setFixedHeight(want)

    def resizeEvent(self, e):
        self._fit_height()
        self._layout()
        super().resizeEvent(e)

    @staticmethod
    def _knob_zones(r: QRectF) -> dict[str, QRectF]:
        """A knob's parts: the round dial in the middle (press), the sides (turn left / turn right)."""
        d = min(r.height(), r.width() / 2.6) * 0.9
        c = r.center()
        dial = QRectF(c.x() - d / 2, c.y() - d / 2, d, d)
        return {"left": QRectF(r.left(), r.top(), dial.left() - r.left(), r.height()), "press": dial,
                "right": QRectF(dial.right(), r.top(), r.right() - dial.right(), r.height())}

    def _key_at(self, pos: QPointF) -> str | None:
        for knob in self._knobs.values():
            if knob["rect"].contains(pos):
                zones = self._knob_zones(knob["rect"])
                role = next((role for role in ("press", "left", "right") if zones[role].contains(pos)), "press")
                return knob["parts"].get(role)
        return next((n for n, r in self._rects.items() if r.contains(pos)), None)

    # painting
    def paintEvent(self, e):
        if not self._rects:
            return
        pal = self.palette()
        dark = pal.color(QPalette.Window).lightness() < 128
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        s = self._scale
        accent = pal.color(QPalette.Highlight)
        panel = mix(pal.color(QPalette.Window), QColor(0, 0, 0), 0.25 if dark else 0.08)
        painter.setPen(Qt.NoPen)
        painter.setBrush(panel)
        painter.drawRoundedRect(self._panel, 12 * s, 12 * s)

        if self._screen_rect is not None:
            painter.setBrush(QColor(18, 20, 24))
            painter.setPen(QPen(QColor(70, 74, 82), max(1.0, s)))
            painter.drawRoundedRect(self._screen_rect, 4 * s, 4 * s)
            painter.setPen(QColor(120, 160, 200))
            f = QFont(self.font())
            f.setPixelSize(max(7, int(10 * s)))
            painter.setFont(f)
            painter.drawText(self._screen_rect, Qt.AlignCenter, "Screen")

        key_bg = mix(pal.color(QPalette.Button), QColor(255, 255, 255) if dark else QColor(255, 255, 255),
                     0.06 if dark else 0.5)
        text = pal.color(QPalette.ButtonText)
        dim = pal.color(QPalette.PlaceholderText)
        for name, r in self._rects.items():
            key = next(k for k in self._keys if k["KeyName"] == name)
            look = self._looks.get(name, KeyLook(key.get("Show") or name))
            led = self._colors.get(name)
            bg = led if led is not None else key_bg
            if look.changed and led is None:
                bg = mix(key_bg, accent, 0.28)
            if name == self._hover:
                bg = mix(bg, accent, 0.15)
            path = QPainterPath()
            path.addRoundedRect(r, 5 * s, 5 * s)
            painter.setPen(QPen(mix(bg, QColor(0, 0, 0), 0.35), max(1.0, s)))
            painter.setBrush(bg)
            painter.drawPath(path)
            if name == self._selected:
                painter.setPen(QPen(accent, max(2.0, 3 * s)))
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(path)

            fg = (QColor(0, 0, 0) if led.lightness() > 140 else QColor(255, 255, 255)) if led is not None else text
            inner = r.adjusted(4 * s, 3 * s, -4 * s, -3 * s)
            if look.changed:
                small = QFont(self.font())
                small.setPixelSize(max(7, int(9 * s)))
                painter.setFont(small)
                painter.setPen(dim if led is None else fg)
                painter.drawText(inner, Qt.AlignLeft | Qt.AlignTop, key.get("Show") or name)
            area = inner.adjusted(0, 9 * s * 0.8, 0, 0) if look.changed else inner
            self._label(painter, look.text, area, look.changed,
                        self._changed_color(accent, dark) if look.changed and led is None else fg)
        for knob in self._knobs.values():
            self._paint_knob(painter, knob, key_bg, text, dim, accent, dark)
        painter.end()

    @staticmethod
    def _changed_color(accent: QColor, dark: bool) -> QColor:
        return accent.lighter(130) if dark else accent.darker(120)

    def _label(self, painter: QPainter, text: str, area: QRectF, bold: bool, color: QColor):
        text = text.replace("+", "+\u200b")
        painter.setFont(self._fit(text, area, 12 * self._scale if len(text) <= 3 else 11 * self._scale, bold))
        painter.setPen(color)
        painter.drawText(area, Qt.AlignCenter | Qt.TextWordWrap, text)

    def _paint_knob(self, painter: QPainter, knob: dict, key_bg: QColor, fg: QColor, dim: QColor, accent: QColor,
                    dark: bool):
        s = self._scale
        r, parts = knob["rect"], knob["parts"]
        zones = self._knob_zones(r)
        active = next((role for role, name in parts.items() if name == self._selected), None)
        looks = {role: self._looks.get(name) or KeyLook("") for role, name in parts.items()}

        def fill(role: str, base: QColor) -> QColor:
            c = mix(base, accent, 0.28) if looks[role].changed else base
            if parts.get(role) == self._hover:
                c = mix(c, accent, 0.15)
            return mix(c, accent, 0.2) if role == active else c

        housing = QPainterPath()
        housing.addRoundedRect(r, 5 * s, 5 * s)
        edge = QPen(mix(key_bg, QColor(0, 0, 0), 0.35), max(1.0, s))
        painter.setPen(edge)
        painter.setBrush(key_bg)
        painter.drawPath(housing)
        painter.save()
        painter.setClipPath(housing)
        painter.setPen(Qt.NoPen)
        for role in ("left", "right"):
            painter.setBrush(fill(role, key_bg))
            painter.drawRect(zones[role])
        painter.restore()
        for role, arrow in KNOB_ARROWS.items():
            z = zones[role].adjusted(3 * s, 2 * s, -3 * s, -2 * s)
            look = looks[role]
            f = QFont(self.font())
            f.setPixelSize(max(8, int(13 * s)))
            painter.setFont(f)
            painter.setPen(dim)
            if not look.text or z.width() < 28:            # small knobs: arrows only (labels in the tooltip)
                painter.drawText(z, Qt.AlignCenter, arrow)
                continue
            top = QRectF(z.left(), z.top(), z.width(), z.height() * 0.36)
            painter.drawText(top, Qt.AlignCenter, arrow)
            self._label(painter, look.text, QRectF(z.left(), top.bottom(), z.width(), z.bottom() - top.bottom()),
                        look.changed, self._changed_color(accent, dark) if look.changed else fg)

        dial = zones["press"]
        base = mix(key_bg, QColor(255, 255, 255), 0.1) if dark else mix(key_bg, QColor(0, 0, 0), 0.1)
        painter.setPen(edge)
        painter.setBrush(fill("press", base))
        painter.drawEllipse(dial)
        painter.setPen(QPen(mix(base, QColor(0, 0, 0), 0.25), max(1.0, s)))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(dial.adjusted(3 * s, 3 * s, -3 * s, -3 * s))        # the knob's grip ring
        look = looks["press"]
        if look.text and dial.width() >= 28:
            inset = dial.width() * 0.16
            self._label(painter, look.text, dial.adjusted(inset, inset, -inset, -inset), look.changed,
                        self._changed_color(accent, dark) if look.changed else fg)

        if active:
            painter.setPen(QPen(accent, max(2.0, 3 * s)))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(housing)
            painter.setPen(QPen(accent, max(1.5, 2 * s)))
            if active == "press":
                painter.drawEllipse(dial)
            else:
                painter.drawRoundedRect(zones[active].adjusted(2 * s, 2 * s, -2 * s, -2 * s), 4 * s, 4 * s)

    def _fit(self, text: str, area: QRectF, size: float, bold: bool) -> QFont:
        """The largest font (down to 7 px) at which `text` fits in `area`, wrapping at spaces and '+'."""
        font = QFont(self.font())
        font.setBold(bold)
        px = max(7, int(size))
        while True:
            font.setPixelSize(px)
            r = QFontMetricsF(font).boundingRect(area, Qt.AlignCenter | Qt.TextWordWrap, text)
            if (r.width() <= area.width() + 0.5 and r.height() <= area.height() + 0.5) or px <= 7:
                return font
            px -= 1

    # interaction
    def mouseMoveEvent(self, e):
        hover = self._key_at(e.position())
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        name = self._key_at(e.position())
        if name and e.button() == Qt.LeftButton:
            self.key_clicked.emit(name)

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            name = self._key_at(QPointF(e.pos()))
            look = self._looks.get(name) if name else None
            if name:
                QToolTip.showText(e.globalPos(), look.tooltip if look and look.tooltip else name, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)
