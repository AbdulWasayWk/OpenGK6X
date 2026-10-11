"""Keys page: offline profiles 1-3, the keyboard picture, and changing what each key does."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QPushButton,
                               QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from .. import bindings as b
from .. import session
from ..store import SLOT_MODES, Profile, presets
from .binding_picker import BindingPicker
from .common import AppState, confirm, error, heading, hint
from .keyboard_view import KeyboardView, KeyLook

STATUS_STYLE = {session.APPLIED: ("●", "#2e9d4f"), session.CHANGED: ("●", "#d08a1a"),
                session.NOT_WRITTEN: ("●", "#d08a1a"), session.UNKNOWN: ("○", "palette(placeholder-text)")}


def describe(binding) -> str:
    if isinstance(binding, dict):
        how = {"times": f"{binding.get('count', 1)}×", "while_held": "while held",
               "toggle": "until pressed again"}[binding.get("repeat", "times")]
        return f"Macro “{binding['macro']}” ({how})"
    return b.label(b.parse(binding))


class KeysPage(QWidget):
    title = "Keys"
    icon = "input-keyboard"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.slot = "1"
        self.fn = False
        self.selected: str | None = None
        self.busy = False

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for s in SLOT_MODES:
            self.tabs.addTab(f"Profile {s}")
        self.tabs.currentChanged.connect(self._tab_changed)
        top.addWidget(self.tabs)
        top.addStretch(1)
        self.activate = QPushButton("Use on keyboard")
        self.activate.setToolTip("Switch the keyboard to this profile")
        self.activate.clicked.connect(self._activate)
        self.apply = QPushButton("Apply to keyboard")
        self.apply.setDefault(True)
        self.apply.clicked.connect(self._apply)
        more = QToolButton()
        more.setText("⋯")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("Rename profile…", self._rename)
        menu.addAction("Reset every key to default", self._reset_all)
        self.copy_menu = menu.addMenu("Copy this profile to")
        for s in SLOT_MODES:
            self.copy_menu.addAction(f"Profile {s}", lambda s=s: self._copy_to(s))
        more.setMenu(menu)
        top.addWidget(self.activate)
        top.addWidget(self.apply)
        top.addWidget(more)
        lay.addLayout(top)

        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        lay.addWidget(self.status)

        layer_row = QHBoxLayout()
        self.layer_buttons = QButtonGroup(self)
        for i, text in enumerate(("Normal", "With Fn held")):
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            self.layer_buttons.addButton(btn, i)
            layer_row.addWidget(btn)
        self.layer_buttons.idClicked.connect(self._layer_changed)
        layer_row.addSpacing(12)
        layer_row.addWidget(hint("Click a key to change what it does. Highlighted keys differ from the default."), 1)
        lay.addLayout(layer_row)

        self.view = KeyboardView()
        self.view.key_clicked.connect(self._select)
        lay.addWidget(self.view)

        # below the keyboard: the editor, or a panel for a slot OpenGK6X hasn't set up
        self.lower = QStackedWidget()
        lay.addWidget(self.lower, 1)

        editor = QWidget()
        el = QHBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        info = QFrame()
        info.setFrameShape(QFrame.StyledPanel)
        info.setFixedWidth(260)
        il = QVBoxLayout(info)
        self.key_title = heading("No key selected")
        self.key_title.setWordWrap(True)
        self.key_current = QLabel("Click a key on the keyboard above.")
        self.key_current.setWordWrap(True)
        self.key_default = hint("")
        self.reset_key = QPushButton("Reset to default")
        self.reset_key.clicked.connect(self._reset_key)
        il.addWidget(self.key_title)
        il.addWidget(self.key_current)
        il.addWidget(self.key_default)
        il.addStretch(1)
        il.addWidget(self.reset_key)
        el.addWidget(info)
        self.picker = BindingPicker(state)
        self.picker.chosen.connect(self._assign)
        el.addWidget(self.picker, 1)
        self.lower.addWidget(editor)

        setup = QWidget()
        sl = QVBoxLayout(setup)
        sl.addStretch(1)
        self.setup_text = QLabel()
        self.setup_text.setWordWrap(True)
        self.setup_text.setAlignment(Qt.AlignCenter)
        sl.addWidget(self.setup_text)
        self.preset_row = QHBoxLayout()
        sl.addLayout(self.preset_row)
        sl.addStretch(1)
        self.lower.addWidget(setup)

        state.profiles_changed.connect(self.refresh)
        state.model_changed.connect(self._model_changed)
        state.keyboard.connected.connect(lambda _info: self.refresh())
        self._model_changed()

    # --- display ---------------------------------------------------------------------------------
    def _model_changed(self):
        self.view.set_keys(self.state.keymap, self.state.settings.get("show_variants", False))
        while self.preset_row.count():
            item = self.preset_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preset_row.addStretch(1)
        start = QPushButton("Start from the standard layout")
        start.clicked.connect(lambda: self._set_up(None))
        self.preset_row.addWidget(start)
        if self.state.model is not None and self.state.vendor is not None:
            for title, prof in presets(self.state.vendor, self.state.model).items():
                btn = QPushButton(f"Start from: {title}")
                btn.clicked.connect(lambda _=False, p=prof: self._set_up(p))
                self.preset_row.addWidget(btn)
        self.preset_row.addStretch(1)
        self.refresh()

    def _profile(self) -> Profile | None:
        return self.state.profiles.get(self.slot)

    def refresh(self):
        if self.state.model is None:
            self.status.setText("Connect the keyboard with its USB cable to get started.")
            for w in (self.apply, self.activate):
                w.setEnabled(False)
            return
        for i, s in enumerate(SLOT_MODES):
            prof = self.state.profiles[s]
            name = prof.name if prof and prof.name and prof.name != f"Profile {s}" else ""
            self.tabs.setTabText(i, f"Profile {s}" + (f" · {name}" if name else ""))
        prof = self._profile()
        st = self.state.status(self.slot)
        mark, color = STATUS_STYLE[st]
        text = session.STATUS_TEXT[st]
        if st == session.CHANGED:
            text += " — press Apply to update the keyboard"
        elif st == session.NOT_WRITTEN:
            text += " — press Apply to write it"
        self.status.setText(f'<span style="color:{color}">{mark}</span> {text}')
        connected = self.state.keyboard.info is not None
        self.apply.setEnabled(connected and not self.busy and st in (session.CHANGED, session.NOT_WRITTEN))
        self.apply.setText("Writing…" if self.busy else "Apply to keyboard")
        self.activate.setEnabled(connected and not self.busy)
        self.copy_menu.setEnabled(prof is not None)
        if prof is None:
            self.setup_text.setText(
                f"<b>Profile {self.slot} isn't set up in OpenGK6X yet.</b><br><br>The keyboard may still hold "
                "settings for this profile from the official app; keyboards can't send those back, so OpenGK6X "
                "can't show them.<br>Start from a layout below, or bring them in with Keyboard → Import.")
            self.lower.setCurrentIndex(1)
        else:
            self.lower.setCurrentIndex(0)
        self._update_keys()
        self._update_editor()

    def _update_keys(self):
        prof = self._profile()
        layer = (prof.fn_keys if self.fn else prof.keys) if prof else {}
        looks = {}
        for k in self.state.keymap:
            name = k["KeyName"]
            show = k.get("Show") or name
            if name in layer:
                binding = layer[name]
                text = f"⏵ {binding['macro']}" if isinstance(binding, dict) else b.cap_label(b.parse(binding))
                looks[name] = KeyLook(text, True, f"{name}: {describe(binding)}")
                continue
            default = self.state.default_binding(self.slot, name, self.fn)
            if self.fn and default is not None and default != self.state.default_binding(self.slot, name, False):
                looks[name] = KeyLook(b.cap_label(default), False, f"Fn+{name}: {b.label(default)} (default)")
            elif name == "Fn":
                looks[name] = KeyLook("Fn", False, "The Fn key itself can't be changed")
            else:
                normal = self.state.default_binding(self.slot, name, False)
                text = b.cap_label(normal) if normal is not None and normal >> 16 == 0x0200 else show
                looks[name] = KeyLook(text, False, f"{name}: default")
        self.view.set_looks(looks)

    def _update_editor(self):
        prof = self._profile()
        name = self.selected
        self.view.set_selected(name)
        if name is None or prof is None:
            self.key_title.setText("No key selected")
            self.key_current.setText("Click a key on the keyboard above.")
            self.key_default.setText("")
            self.reset_key.setEnabled(False)
            self.picker.setEnabled(False)
            return
        layer = prof.fn_keys if self.fn else prof.keys
        self.key_title.setText(("Fn + " if self.fn else "") + name)
        if name == "Fn":
            self.key_current.setText("The Fn key itself can't be changed.")
            self.key_default.setText("")
            self.reset_key.setEnabled(False)
            self.picker.setEnabled(False)
            return
        default = self.state.default_binding(self.slot, name, self.fn)
        default_text = b.label(default) if default is not None else "nothing"
        if name in layer:
            self.key_current.setText(f"Now: <b>{describe(layer[name])}</b>")
            self.picker.show_binding(layer[name])
        else:
            self.key_current.setText(f"Now: <b>{default_text}</b> (default)")
            self.picker.show_binding(b.name(default) if default is not None else None)
        self.key_default.setText(f"Default: {default_text}")
        self.reset_key.setEnabled(name in layer)
        self.picker.setEnabled(True)

    # --- events ----------------------------------------------------------------------------------
    def _tab_changed(self, i):
        self.slot = list(SLOT_MODES)[i]
        self.refresh()

    def _layer_changed(self, i):
        self.fn = i == 1
        self.refresh()

    def _select(self, name):
        self.selected = name
        self._update_editor()

    def _assign(self, binding):
        prof = self._profile()
        if prof is None or self.selected is None or self.selected == "Fn":
            return
        layer = prof.fn_keys if self.fn else prof.keys
        default = self.state.default_binding(self.slot, self.selected, self.fn)
        if not isinstance(binding, dict) and default is not None and b.parse(binding) == default:
            layer.pop(self.selected, None)              # same as the default: no change to keep
        else:
            layer[self.selected] = binding
        self.state.save_profiles()

    def _reset_key(self):
        prof = self._profile()
        if prof and self.selected:
            (prof.fn_keys if self.fn else prof.keys).pop(self.selected, None)
            self.state.save_profiles()

    def _set_up(self, preset: Profile | None):
        self.state.profiles[self.slot] = Profile(
            name=preset.name if preset else f"Profile {self.slot}",
            keys=dict(preset.keys) if preset else {}, fn_keys=dict(preset.fn_keys) if preset else {})
        self.state.save_profiles()

    def _rename(self):
        prof = self._profile()
        if prof is None:
            return
        name, ok = QInputDialog.getText(self, "Rename profile", "Name:", text=prof.name)
        if ok:
            prof.name = name.strip()
            self.state.save_profiles()

    def _reset_all(self):
        prof = self._profile()
        if prof and (prof.keys or prof.fn_keys) and confirm(
                self, "Reset profile", f"Set every key of profile {self.slot} back to default?", "Reset"):
            prof.keys.clear()
            prof.fn_keys.clear()
            self.state.save_profiles()

    def _copy_to(self, target: str):
        prof = self._profile()
        if prof is None or target == self.slot:
            return
        old = self.state.profiles[target]
        if old and not confirm(self, "Copy profile", f"Replace profile {target} with a copy of profile "
                                                     f"{self.slot}?", "Replace"):
            return
        self.state.profiles[target] = Profile(prof.name, dict(prof.keys), dict(prof.fn_keys),
                                              old.applied if old else None)
        self.state.save_profiles()
        self.tabs.setCurrentIndex(list(SLOT_MODES).index(target))

    def _apply(self):
        prof = self._profile()
        if prof is None:
            return
        if prof.applied is None and not confirm(
                self, "Write profile", f"OpenGK6X hasn't written profile {self.slot} before. Writing replaces "
                f"whatever the keyboard has in it, for example settings from the official app.", "Write"):
            return
        slot, state = self.slot, self.state
        self.busy = True
        self.refresh()

        def job(kb):
            return session.write_profile(kb, state.store, state.vendor, state.model, slot, state.profiles)

        def done(r):
            self.busy = False
            state.message.emit(f"Profile {slot} written ({r.seconds:.1f} s); the keyboard is now on it")
            if r.unexpected:
                error(self, f"The keyboard answered {r.unexpected} packets unexpectedly. Details: {r.log}")
            state.profiles_changed.emit()

        def failed(e):
            self.busy = False
            self.refresh()
            error(self, f"Couldn't write profile {slot}: {e}")

        state.keyboard.run(job, done, failed)

    def _activate(self):
        slot = self.slot
        self.state.keyboard.run(lambda kb: kb.set_mode(SLOT_MODES[slot]),
                                lambda _r: self.state.message.emit(f"The keyboard is now on profile {slot}"),
                                lambda e: error(self, str(e)))
