"""OpenGK6X main window."""
import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from .common import AppState, heading, hint
from .device_page import DevicePage
from .keys_page import KeysPage
from .lighting_page import LightingPage
from .macros_page import MacrosPage


class MissingDataPage(QWidget):
    title = "Setup"
    icon = "dialog-warning"

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
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenGK6X")
        self.resize(1280, 860)
        self.state = AppState()
        self.state.message.connect(lambda m: self.statusBar().showMessage(m, 8000))
        self.conn = QLabel()
        self.statusBar().addPermanentWidget(self.conn)
        self.state.keyboard.connected.connect(self._connection)
        self._connection(None)

        if self.state.vendor is None:
            pages = [MissingDataPage()]
        else:
            pages = [KeysPage(self.state), MacrosPage(self.state), LightingPage(self.state), DevicePage(self.state)]
        self.nav = QListWidget()
        self.nav.setIconSize(QSize(22, 22))
        self.nav.setFixedWidth(180)
        self.stack = QStackedWidget()
        for page in pages:
            self.nav.addItem(QListWidgetItem(QIcon.fromTheme(page.icon), page.title))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.setCurrentRow(0)

    def _connection(self, info):
        self.conn.setText("● Keyboard connected" if info else "○ Keyboard not connected")

    def closeEvent(self, e):
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            if hasattr(page, "_save"):
                page._save()
        self.state.keyboard.shutdown()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("OpenGK6X")
    app.setDesktopFileName("opengk6x")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
