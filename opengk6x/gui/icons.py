"""OpenGK6X's own icons: the app icon as an image (never looked up by name, so trays and taskbars always find it),
and line icons for the sidebar drawn in the current text color (visible in light and dark themes, whatever icon
theme is installed)."""
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

APP_SVG = Path(__file__).with_name("opengk6x.svg")

_LINE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" stroke-width="1.8" ' \
        'stroke-linecap="round" stroke-linejoin="round">{}</svg>'
GLYPHS = {
    "keys": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01'
            'M6 14h.01M18 14h.01M9 14h6"/>',
    "macros": '<path d="M4 6h10M4 12h7M4 18h10"/><path d="M15 10.5v7l5.5-3.5z" fill="#000"/>',
    "lighting": '<circle cx="9" cy="10" r="5"/><circle cx="15" cy="10" r="5"/><circle cx="12" cy="15" r="5"/>',
    "live": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "keyboard": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "warning": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
}


def app_icon() -> QIcon:
    """The OpenGK6X icon from its file (a theme-name icon can show up blank in Plasma's tray/taskbar until its
    icon cache knows a newly installed icon)."""
    return QIcon(str(APP_SVG))


def line_icon(name: str, color: QColor) -> QIcon:
    svg = _LINE.format(GLYPHS[name]).replace("#000", color.name())
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        renderer.render(p, QRectF(0, 0, size, size))
        p.end()
        icon.addPixmap(pm)
    return icon
