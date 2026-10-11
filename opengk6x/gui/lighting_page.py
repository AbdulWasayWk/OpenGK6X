"""Lighting page: the effect library with a live preview, your own effects, and the custom effects list (Fn + −)."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSlider, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import cmf, session
from .. import effects as fx
from ..store import compile_custom, fingerprint
from .common import AppState, confirm, error, heading, hint
from .effect_widgets import EffectEditor, EffectPreview
from .keys_page import STATUS_STYLE

GUID_ROLE = Qt.UserRole


class LightingPage(QWidget):
    title = "Lighting"
    icon = "preferences-desktop-color"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.busy = False
        self.custom: list[str] = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(heading("Lighting"))
        top.addStretch(1)
        lay.addLayout(top)
        self.explain = hint("")
        lay.addWidget(self.explain)

        split = QSplitter()
        lay.addWidget(split, 1)

        # library
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search effects…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        ll.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda item, _p: self._preview(self._guid(item)))
        self.tree.itemDoubleClicked.connect(lambda item, _c: self._add_to_list())
        ll.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn in (("New…", self._new), ("Edit…", self._edit), ("Duplicate", self._duplicate),
                         ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Import .le…", self._import), ("Export .le…", self._export)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ll.addLayout(row)
        split.addWidget(left)

        # preview + custom list
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.preview_title = QLabel("Pick an effect to preview it")
        f = self.preview_title.font()
        f.setBold(True)
        self.preview_title.setFont(f)
        prow = QHBoxLayout()
        prow.addWidget(self.preview_title, 1)
        prow.addWidget(QLabel("Preview speed"))
        self.speed = QSlider(Qt.Horizontal)
        self.speed.setRange(25, 400)
        self.speed.setValue(100)
        self.speed.setFixedWidth(160)
        self.speed.valueChanged.connect(lambda _v: self._preview(self._previewing))
        prow.addWidget(self.speed)
        rl.addLayout(prow)
        self.preview = EffectPreview()
        rl.addWidget(self.preview)

        box = QGroupBox("Custom effects in the keyboard (cycle with Fn + −)")
        bl = QVBoxLayout(box)
        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        self.status.setWordWrap(True)
        bl.addWidget(self.status)
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        self.list.currentItemChanged.connect(lambda item, _p: self._preview(item.data(GUID_ROLE) if item else None))
        body.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.add_btn = QPushButton("← Add the selected effect")
        self.add_btn.clicked.connect(self._add_to_list)
        side.addWidget(self.add_btn)
        for text, fn in (("Remove", self._remove), ("Move up", lambda: self._move(-1)),
                         ("Move down", lambda: self._move(1)), ("Use the factory list", self._factory)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        body.addLayout(side)
        bl.addLayout(body)
        self.apply = QPushButton("Write to keyboard")
        self.apply.clicked.connect(self._apply)
        arow = QHBoxLayout()
        arow.addWidget(hint(f"Up to {fx.CUSTOM_SLOTS} effects. They're the same in every profile."), 1)
        arow.addWidget(self.apply)
        bl.addLayout(arow)
        rl.addWidget(box)
        split.addWidget(right)
        split.setSizes([300, 900])

        self._previewing = None
        state.model_changed.connect(self._model_changed)
        state.keyboard.connected.connect(lambda _i: self._update_status())
        self._model_changed()

    # --- data ------------------------------------------------------------------------------------
    def _effect(self, guid: str | None) -> dict | None:
        if not guid:
            return None
        mine = self.state.store.effects()
        if guid in mine:
            return mine[guid]
        text = self.state.vendor.effect(guid) if self.state.vendor else None
        try:
            return json.loads(text) if text else None
        except ValueError:
            return None

    def _name(self, guid: str) -> str:
        e = self.state.store.effects().get(guid)
        if e:
            return e.get("Name") or guid
        return self._library_names.get(guid, guid)

    def _model_changed(self):
        self.preview.set_keymap(self.state.keymap)
        self._library_names = {}
        if self.state.model is not None and self.state.vendor is not None:
            self._library_names = {e["GUID"]: e["Name"] for e in self.state.vendor.effect_library(self.state.model)}
        per_profile = bool(self.state.config.get("hasModeLe"))
        self.explain.setText(
            ("Each offline profile can have its own effect. " if per_profile else
             "On this keyboard all profiles share the lighting: ") +
            "Fn + = cycles the keyboard's built-in effects, Fn + − cycles your custom effects below. "
            "Fn + ↑/↓ brightness, Fn + ←/→ speed.")
        if self.state.model is not None:
            self.custom = list(self.state.store.lighting(self.state.model)["custom"])
        self._fill_tree()
        self._fill_list()

    def _fill_tree(self, select: str | None = None):
        self.tree.clear()
        mine = QTreeWidgetItem(self.tree, ["My effects"])
        lib = QTreeWidgetItem(self.tree, ["Official library"])
        for g in (mine, lib):
            g.setFlags(Qt.ItemIsEnabled)
            g.setExpanded(True)
        for guid, e in sorted(self.state.store.effects().items(), key=lambda kv: kv[1].get("Name", "").lower()):
            item = QTreeWidgetItem(mine, [e.get("Name") or guid])
            item.setData(0, GUID_ROLE, guid)
        if mine.childCount() == 0:
            empty = QTreeWidgetItem(mine, ["(none yet: click New…)"])
            empty.setFlags(Qt.ItemIsEnabled)
        for guid, name in self._library_names.items():
            item = QTreeWidgetItem(lib, [name])
            item.setData(0, GUID_ROLE, guid)
        self._filter(self.search.text())
        if select:
            for i in range(self.tree.topLevelItemCount()):
                g = self.tree.topLevelItem(i)
                for j in range(g.childCount()):
                    if g.child(j).data(0, GUID_ROLE) == select:
                        self.tree.setCurrentItem(g.child(j))

    def _filter(self, text: str):
        words = text.lower().split()
        for i in range(self.tree.topLevelItemCount()):
            g = self.tree.topLevelItem(i)
            for j in range(g.childCount()):
                c = g.child(j)
                c.setHidden(bool(words) and not all(w in c.text(0).lower() for w in words))

    def _fill_list(self):
        self.list.clear()
        for i, guid in enumerate(self.custom, 1):
            found = self._effect(guid) is not None
            item = QListWidgetItem(f"{i}.  {self._name(guid)}" + ("" if found else "  (missing)"))
            item.setData(GUID_ROLE, guid)
            self.list.addItem(item)
        self.add_btn.setEnabled(len(self.custom) < fx.CUSTOM_SLOTS)
        self._update_status()

    def _update_status(self):
        if self.state.model is None:
            self.status.setText("Connect the keyboard to get started.")
            self.apply.setEnabled(False)
            return
        data = self.state.store.lighting(self.state.model)
        if data["applied"] is None:
            st = session.UNKNOWN
            text = ("The keyboard still has the custom effects it came with or that the official app wrote; "
                    "they can't be read back. Writing replaces them.")
        else:
            current = compile_custom(self.state.store, self.state.vendor, self.state.model, self.state.matrix,
                                     self.custom)
            st = session.APPLIED if fingerprint(current) == data["applied"] else session.CHANGED
            text = {session.APPLIED: "The keyboard has this list.",
                    session.CHANGED: "Changed: press Write to keyboard to update it."}[st]
        mark, color = STATUS_STYLE[st]
        self.status.setText(f'<span style="color:{color}">{mark}</span> {text}')
        connected = self.state.keyboard.info is not None
        self.apply.setEnabled(connected and not self.busy and st != session.APPLIED)
        self.apply.setText("Writing…" if self.busy else "Write to keyboard")

    def _save_list(self):
        data = self.state.store.lighting(self.state.model)
        data["custom"] = list(self.custom)
        self.state.store.save_lighting(self.state.model, data)
        self._fill_list()

    @staticmethod
    def _guid(item) -> str | None:
        return item.data(0, GUID_ROLE) if item else None

    # --- preview ---------------------------------------------------------------------------------
    def _preview(self, guid: str | None):
        self._previewing = guid
        effect = self._effect(guid)
        self.preview_title.setText(self._name(guid) if guid else "Pick an effect to preview it")
        self.preview.play(effect, self.speed.value() / 100)

    def hideEvent(self, e):
        self.preview.stop()
        super().hideEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        if self._previewing:
            self._preview(self._previewing)

    # --- custom list -----------------------------------------------------------------------------
    def _add_to_list(self):
        guid = self._guid(self.tree.currentItem())
        if not guid or self.state.model is None:
            return
        if len(self.custom) >= fx.CUSTOM_SLOTS:
            error(self, f"The list holds {fx.CUSTOM_SLOTS} effects. Remove one first.")
            return
        self.custom.append(guid)
        self._save_list()

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.custom):
            del self.custom[row]
            self._save_list()

    def _move(self, d: int):
        row = self.list.currentRow()
        to = row + d
        if 0 <= row < len(self.custom) and 0 <= to < len(self.custom):
            self.custom[row], self.custom[to] = self.custom[to], self.custom[row]
            self._save_list()
            self.list.setCurrentRow(to)

    def _factory(self):
        std = self.state.vendor.default_profile(self.state.model, "std")
        self.custom = [e["GUID"] for e in std.get("DriverLE", []) if e.get("GUID")][:fx.CUSTOM_SLOTS]
        self._save_list()

    def _apply(self):
        if not self.custom and not confirm(self, "Write custom effects", "The list is empty: the keyboard will have "
                                           "no custom effects (Fn + − does nothing). Continue?", "Write"):
            return
        if self.state.store.lighting(self.state.model)["applied"] is None and not confirm(
                self, "Replace custom effects",
                "This replaces the custom effects stored in your keyboard (the ones Fn + − cycles), e.g. ones made "
                "with the official app. The keyboard can't send them back, so they can't be restored unless you "
                "have them as files.", "Replace"):
            return
        missing = [self._name(g) for g in self.custom if self._effect(g) is None]
        if missing and not confirm(self, "Missing effects", "These can't be found and will be left out:\n" +
                                   "\n".join(missing), "Continue"):
            return
        state, guids = self.state, list(self.custom)
        self.busy = True
        self._update_status()

        def done(r):
            self.busy = False
            self._update_status()
            state.message.emit(f"Custom effects written ({r.seconds:.1f} s). Press Fn + − to cycle them.")

        def failed(e):
            self.busy = False
            self._update_status()
            error(self, f"Couldn't write the custom effects: {e}")

        state.keyboard.run(lambda kb: session.write_custom(kb, state.store, state.vendor, state.model, guids),
                           done, failed)

    # --- my effects ------------------------------------------------------------------------------
    def _open_editor(self, effect: dict | None):
        dlg = EffectEditor([k for k in self.state.keymap], effect, self)
        if dlg.exec() and dlg.result_effect:
            self.state.store.save_effect(dlg.result_effect)
            self._fill_tree(select=dlg.result_effect["GUID"])
            self._fill_list()

    def _new(self):
        self._open_editor(None)

    def _edit(self):
        guid = self._guid(self.tree.currentItem())
        mine = self.state.store.effects()
        if guid in mine:
            if "OpenGK6X" in mine[guid]:
                self._open_editor(mine[guid])
            else:
                error(self, "This effect was made in the official app; it can be previewed, used and exported, "
                            "but not edited here. Make a new one with New….")
        elif guid:
            error(self, "Library effects can't be changed. Use New… to make your own.")

    def _duplicate(self):
        guid = self._guid(self.tree.currentItem())
        effect = self._effect(guid)
        if effect:
            copy = json.loads(json.dumps(effect))
            copy["GUID"] = fx.new_guid()
            copy["Name"] = f"{self._name(guid)} copy"
            self.state.store.save_effect(copy)
            self._fill_tree(select=copy["GUID"])

    def _delete(self):
        guid = self._guid(self.tree.currentItem())
        if guid not in self.state.store.effects():
            return
        used = guid in self.custom
        if not confirm(self, "Delete effect", f"Delete “{self._name(guid)}”?" +
                       ("\n\nIt's in your custom effects list; it'll be removed from there too." if used else ""),
                       "Delete"):
            return
        self.state.store.delete_effect(guid)
        if used:
            self.custom = [g for g in self.custom if g != guid]
            self._save_list()
        self._fill_tree()

    def _import(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import lighting effects", str(Path.home()), "Effects (*.le)")
        last = None
        for f in files:
            try:
                kind, body = cmf.decode(Path(f).read_bytes())
                effect = json.loads(body.decode("utf-8-sig")) if kind == "LIGHT" else None
            except (OSError, ValueError):
                effect = None
            if not effect or "Frames" not in effect:
                error(self, f"{f} isn't a lighting effect from the official app")
                continue
            effect.setdefault("GUID", fx.new_guid())
            effect["Name"] = effect.get("Name") or Path(f).stem
            self.state.store.save_effect(effect)
            last = effect["GUID"]
        if last:
            self._fill_tree(select=last)

    def _export(self):
        guid = self._guid(self.tree.currentItem())
        effect = self._effect(guid)
        if not effect:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export effect", str(Path.home() / f"{self._name(guid)}.le"),
                                              "Effects (*.le)")
        if path:
            Path(path).write_bytes(cmf.encode("LIGHT", json.dumps(effect, ensure_ascii=False).encode("utf-8")))
            self.state.message.emit(f"Exported {path}")
