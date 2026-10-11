"""A picture of the keyboard, drawn from the model's key positions (keymap.js), with clickable keys."""
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .common import is_variant


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

    # data
    def set_keys(self, keymap: list[dict], show_variants: bool = False):
        self._keys = [k for k in keymap if show_variants or not is_variant(k)]
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
        for k in self._keys:
            p = k["Position"]
            r = r.united(QRectF(p["Left"], p["Top"], p["Width"], p["Height"]))
        return r.adjusted(-14, -14, 14, 14)

    def _layout(self):
        self._rects = {}
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
            self._rects[k["KeyName"]] = QRectF(ox + p["Left"] * s, oy + p["Top"] * s, p["Width"] * s,
                                               p["Height"] * s).adjusted(1.5 * s, 1.5 * s, -1.5 * s, -1.5 * s)

    def _fit_height(self):
        """Keep the keyboard's shape: as tall as the width needs (the page gives the rest to other widgets)."""
        if self._keys and self.width() > 0:
            want = self.heightForWidth(self.width())
            if want != self.minimumHeight() or want != self.maximumHeight():
                self.setFixedHeight(want)

    def resizeEvent(self, e):
        self._fit_height()
        self._layout()
        super().resizeEvent(e)

    def _key_at(self, pos: QPointF) -> str | None:
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
                painter.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 5 * s, 5 * s)

            fg = (QColor(0, 0, 0) if led.lightness() > 140 else QColor(255, 255, 255)) if led is not None else text
            inner = r.adjusted(4 * s, 3 * s, -4 * s, -3 * s)
            if look.changed:
                small = QFont(self.font())
                small.setPixelSize(max(7, int(9 * s)))
                painter.setFont(small)
                painter.setPen(dim if led is None else fg)
                painter.drawText(inner, Qt.AlignLeft | Qt.AlignTop, key.get("Show") or name)
            area = inner.adjusted(0, 9 * s * 0.8, 0, 0) if look.changed else inner
            big = self._fit(look.text.replace("+", "+\u200b"), area, 12 * s if len(look.text) <= 3 else 11 * s,
                            look.changed)
            painter.setFont(big)
            painter.setPen(accent.lighter(130) if look.changed and led is None and dark else
                           accent.darker(120) if look.changed and led is None else fg)
            painter.drawText(area, Qt.AlignCenter | Qt.TextWordWrap, look.text.replace("+", "+\u200b"))
        painter.end()

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
