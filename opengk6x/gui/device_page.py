"""Keyboard page: connection, switching profiles, import/export, the keyboard's own shortcuts, settings."""
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import protocol as p
from .. import transfer
from .common import AppState, confirm, error, hbox, heading, hint, info

SHORTCUTS = [("Fn + =", "Next built-in lighting effect"), ("Fn + −", "Next custom lighting effect"),
             ("Fn + ↑ / ↓", "Brightness up / down"), ("Fn + ← / →", "Effect speed"),
             ("BT / 2.4G / USB switch", "Connection: Bluetooth, 2.4 GHz receiver or cable"),
             ("Win / Mac switch", "Windows or Mac key layout"),
             ("Fn + Esc + Q (hold)", "Factory reset: clears everything stored in the keyboard")]


class DevicePage(QWidget):
    title = "Keyboard"
    icon = "preferences-desktop-peripherals"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)

        lay.addWidget(heading("Keyboard"))
        box = QGroupBox("Connection")
        f = QFormLayout(box)
        self.fields = {k: QLabel("—") for k in ("status", "model", "firmware", "matrix")}
        for k, label in (("status", "Status"), ("model", "Model"), ("firmware", "Firmware"), ("matrix", "Key matrix")):
            f.addRow(label, self.fields[k])
        f.addRow(hint("Settings are written over the USB cable. They're stored in the keyboard, so they also work "
                      "over Bluetooth and the 2.4 GHz receiver."))
        lay.addWidget(box)

        box = QGroupBox("Active profile")
        g = QGridLayout(box)
        g.addWidget(hint("Switch the keyboard to another profile. The standard profile is the keyboard's built-in "
                         "layout; profiles 1–3 are yours (Keys page)."), 0, 0, 1, 4)
        self.mode_buttons = []
        for i, (text, mode) in enumerate((("Standard", p.MODE_STANDARD), ("Profile 1", 2), ("Profile 2", 3),
                                          ("Profile 3", 4))):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, m=mode, t=text: self._switch(m, t))
            g.addWidget(btn, 1, i)
            self.mode_buttons.append(btn)
        lay.addWidget(box)

        box = QGroupBox("Back up and restore")
        v = QVBoxLayout(box)
        v.addWidget(hint("An OpenGK6X backup holds your profiles, macros and lighting effects in one file."))
        save = QPushButton("Save backup…")
        save.clicked.connect(self._backup)
        load = QPushButton("Restore backup…")
        load.clicked.connect(lambda: self._import(backup=True))
        v.addWidget(hbox(save, load))
        lay.addWidget(box)

        box = QGroupBox("Official app files")
        v = QVBoxLayout(box)
        v.addWidget(hint("Import profiles (.gpr, .cmf), macros (.cms) and lighting effects (.le) from the official "
                         "GK6X app, or its whole data folder (on Windows: %APPDATA%\\GK6XPlus-CMS). Export writes "
                         "files the official app can import."))
        files = QPushButton("Import files…")
        files.clicked.connect(lambda: self._import(backup=False))
        folder = QPushButton("Import folder…")
        folder.clicked.connect(self._import_folder)
        export = QPushButton("Export for the official app…")
        export.clicked.connect(self._export_official)
        v.addWidget(hbox(files, folder, export))
        lay.addWidget(box)

        box = QGroupBox("Shortcuts on the keyboard")
        g = QGridLayout(box)
        for i, (keys, what) in enumerate(SHORTCUTS):
            k = QLabel(f"<b>{keys}</b>")
            g.addWidget(k, i, 0)
            g.addWidget(QLabel(what), i, 1)
        g.setColumnStretch(1, 1)
        lay.addWidget(box)

        box = QGroupBox("After a factory reset")
        v = QVBoxLayout(box)
        v.addWidget(hint("Fn + Esc + Q clears the keyboard. Tell OpenGK6X so it shows your profiles as not written "
                         "(apply them again to put them back)."))
        reset = QPushButton("I reset the keyboard")
        reset.clicked.connect(self._was_reset)
        v.addWidget(hbox(reset))
        lay.addWidget(box)

        box = QGroupBox("Display")
        v = QVBoxLayout(box)
        self.variants = QCheckBox("Show volume-knob and split-spacebar keys (keyboard variants with those parts)")
        self.variants.setChecked(bool(state.settings.get("show_variants", False)))
        self.variants.toggled.connect(self._variants)
        v.addWidget(self.variants)
        lay.addWidget(box)
        lay.addStretch(1)

        state.keyboard.connected.connect(self._connected)
        self._connected(state.keyboard.info)

    def _connected(self, kb_info):
        on = kb_info is not None
        for b in self.mode_buttons:
            b.setEnabled(on)
        if not on:
            self.fields["status"].setText("Not connected — plug in the USB cable")
            for k in ("model", "firmware", "matrix"):
                self.fields[k].setText("—")
            return
        name = next((m.get("Name") for m in self._models() if m.get("ModelID") == kb_info.model), "")
        self.fields["status"].setText("Connected over USB")
        self.fields["model"].setText(f"{kb_info.model}" + (f" ({name})" if name else ""))
        self.fields["firmware"].setText(f"{kb_info.firmware_version}  (id 0x{kb_info.firmware_id:08x})")
        self.fields["matrix"].setText(f"{kb_info.matrix[0]} × {kb_info.matrix[1]}")

    def _models(self) -> list[dict]:
        import json
        if self.state.vendor is None:
            return []
        try:
            return json.loads((self.state.vendor.root / "device/modellist.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return []

    def _switch(self, mode: int, text: str):
        self.state.keyboard.run(lambda kb: kb.set_mode(mode),
                                lambda _r: self.state.message.emit(f"The keyboard is now on: {text}"),
                                lambda e: error(self, str(e)))

    def _backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save backup", str(Path.home() / "opengk6x-backup.json"),
                                              "OpenGK6X backup (*.json)")
        if path:
            transfer.write_backup(self.state.store, Path(path))
            self.state.message.emit(f"Saved {path}")

    def _import(self, backup: bool):
        if self.state.model is None:
            error(self, "Connect the keyboard first (so OpenGK6X knows its model).")
            return
        if backup:
            path, _ = QFileDialog.getOpenFileName(self, "Restore backup", str(Path.home()), "OpenGK6X backup (*.json)")
            paths = [Path(path)] if path else []
        else:
            files, _ = QFileDialog.getOpenFileNames(self, "Import official app files", str(Path.home()),
                                                    "Official app files (*.gpr *.cmf *.cms *.le)")
            paths = [Path(f) for f in files]
        self._do_import(paths, backup)

    def _import_folder(self):
        if self.state.model is None:
            error(self, "Connect the keyboard first (so OpenGK6X knows its model).")
            return
        d = QFileDialog.getExistingDirectory(self, "Import the official app's data folder", str(Path.home()))
        if d:
            self._do_import([Path(d)], backup=False)

    def _do_import(self, paths: list[Path], backup: bool):
        if not paths:
            return
        try:
            imported = transfer.read_backup(paths[0], self.state.model) if backup else \
                transfer.read_official(paths, self.state.model, self.state.vendor)
        except (OSError, ValueError) as e:
            error(self, f"Couldn't import: {e}")
            return
        if not (imported.profiles or imported.macros or imported.effects):
            error(self, "Nothing to import." + ("\n\n" + "\n".join(imported.notes) if imported.notes else ""))
            return
        summary = []
        if imported.profiles:
            summary.append("Profiles: " + ", ".join(f"{s} ({p.name})" for s, p in sorted(imported.profiles.items())))
        if imported.macros:
            summary.append(f"Macros: {len(imported.macros)}")
        if imported.effects:
            summary.append(f"Lighting effects: {len(imported.effects)}")
        notes = ("\n\nNotes:\n• " + "\n• ".join(imported.notes[:12])) if imported.notes else ""
        replaced = [s for s in imported.profiles if self.state.profiles.get(s)]
        warn = f"\n\nThis replaces your OpenGK6X profile {', '.join(replaced)}." if replaced else ""
        if not confirm(self, "Import", "\n".join(summary) + warn + notes, "Import"):
            return
        done = transfer.merge(self.state.store, self.state.model, imported)
        self.state.profiles = self.state.store.profiles(self.state.model)
        self.state.macros = self.state.store.macros()
        self.state.macros_changed.emit()
        self.state.profiles_changed.emit()
        info(self, "Imported:\n• " + "\n• ".join(done) +
             ("\n\nNothing was written to the keyboard yet: apply the profiles on the Keys page."
              if imported.profiles else ""))

    def _export_official(self):
        if self.state.model is None:
            error(self, "Connect the keyboard first (so OpenGK6X knows its model).")
            return
        d = QFileDialog.getExistingDirectory(self, "Export for the official app: choose a folder", str(Path.home()))
        if not d:
            return
        files, notes = transfer.write_official(self.state.store, self.state.model, self.state.vendor, Path(d))
        info(self, f"Wrote {len(files)} files to {d}." + ("\n\n" + "\n".join(notes) if notes else "") +
             "\n\nIn the official app, import the .gpr with its import-configuration button, and the macros and "
             "effects on its Macro and LE pages.")

    def _was_reset(self):
        if not confirm(self, "Keyboard reset", "Mark profiles 1–3 as not written? Your OpenGK6X profiles stay; apply "
                                               "them again to put them back on the keyboard.", "Mark"):
            return
        for prof in self.state.profiles.values():
            if prof:
                prof.applied = None
        self.state.save_profiles()

    def _variants(self, on: bool):
        self.state.settings.set("show_variants", on)
        self.state.model_changed.emit()
