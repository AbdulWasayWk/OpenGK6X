"""Macros page: the macro library, a step editor, a recorder, import/export of the official .cms files."""
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox,
                               QSplitter, QTableWidget, QVBoxLayout, QWidget)

from .. import bindings as b
from .. import cmf
from ..keycapture import from_native_scancode
from ..macros import MAX_ACTIONS, Macro, from_script, parse_text, to_script, to_text
from ..transfer import guid_for
from .common import AppState, confirm, error, heading, hint

KINDS = [("tap", "Tap key"), ("down", "Press key"), ("up", "Release key"), ("delay", "Wait"),
         ("mouse_down", "Mouse press"), ("mouse_up", "Mouse release")]
KEY_CHOICES = [(n, lbl) for n, lbl in b.MODIFIERS] + [(n, lbl) for _, (n, lbl) in b.KEYS.items()]


def to_rows(steps: list[dict]) -> list[dict]:
    """Steps → editor rows (a press directly followed by its release becomes one "tap" row)."""
    rows, i = [], 0
    while i < len(steps):
        s = steps[i]
        nxt = steps[i + 1] if i + 1 < len(steps) else {}
        if "delay" in s:
            rows.append({"kind": "delay", "ms": s["delay"]})
        elif "mouse" in s:
            rows.append({"kind": f"mouse_{s['action']}", "button": s["mouse"]})
        elif s["action"] == "down" and nxt.get("key") == s["key"] and nxt.get("action") == "up":
            rows.append({"kind": "tap", "key": s["key"]})
            i += 1
        else:
            rows.append({"kind": s["action"], "key": s["key"]})
        i += 1
    return rows


def to_steps(rows: list[dict]) -> list[dict]:
    steps = []
    for r in rows:
        if r["kind"] == "delay":
            steps.append({"delay": r["ms"]})
        elif r["kind"].startswith("mouse_"):
            steps.append({"mouse": r["button"], "action": r["kind"][6:]})
        elif r["kind"] == "tap":
            steps += [{"key": r["key"], "action": "down"}, {"key": r["key"], "action": "up"}]
        else:
            steps.append({"key": r["key"], "action": r["kind"]})
    return steps


