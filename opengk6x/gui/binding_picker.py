"""Choosing what a key does: a searchable list of every action, a shortcut builder, key capture, macros."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from .. import bindings as b
from ..keycapture import from_native_scancode
from .common import AppState, hint

MACRO_ROLE = Qt.UserRole + 1
CATEGORY_ORDER = ["Basic", "Keys", "Modifiers", "Shortcuts", "Media", "Mouse", "Lighting", "Profiles",
                  "Space dual-role", "System"]


class CaptureDialog(QDialog):
    """Press a key or a shortcut; the result is a binding text ("ctrl+shift+t", "f13", "lctrl")."""

    def __init__(self, parent=None, title="Press a key or shortcut"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result_text: str | None = None
        self._mods: list[str] = []
        self._held: set[int] = set()
        self._key: int | None = None
        lay = QVBoxLayout(self)
        self.label = QLabel("Press the key or shortcut on your keyboard…")
        f = self.label.font()
        f.setPointSizeF(f.pointSizeF() * 1.4)
        self.label.setFont(f)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(380, 90)
        lay.addWidget(self.label)
        lay.addWidget(hint("Release all keys to finish. Your desktop may catch some shortcuts (like Super) first."))
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, e):
        super().showEvent(e)
        self.grabKeyboard()

    def done(self, r):
        self.releaseKeyboard()
        super().done(r)

    def _text(self) -> str:
        parts = [b.FRIENDLY[m] for m in self._mods]
        if self._key is not None:
            parts.append(b.KEYS[self._key][0])
        return "+".join(parts)

    def keyPressEvent(self, e):
        if e.isAutoRepeat():
            return
        what = from_native_scancode(e.nativeScanCode())
        if what is None:
            self.label.setText("That key can't be used here")
            return
        self._held.add(e.nativeScanCode())
        kind, value = what
        if kind == "modifier":
            if value not in self._mods and self._key is None:
                self._mods.append(value)
        elif self._key is None:
            self._key = value
        self.label.setText(b.label(b.parse(self._text())))

    def keyReleaseEvent(self, e):
        if e.isAutoRepeat():
            return
        self._held.discard(e.nativeScanCode())
        if not self._held and (self._mods or self._key is not None):
            self.result_text = b.name(b.parse(self._text()))
            self.accept()


class BindingPicker(QWidget):
    """Emits `chosen` with a binding (text, or a macro dict) when the user assigns something."""

    chosen = Signal(object)

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._hidden: set[str] = set()
        self._suggest: tuple[str, tuple] | None = None
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        lay = QVBoxLayout()
        right = QVBoxLayout()
        outer.addLayout(lay, 3)
        outer.addLayout(right, 2)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search: volume, copy, f13, mouse, profile, macro…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemDoubleClicked.connect(lambda item, _c: self._assign_item(item))
        self.tree.currentItemChanged.connect(self._selection_changed)
        lay.addWidget(self.tree, 1)

        self.macro_box = QGroupBox("Macro playback")
        mg = QHBoxLayout(self.macro_box)
        self.repeat = QComboBox()
        for mode, text in (("times", "Run"), ("while_held", "Repeat while the key is held"),
                           ("toggle", "Repeat until pressed again")):
            self.repeat.addItem(text, mode)
        self.count = QSpinBox()
        self.count.setRange(1, 255)
        self.count_label = QLabel("time(s)")
        self.repeat.currentIndexChanged.connect(self._repeat_changed)
        mg.addWidget(self.repeat)
        mg.addWidget(self.count)
        mg.addWidget(self.count_label)
        mg.addStretch(1)
        self.macro_box.hide()
        lay.addWidget(self.macro_box)

        self.assign = QPushButton("Assign to key")
        self.assign.setDefault(True)
        self.assign.setEnabled(False)
        self.assign.clicked.connect(lambda: self._assign_item(self.tree.currentItem()))
        lay.addWidget(self.assign)

        combo = QGroupBox("Shortcut")
        g = QGridLayout(combo)
        self.mods = {}
        for i, (name, text) in enumerate((("lctrl", "Ctrl"), ("lshift", "Shift"), ("lalt", "Alt"),
                                          ("lwin", "Super"))):
            cb = QCheckBox(text)
            self.mods[name] = cb
            g.addWidget(cb, 0, i)
        self.right_hand = QCheckBox("right-hand")
        self.right_hand.setToolTip("Use the right Ctrl/Shift/Alt/Super instead of the left ones")
        g.addWidget(self.right_hand, 0, 4)
        self.combo_key = QComboBox()
        self.combo_key.setEditable(True)
        self.combo_key.setInsertPolicy(QComboBox.NoInsert)
        self.combo_key.addItem("(no key)", None)
        for usage, (name, label) in b.KEYS.items():
            self.combo_key.addItem(label, name)
        g.addWidget(QLabel("+"), 1, 0, Qt.AlignRight)
        g.addWidget(self.combo_key, 1, 1, 1, 2)
        set_combo = QPushButton("Assign shortcut")
        set_combo.clicked.connect(self._assign_combo)
        g.addWidget(set_combo, 1, 3, 1, 2)
        capture = QPushButton("⌨  Press keys to capture…")
        capture.setToolTip("Press a key or shortcut on your keyboard to fill this in")
        capture.clicked.connect(self._capture)
        g.addWidget(capture, 2, 0, 1, 5)
        right.addWidget(combo)
        right.addWidget(hint("Double-click an action to assign it. Shortcuts are sent as one key press with the "
                             "modifiers held, so Ctrl+C copies."))
        right.addStretch(1)

        state.macros_changed.connect(self.rebuild)
        self.rebuild()

    def set_hidden_categories(self, hidden):
        self._hidden = set(hidden)
        self.rebuild()

    def set_suggestions(self, title: str | None, actions=()):
        """An extra group at the top of the list, e.g. what knobs are usually set to; None for none."""
        new = (title, tuple(actions)) if title else None
        if new != self._suggest:
            self._suggest = new
            self.rebuild()

    def set_target(self, text: str):
        """What the assign button assigns to ("key", "turn left", …)."""
        self.assign.setText(f"Assign to {text}")

    def rebuild(self):
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        if self._suggest:
            top = QTreeWidgetItem(self.tree, [self._suggest[0]])
            top.setFlags(Qt.ItemIsEnabled)
            for name, label in self._suggest[1]:
                item = QTreeWidgetItem(top, [label])
                item.setData(0, Qt.UserRole, name)
                item.setToolTip(0, f"{label}  [{name}]")
            top.setExpanded(True)
        for cat in [c for c in CATEGORY_ORDER + ["Macros"] if c not in self._hidden]:
            groups[cat] = QTreeWidgetItem(self.tree, [cat])
            groups[cat].setFlags(Qt.ItemIsEnabled)
        for a in b.catalog():
            if a.category not in groups:
                continue
            item = QTreeWidgetItem(groups[a.category], [a.label])
            item.setData(0, Qt.UserRole, a.name)
            item.setToolTip(0, f"{a.label}  [{a.name}]")
        for name in sorted(self.state.macros, key=str.lower) if "Macros" in groups else ():
            item = QTreeWidgetItem(groups["Macros"], [name])
            item.setData(0, MACRO_ROLE, name)
        if not self.state.macros and "Macros" in groups:
            item = QTreeWidgetItem(groups["Macros"], ["(no macros yet: make one on the Macros page)"])
            item.setFlags(Qt.ItemIsEnabled)
        groups["Basic"].setExpanded(not self._suggest)
        self._filter(self.search.text())

    def _filter(self, text: str):
        words = text.lower().split()
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            visible = 0
            for j in range(group.childCount()):
                child = group.child(j)
                hay = f"{child.text(0)} {child.data(0, Qt.UserRole) or ''} {group.text(0)}".lower()
                show = all(w in hay for w in words)
                child.setHidden(not show)
                visible += show
            group.setHidden(visible == 0)
            if words:
                group.setExpanded(True)

    def _selection_changed(self, item, _prev):
        is_action = bool(item and (item.data(0, Qt.UserRole) or item.data(0, MACRO_ROLE)))
        self.assign.setEnabled(is_action)
        self.macro_box.setVisible(bool(item and item.data(0, MACRO_ROLE)))

    def _repeat_changed(self):
        times = self.repeat.currentData() == "times"
        self.count.setVisible(times)
        self.count_label.setVisible(times)

    def _assign_item(self, item):
        if item is None:
            return
        if item.data(0, MACRO_ROLE):
            self.chosen.emit({"macro": item.data(0, MACRO_ROLE), "repeat": self.repeat.currentData(),
                              "count": self.count.value()})
        elif item.data(0, Qt.UserRole):
            self.chosen.emit(item.data(0, Qt.UserRole))

    def _assign_combo(self):
        right = self.right_hand.isChecked()
        parts = [("r" + n[1:] if right else n) for n, cb in self.mods.items() if cb.isChecked()]
        key = self.combo_key.currentData()
        if key is None:
            text = self.combo_key.currentText().strip().lower()
            key = next((n for _, (n, lbl) in b.KEYS.items() if lbl.lower() == text or n == text), None)
        if key:
            parts.append(key)
        if parts:
            self.chosen.emit(b.name(b.parse("+".join(parts))))

    def _capture(self):
        dlg = CaptureDialog(self)
        if dlg.exec() and dlg.result_text:
            self.chosen.emit(dlg.result_text)

    def show_binding(self, binding):
        """Reflect a key's current binding in the shortcut builder / macro options."""
        if isinstance(binding, dict):
            self.repeat.setCurrentIndex(max(0, self.repeat.findData(binding.get("repeat", "times"))))
            self.count.setValue(int(binding.get("count", 1)))
            return
        value = b.parse(binding) if binding else 0
        for cb in self.mods.values():
            cb.setChecked(False)
        self.right_hand.setChecked(False)
        self.combo_key.setCurrentIndex(0)
        if value >> 16 == 0x0200:
            mods, usage = value & 0xFF, value >> 8 & 0xFF
            self.right_hand.setChecked(bool(mods & 0xF0) and not mods & 0x0F)
            for n, cb in self.mods.items():
                cb.setChecked(bool(mods & (b.MODIFIER_BITS[n] | b.MODIFIER_BITS["r" + n[1:]])))
            i = self.combo_key.findData(b.KEYS[usage][0]) if usage in b.KEYS else 0
            self.combo_key.setCurrentIndex(max(0, i))
