"""A picture of the keyboard, drawn from the model's key positions (keymap.js), with clickable keys.

A knob (layouts.display_keys: its three entries share one area) is drawn as one round dial showing its three
actions: ⟲ turn left on top, the press in the middle, ⟳ turn right below. Clicking it emits one of its parts
(`key_clicked`); `knob_of` tells which knob a part belongs to."""
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

KNOB_LINES = (("left", "⟲ "), ("press", ""), ("right", "⟳ "))         # top to bottom


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

    def knob_of(self, name: str | None) -> dict | None:
        """{"rect", "parts": {role: key name}} of the knob `name` is a part of, or None."""
        return next((k for k in self._knobs.values() if name in k["parts"].values()), None)

    def _key_at(self, pos: QPointF) -> str | None:
        for knob in self._knobs.values():
            if knob["rect"].contains(pos):
                return knob["parts"].get("press") or next(iter(knob["parts"].values()))
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
        looks = {role: self._looks.get(name) or KeyLook("") for role, name in parts.items()}
        active = next((role for role, name in parts.items() if name == self._selected), None)
        d = min(r.width(), r.height())
        dial = QRectF(r.center().x() - d / 2, r.center().y() - d / 2, d, d)
        base = mix(key_bg, QColor(255, 255, 255), 0.08) if dark else mix(key_bg, QColor(0, 0, 0), 0.07)
        if self._hover in parts.values():
            base = mix(base, accent, 0.15)
        painter.setPen(QPen(mix(base, QColor(0, 0, 0), 0.35), max(1.0, s)))
        painter.setBrush(base)
        painter.drawEllipse(dial)
        painter.setPen(QPen(mix(base, QColor(0, 0, 0), 0.18), max(1.0, 0.8 * s)))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(dial.adjusted(2.5 * s, 2.5 * s, -2.5 * s, -2.5 * s))     # the knob's grip ring

        # its three actions, one line each; the line being edited gets a highlight
        side = d * 0.78
        h = side / 3
        top = dial.center().y() - side / 2
        for i, (role, arrow) in enumerate(KNOB_LINES):
            if role not in parts:
                continue
            look = looks[role]
            width = d * (0.84 if role == "press" else 0.74)
            line = QRectF(dial.center().x() - width / 2, top + i * h, width, h)
            if role == active:
                painter.setPen(Qt.NoPen)
                painter.setBrush(mix(base, accent, 0.35))
                painter.drawRoundedRect(line.adjusted(-1 * s, 0, 1 * s, 0), h / 2, h / 2)
            text = arrow + look.text if look.text else arrow.strip()
            color = self._changed_color(accent, dark) if look.changed else fg if look.text else dim
            self._line(painter, text, line, look.changed or role == "press" and bool(look.text), color)

        if active:
            painter.setPen(QPen(accent, max(2.0, 3 * s)))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(dial)
        elif any(look.changed for look in looks.values()):
            painter.setPen(QPen(mix(base, accent, 0.6), max(1.0, 1.5 * s)))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(dial.adjusted(0.5 * s, 0.5 * s, -0.5 * s, -0.5 * s))

    def _line(self, painter: QPainter, text: str, area: QRectF, bold: bool, color: QColor):
        """One line of text, as large as fits (6-11 px at this scale), shortened with … if it still doesn't."""
        font = QFont(self.font())
        font.setBold(bold)
        px = max(6, int(min(area.height() * 0.95, 11 * self._scale)))
        while True:
            font.setPixelSize(px)
            if QFontMetricsF(font).horizontalAdvance(text) <= area.width() or px <= 6:
                break
            px -= 1
        painter.setFont(font)
        painter.setPen(color)
        text = QFontMetricsF(font).elidedText(text, Qt.ElideRight, area.width() + 1)
        painter.drawText(area, Qt.AlignCenter, text)

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
            knob = self.knob_of(name)
            names = [knob["parts"][role] for role, _ in KNOB_LINES if role in knob["parts"]] if knob else [name]
            tips = [self._looks[n].tooltip for n in names if n in self._looks and self._looks[n].tooltip]
            if name:
                QToolTip.showText(e.globalPos(), "\n".join(tips) or name, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)
