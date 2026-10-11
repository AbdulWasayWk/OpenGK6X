"""Lighting page: how lighting works on this keyboard."""
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from .common import AppState, heading, hint


class LightingPage(QWidget):
    title = "Lighting"
    icon = "preferences-desktop-color"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Lighting"))
        box = QGroupBox("How lighting works on this keyboard")
        v = QVBoxLayout(box)
        self.text = QLabel()
        self.text.setWordWrap(True)
        v.addWidget(self.text)
        lay.addWidget(box)
        lay.addWidget(hint("Editing the custom effects list (Fn + −) comes next. The keyboard can't send its current "
                           "effects back, so OpenGK6X will always ask before replacing them."))
        lay.addStretch(1)
        state.model_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        per_profile = bool(self.state.config.get("hasModeLe"))
        own = ("Each offline profile can have its own lighting effect." if per_profile else
               "Your keyboard's profiles don't store lighting of their own: every profile uses the same "
               "effects, and you pick one on the keyboard.")
        self.text.setText(
            f"{own}<br><br><b>Fn + =</b> cycles the keyboard's built-in effects.<br><b>Fn + −</b> cycles your "
            "custom effects (stored in the keyboard).<br><b>Fn + ↑ / ↓</b> brightness, <b>Fn + ← / →</b> speed.<br><br>"
            "Writing a profile from OpenGK6X keeps the effect you picked.")