class RecordDialog(QDialog):
    """Records key presses and releases (with the time between them) until Stop is clicked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record a macro")
        self.steps: list[dict] = []
        self._last = None
        lay = QVBoxLayout(self)
        self.label = QLabel("Recording… type on your keyboard, then click Stop.")
        f = self.label.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        self.label.setFont(f)
        self.label.setMinimumSize(460, 60)
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)
        self.delays = QCheckBox("Record the pauses between keys")
        self.delays.setChecked(True)
        self.delays.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(self.delays)
        lay.addWidget(hint("Mouse clicks aren't recorded; add them in the editor. Your desktop may catch some "
                           "shortcuts first."))
        buttons = QDialogButtonBox()
        stop = buttons.addButton("Stop", QDialogButtonBox.AcceptRole)
        stop.setFocusPolicy(Qt.NoFocus)
        cancel = buttons.addButton(QDialogButtonBox.Cancel)
        cancel.setFocusPolicy(Qt.NoFocus)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def showEvent(self, e):
        super().showEvent(e)
        self.grabKeyboard()

    def done(self, r):
        self.releaseKeyboard()
        if r and not self.delays.isChecked():
            self.steps = [s for s in self.steps if "delay" not in s]
        super().done(r)

    def _record(self, e, action):
        if e.isAutoRepeat():
            return
        what = from_native_scancode(e.nativeScanCode())
        if what is None:
            return
        kind, value = what
        key = value if kind == "modifier" else b.KEYS[value][0]
        now = time.monotonic()
        if self._last is not None:
            ms = min(0xFFFF, round((now - self._last) * 1000))
            if ms:
                self.steps.append({"delay": ms})
        self._last = now
        self.steps.append({"key": key, "action": action})
        self.preview.setText(to_text(self.steps)[-400:])

    def keyPressEvent(self, e):
        self._record(e, "down")

    def keyReleaseEvent(self, e):
        self._record(e, "up")


class MacrosPage(QWidget):
    title = "Macros"
    icon = "media-record"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.current: str | None = None
        self.rows: list[dict] = []
        self._saving = QTimer(self)
        self._saving.setSingleShot(True)
        self._saving.setInterval(400)
        self._saving.timeout.connect(self._save)

        split = QSplitter()
        outer = QHBoxLayout(self)
        outer.addWidget(split)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(heading("Macros"))
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._open)
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("New", self._new), ("Duplicate", self._duplicate), ("Delete", self._delete)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            row.addWidget(btn)
        ll.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Import .cms…", self._import), ("Export .cms…", self._export)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            row.addWidget(btn)
        ll.addLayout(row)
        split.addWidget(left)

        self.editor = QWidget()
        el = QVBoxLayout(self.editor)
        el.setContentsMargins(8, 0, 0, 0)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._rename)
        name_row.addWidget(self.name, 1)
        el.addLayout(name_row)

        tools = QHBoxLayout()
        record = QPushButton("⏺  Record…")
        record.clicked.connect(self._record)
        tools.addWidget(record)
        for text, row in (("+ Key", {"kind": "tap", "key": "a"}), ("+ Wait", {"kind": "delay", "ms": 50}),
                          ("+ Click", None)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, r=row: self._add(r))
            tools.addWidget(btn)
        tools.addStretch(1)
        for text, fn in (("↑", lambda: self._move(-1)), ("↓", lambda: self._move(1)), ("Remove", self._remove)):
            btn = QPushButton(text)
            btn.clicked.connect(fn)
            tools.addWidget(btn)
        el.addLayout(tools)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Step", "Key, button or time"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        el.addWidget(self.table, 1)

        text_row = QHBoxLayout()
        text_row.addWidget(QLabel("As text"))
        self.text = QLineEdit()
        self.text.setToolTip("+x press, -x release, x tap, 50ms wait, click:left — e.g. +ctrl c -ctrl")
        self.text.editingFinished.connect(self._from_text)
        text_row.addWidget(self.text, 1)
        el.addLayout(text_row)
        self.info = hint("")
        el.addWidget(self.info)
        split.addWidget(self.editor)
        split.setSizes([260, 700])

        state.macros_changed.connect(self._reload_list)
        state.profiles_changed.connect(self._update_info)
        self._reload_list()

    # --- list ------------------------------------------------------------------------------------
    def _reload_list(self):
        current = self.current
        self.list.blockSignals(True)
        self.list.clear()
        for name in sorted(self.state.macros, key=str.lower):
            self.list.addItem(name)
        self.list.blockSignals(False)
        items = self.list.findItems(current, Qt.MatchExactly) if current else []
        if items:
            self.list.setCurrentItem(items[0])
        elif self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._open(None)

    def _open(self, name):
        self._save()
        self.current = name if name in self.state.macros else None
        self.editor.setEnabled(self.current is not None)
        macro = self.state.macros.get(self.current) if self.current else None
        self.name.setText(self.current or "")
        self.rows = to_rows(macro.steps) if macro else []
        self._fill_table()

    def _unique(self, base: str) -> str:
        name, n = base, 1
        while name in self.state.macros:
            n += 1
            name = f"{base} {n}"
        return name

    def _new(self):
        name = self._unique("New macro")
        self.state.macros[name] = Macro(name, [])
        self.current = name
        self.state.save_macros()

    def _duplicate(self):
        if self.current:
            name = self._unique(f"{self.current} copy")
            self.state.macros[name] = Macro(name, list(self.state.macros[self.current].steps))
            self.current = name
            self.state.save_macros()

    def _users(self, name: str) -> list[str]:
        out = []
        for slot, prof in self.state.profiles.items():
            for layer, prefix in ((prof.keys, ""), (prof.fn_keys, "Fn+")) if prof else ():
                out += [f"profile {slot} {prefix}{k}" for k, v in layer.items()
                        if isinstance(v, dict) and v.get("macro") == name]
        return out

    def _delete(self):
        if not self.current:
            return
        users = self._users(self.current)
        warn = f"\n\nIt's used by {', '.join(users)}; those keys go back to their default." if users else ""
        if not confirm(self, "Delete macro", f"Delete “{self.current}”?{warn}", "Delete"):
            return
        for prof in self.state.profiles.values():
            for layer in (prof.keys, prof.fn_keys) if prof else ():
                for k in [k for k, v in layer.items() if isinstance(v, dict) and v.get("macro") == self.current]:
                    del layer[k]
        del self.state.macros[self.current]
        self.current = None
        self.state.save_profiles()
        self.state.save_macros()

    def _rename(self):
        new = self.name.text().strip()
        old = self.current
        if not old or not new or new == old:
            self.name.setText(old or "")
            return
        if new in self.state.macros:
            error(self, f"There's already a macro called “{new}”.")
            self.name.setText(old)
            return
        self._save()
        macro = self.state.macros.pop(old)
        macro.name = new
        self.state.macros[new] = macro
        for prof in self.state.profiles.values():
            for layer in (prof.keys, prof.fn_keys) if prof else ():
                for v in layer.values():
                    if isinstance(v, dict) and v.get("macro") == old:
                        v["macro"] = new
        self.current = new
        self.state.save_profiles()
        self.state.save_macros()

    # --- steps -----------------------------------------------------------------------------------
    def _fill_table(self):
        self.table.setRowCount(0)
        for i, r in enumerate(self.rows):
            self.table.insertRow(i)
            kind = QComboBox()
            for k, text in KINDS:
                kind.addItem(text, k)
            kind.setCurrentIndex(max(0, kind.findData(r["kind"])))
            kind.currentIndexChanged.connect(lambda _x, row=i, w=kind: self._kind_changed(row, w.currentData()))
            self.table.setCellWidget(i, 0, kind)
            self.table.setCellWidget(i, 1, self._value_widget(i, r))
        self._update_info()

    def _value_widget(self, i: int, r: dict) -> QWidget:
        if r["kind"] == "delay":
            w = QSpinBox()
            w.setRange(0, 0xFFFF)
            w.setSuffix(" ms")
            w.setValue(r["ms"])
            w.valueChanged.connect(lambda v, row=i: self._set(row, ms=v))
        elif r["kind"].startswith("mouse_"):
            w = QComboBox()
            w.addItem("Left button", "left")
            w.addItem("Right button", "right")
            w.setCurrentIndex(max(0, w.findData(r["button"])))
            w.currentIndexChanged.connect(lambda _x, row=i, c=w: self._set(row, button=c.currentData()))
        else:
            w = QComboBox()
            w.setEditable(True)
            w.setInsertPolicy(QComboBox.NoInsert)
            for name, label in KEY_CHOICES:
                w.addItem(label, name)
            w.setCurrentIndex(max(0, w.findData(r["key"])))
            w.currentIndexChanged.connect(lambda _x, row=i, c=w: self._set(row, key=c.currentData()))
        return w

    def _kind_changed(self, row: int, kind: str):
        r = self.rows[row]
        if kind == "delay":
            self.rows[row] = {"kind": kind, "ms": r.get("ms", 50)}
        elif kind.startswith("mouse_"):
            self.rows[row] = {"kind": kind, "button": r.get("button", "left")}
        else:
            self.rows[row] = {"kind": kind, "key": r.get("key", "a")}
        self.table.setCellWidget(row, 1, self._value_widget(row, self.rows[row]))
        self._changed()

    def _set(self, row: int, **values):
        self.rows[row].update({k: v for k, v in values.items() if v is not None})
        self._changed()

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else self.table.currentRow()

    def _add(self, row: dict | None):
        if row is None:
            new = [{"kind": "mouse_down", "button": "left"}, {"kind": "mouse_up", "button": "left"}]
        else:
            new = [dict(row)]
        at = self._selected_row()
        at = len(self.rows) if at < 0 else at + 1
        self.rows[at:at] = new
        self._fill_table()
        self.table.selectRow(at)
        self._changed()

    def _remove(self):
        at = self._selected_row()
        if 0 <= at < len(self.rows):
            del self.rows[at]
            self._fill_table()
            self._changed()

    def _move(self, d: int):
        at = self._selected_row()
        to = at + d
        if 0 <= at < len(self.rows) and 0 <= to < len(self.rows):
            self.rows[at], self.rows[to] = self.rows[to], self.rows[at]
            self._fill_table()
            self.table.selectRow(to)
            self._changed()

    def _record(self):
        dlg = RecordDialog(self)
        if dlg.exec() and dlg.steps:
            self.rows += to_rows(dlg.steps)
            self._fill_table()
            self._changed()

    def _from_text(self):
        try:
            steps = parse_text(self.text.text())
        except ValueError as e:
            error(self, str(e))
            return
        self.rows = to_rows(steps)
        self._fill_table()
        self._changed()

    def _changed(self):
        self._update_info()
        self._saving.start()

    def _save(self):
        if self._saving.isActive():
            self._saving.stop()
        if self.current and self.current in self.state.macros:
            steps = to_steps(self.rows)
            if steps != self.state.macros[self.current].steps:
                self.state.macros[self.current].steps = steps
                self.state.save_macros()

    def _update_info(self):
        if not self.current:
            self.info.setText("Create a macro, then assign it to a key on the Keys page.")
            return
        steps = to_steps(self.rows)
        self.text.setText(to_text(steps))
        users = self._users(self.current)
        over = f"  ⚠ The keyboard holds at most {MAX_ACTIONS} steps." if len(steps) > MAX_ACTIONS else ""
        self.info.setText(f"{len(steps)} steps.{over}  " + (f"Used by {', '.join(users)} (apply those profiles "
                          "after editing)." if users else "Not assigned to a key yet (Keys page)."))

    # --- files -----------------------------------------------------------------------------------
    def _import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import macros", str(Path.home()), "Macros (*.cms)")
        added = []
        for f in files:
            try:
                kind, body = cmf.decode(Path(f).read_bytes())
            except (OSError, ValueError):
                kind = None
            if kind != "MACRO":
                error(self, f"{f} isn't a macro file from the official app")
                continue
            name = self._unique(Path(f).stem)
            self.state.macros[name] = Macro(name, from_script(body.decode("utf-8-sig", errors="replace")))
            added.append(name)
        if added:
            self.current = added[-1]
            self.state.save_macros()

    def _export(self):
        if not self.current:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export macro", str(Path.home() / f"{self.current}.cms"),
                                              "Macros (*.cms)")
        if not path:
            return
        try:
            script = to_script(self.current, guid_for("macro", self.current), self.state.macros[self.current].steps)
        except ValueError as e:
            error(self, str(e))
            return
        Path(path).write_bytes(cmf.encode("MACRO", script.encode("utf-8")))
        self.state.message.emit(f"Exported {path}")
