"""OpenGK6X main window."""
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget)

from .common import AppState, heading, hint
from .icons import app_icon, line_icon
from .device_page import DevicePage
from .keys_page import KeysPage
from .lighting_page import LightingPage
from .live_page import LiveController, LivePage
from .macros_page import MacrosPage


class MissingDataPage(QWidget):
    title = "Setup"
    icon = "warning"

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        lay.addWidget(heading("The official app's data is needed"))
        lay.addWidget(hint("OpenGK6X reads each keyboard model's layout and defaults from your copy of the official "
                           "GK6X app (they belong to its maker, so they aren't included). Run:\n\n"
                           "    opengk6x setup-data GK6X_Setup_8.0.7.zip\n\n(the download from Epomaker, or the "
                           ".exe in it), then start OpenGK6X again."))
        lay.addStretch(2)


class MainWindow(QMainWindow):
    def __init__(self, tray_start: bool = False):
        super().__init__()
        self._quitting = False
        self.setWindowTitle("OpenGK6X")
        self.resize(1280, 860)
        self.state = AppState()
        self.state.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.conn = QLabel()
        self.statusBar().addPermanentWidget(self.conn)
        self.state.keyboard.connected.connect(self._connection)
        self._connection(None)

        self.live = None
        if self.state.vendor is None:
            pages = [MissingDataPage()]
        else:
            self.live = LiveController(self.state)
            self.state.live = self.live
            pages = [KeysPage(self.state), MacrosPage(self.state), LightingPage(self.state),
                     LivePage(self.state, self.live), DevicePage(self.state)]
        self.nav = QListWidget()
        self.nav.setIconSize(QSize(22, 22))
        self.nav.setFixedWidth(180)
        self.stack = QStackedWidget()
        for page in pages:
            item = QListWidgetItem(page.title)
            item.setData(Qt.UserRole, page.icon)
            self.nav.addItem(item)
            self.stack.addWidget(page)
        self._nav_icons()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.setCurrentRow(0)
        self._make_tray()
        if tray_start and self.live:
            # started at login: turn live mode on as soon as the keyboard is there
            def first(info):
                if info and not self.live.running:
                    self.state.keyboard.connected.disconnect(first)
                    self.live.start()
            self.state.keyboard.connected.connect(first)

    def _make_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip("OpenGK6X")
        menu = QMenu()
        self.tray_live = QAction("Live mode", menu, checkable=True)
        self.tray_live.triggered.connect(lambda on: self.live.start() if on else self.live.stop())
        if self.live:
            menu.addAction(self.tray_live)
            self.live.changed.connect(self._live_changed)
        menu.addAction("Open OpenGK6X", self._show)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self._show() if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self._live_changed()

    def _live_changed(self):
        on = bool(self.live and self.live.running)
        self.tray_live.setChecked(on)
        if self.tray:
            self.tray.setToolTip("OpenGK6X — live mode on" if on else "OpenGK6X")

    def _show(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _nav_icons(self):
        """Sidebar icons in the text color (redrawn when the colors change, e.g. light ↔ dark)."""
        color = self.nav.palette().color(QPalette.Text)
        for i in range(self.nav.count()):
            item = self.nav.item(i)
            item.setIcon(line_icon(item.data(Qt.UserRole), color))

    def changeEvent(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.state.reload_if_changed()
        if e.type() == QEvent.PaletteChange and hasattr(self, "nav"):
            self._nav_icons()
        super().changeEvent(e)

    def _connection(self, info):
        self.conn.setText("● Keyboard connected" if info else "○ Keyboard not connected")

    def quit(self):
        self._quitting = True
        self.close()

    def closeEvent(self, e):
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            if hasattr(page, "_save"):
                page._save()
        if not self._quitting and self.tray and self.live and self.live.running:
            self.hide()                    # live mode keeps running in the tray
            self.tray.showMessage("OpenGK6X", "Live mode keeps running here. Quit from this icon's menu.",
                                  app_icon(), 4000)
            e.ignore()
            return
        if self.live:
            self.live.stop_blocking()
        self.state.keyboard.shutdown()
        if self.tray:
            self.tray.hide()
        super().closeEvent(e)
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenGK6X")
    app.setDesktopFileName("opengk6x")
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    tray = "--tray" in sys.argv[1:]
    w = MainWindow(tray_start=tray)
    if not tray or not w.tray:
        w.show()
    sys.exit(app.exec())
