"""Keys page: offline profiles 1-3, the keyboard picture, and changing what each key does."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QPushButton, QStackedWidget, QTabBar, QToolButton, QVBoxLayout, QWidget)

from .. import bindings as b
from .. import session
from .. import layouts
from ..store import SLOT_MODES, STANDARD, Profile, presets
from .binding_picker import BindingPicker
from .common import AppState, confirm, error, heading, hint
from .keyboard_view import KeyboardView, KeyLook

KNOB_HELP = {"left": "What turning the knob to the left does", "right": "What turning the knob to the right does",
             "press": "What pressing the knob does"}

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
    icon = "keys"

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self.slot = STANDARD
        self.fn = False
        self.selected: str | None = None
        self.busy = False

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for s in SLOT_MODES:
            self.tabs.addTab(self._tab_name(s))
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
            self.copy_menu.addAction(self._tab_name(s), lambda s=s: self._copy_to(s))
        more.setMenu(menu)
        top.addWidget(self.activate)
        top.addWidget(self.apply)
        top.addWidget(more)
        lay.addLayout(top)

        self.status = QLabel()
        self.status.setTextFormat(Qt.RichText)
        self.where = hint("")
        lay.addWidget(self.status)
        lay.addWidget(self.where)

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

        # the knob's three actions, for keyboards that have one
        self.knob_box = QWidget()
        kl = QHBoxLayout(self.knob_box)
        kl.setContentsMargins(0, 0, 0, 0)
        self.knob_title = QLabel()
        kl.addWidget(self.knob_title)
        self.knob_combos: dict[str, QComboBox] = {}
        for role, text in layouts.KNOB_ROLES.items():
            kl.addSpacing(12)
            kl.addWidget(QLabel(text))
            combo = QComboBox()
            combo.setMinimumWidth(190)
            combo.activated.connect(lambda _i, r=role: self._knob_chosen(r))
            kl.addWidget(combo)
            self.knob_combos[role] = combo
        kl.addStretch(1)
        lay.addWidget(self.knob_box)

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
        self.press_label = QLabel("When pressed, light up with:")
        self.press_effect = QComboBox()
        self.press_effect.currentIndexChanged.connect(self._press_effect_changed)
        il.addWidget(self.press_label)
        il.addWidget(self.press_effect)
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
    @staticmethod
    def _tab_name(slot: str) -> str:
        return "Standard" if slot == STANDARD else f"Profile {slot}"

    def _layer_rules(self):
        """The Fn layer and macros exist in profiles 1-3 only (the keyboard refuses them in the standard one)."""
        fn_ok = self.state.has_fn_layer and self.slot != STANDARD
        self.layer_buttons.button(1).setVisible(fn_ok)
        if not fn_ok and self.fn:
            self.layer_buttons.button(0).setChecked(True)
            self.fn = False
        hidden = set(self.state.unsupported())
        if self.slot == STANDARD:
            hidden.add("Macros")
        self.picker.set_hidden_categories(hidden)

    def _model_changed(self):
        self.view.set_keys(self.state.display_keys(), self.state.screen_area())
        self._layer_rules()
        self.press_effect.blockSignals(True)
        self.press_effect.clear()
        self.press_effect.addItem("Nothing", None)
        for guid, name in self.state.effect_names():
            self.press_effect.addItem(name, guid)
        self.press_effect.blockSignals(False)
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
            name = prof.name if prof and prof.name and prof.name not in (f"Profile {s}", "Standard") else ""
            self.tabs.setTabText(i, self._tab_name(s) + (f" · {name}" if name else ""))
        wireless = layouts.LAYOUTS.get(self.state.layout, layouts.LAYOUTS["full"]).wireless_standard_only
        if self.slot == STANDARD:
            self.where.setText("The keyboard's own layout" + (", used on every connection (cable, 2.4 GHz, "
                               "Bluetooth)" if wireless else "") + ". Key changes only: the Fn layer and macros "
                               "need profile 1–3.")
        else:
            self.where.setText("Works on the USB cable only: over 2.4 GHz and Bluetooth the keyboard uses the "
                               "Standard profile. For changes everywhere, use the Standard tab." if wireless else "")
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
        self._fill_knob()
        self._update_editor()

    def _update_keys(self):
        prof = self._profile()
        layer = (prof.fn_keys if self.fn else prof.keys) if prof else {}
        looks = {}
        for k in self.state.display_keys():
            name = k["KeyName"]
            show = k.get("Show") or name
            if k.get("Shape") == "round" and name not in layer:
                default = self.state.default_binding(self.slot, name, self.fn)
                looks[name] = KeyLook(show, False, f"{show}: {b.label(default) if default is not None else '—'}"
                                                   " (default)")
                continue
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
        if name is None or prof is None or name == "Fn":
            self.press_label.setVisible(False)
            self.press_effect.setVisible(False)
        if name is None or prof is None:
            self.key_title.setText("No key selected")
            self.key_current.setText("Click a key on the keyboard above.")
            self.key_default.setText("")
            self.reset_key.setEnabled(False)
            self.picker.setEnabled(False)
            return
        layer = prof.fn_keys if self.fn else prof.keys
        label = next((k.get("Show") for k in self.state.display_keys() if k["KeyName"] == name and k.get("Shape")),
                     None) or name
        self.key_title.setText(("Fn + " if self.fn else "") + label)
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
        show_press = self.state.has_profile_lighting and not self.fn
        self.press_label.setVisible(show_press)
        self.press_effect.setVisible(show_press)
        if show_press:
            guid = (prof.lighting.get("key_effects") or {}).get(name)
            self.press_effect.blockSignals(True)
            self.press_effect.setCurrentIndex(max(0, self.press_effect.findData(guid)))
            self.press_effect.blockSignals(False)

    # --- events ----------------------------------------------------------------------------------
    def _tab_changed(self, i):
        self.slot = list(SLOT_MODES)[i]
        self._layer_rules()
        self.refresh()

    def _layer_changed(self, i):
        self.fn = i == 1
        self.refresh()

    def _select(self, name):
        self.selected = name
        self._update_editor()

    def _assign(self, binding):
        if self.selected and self.selected != "Fn":
            self._set_binding(self.selected, binding)

    def _set_binding(self, name: str, binding):
        """Bind `name` on the current layer; a binding equal to the default (or None) removes the change."""
        prof = self._profile()
        if prof is None:
            return
        layer = prof.fn_keys if self.fn else prof.keys
        default = self.state.default_binding(self.slot, name, self.fn)
        if binding is None or (not isinstance(binding, dict) and default is not None and b.parse(binding) == default):
            layer.pop(name, None)                       # same as the default: no change to keep
        else:
            layer[name] = binding
        self.state.save_profiles()

    # --- knob ------------------------------------------------------------------------------------
    def _fill_knob(self):
        keys = layouts.knob_keys(self.state.layout)
        prof = self._profile()
        present = {k["KeyName"] for k in self.state.keymap}
        show = bool(keys) and prof is not None and all(n in present for n in keys.values())
        self.knob_box.setVisible(show)
        if not show:
            return
        self.knob_title.setText("<b>Knob</b>" + (" (with Fn held)" if self.fn else ""))
        layer = prof.fn_keys if self.fn else prof.keys
        texts = {b.parse(value): text for value, text in layouts.KNOB_ACTIONS}
        for role, combo in self.knob_combos.items():
            name = keys[role]
            default = self.state.default_binding(self.slot, name, self.fn)
            current = layer.get(name)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(f"Default ({texts.get(default) or b.label(default)})" if default is not None else "Default",
                          "__default__")
            selected = 0
            for value, text in layouts.KNOB_ACTIONS:
                combo.addItem(text, value)
                if isinstance(current, str) and b.parse(current) == b.parse(value):
                    selected = combo.count() - 1
            if current is not None and selected == 0:
                combo.addItem(describe(current), "__custom__")
                selected = combo.count() - 1
            combo.addItem("Other…", "__other__")
            combo.setCurrentIndex(selected)
            combo.setToolTip(f"{KNOB_HELP[role]}. “Other…” picks any action from the list below.")
            combo.blockSignals(False)

    def _knob_chosen(self, role: str):
        name = layouts.knob_keys(self.state.layout)[role]
        data = self.knob_combos[role].currentData()
        if data == "__other__":
            self._select(name)                          # the full list below, for this knob action
            self.picker.search.setFocus()
            self._fill_knob()
            return
        if data == "__custom__":
            return
        self._set_binding(name, None if data == "__default__" else data)

    def _press_effect_changed(self):
        prof = self._profile()
        if prof is None or not self.selected or self.fn:
            return
        effects = prof.lighting.setdefault("key_effects", {})
        guid = self.press_effect.currentData()
        if guid:
            effects[self.selected] = guid
        else:
            effects.pop(self.selected, None)
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
        keys, fn_keys = dict(prof.keys), dict(prof.fn_keys)
        note = ""
        if target == STANDARD:
            dropped = len(fn_keys) + sum(isinstance(v, dict) for v in keys.values())
            keys = {k: v for k, v in keys.items() if not isinstance(v, dict)}
            fn_keys = {}
            note = f"\n\n{dropped} Fn-layer and macro keys are left out: the standard profile can't hold them." \
                if dropped else ""
        if (old and (old.keys or old.fn_keys) or note) and not confirm(
                self, "Copy profile", f"Replace {self._tab_name(target)} with a copy of "
                f"{self._tab_name(self.slot)}?{note}", "Replace"):
            return
        self.state.profiles[target] = Profile(prof.name if target != STANDARD else "Standard", keys, fn_keys,
                                              old.applied if old else None, dict(prof.lighting))
        self.state.save_profiles()
        self.tabs.setCurrentIndex(list(SLOT_MODES).index(target))

    def _apply(self):
        prof = self._profile()
        if prof is None:
            return
        if prof.applied is None:
            if self.slot == STANDARD:
                text = ("This changes the keyboard's own layout (the Standard profile), which it also uses over "
                        "2.4 GHz and Bluetooth. Holding Fn + Esc + Q resets it to the factory layout.")
            else:
                text = (f"OpenGK6X hasn't written profile {self.slot} before. Writing replaces whatever the keyboard "
                        "has in it, for example settings from the official app.")
            if not confirm(self, "Write profile", text, "Write"):
                return
        slot, state = self.slot, self.state
        self.busy = True
        self.refresh()
        state.stop_live(lambda: self._write(slot))

    def _write(self, slot: str):
        state = self.state

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
        self.state.stop_live(lambda: self.state.keyboard.run(lambda kb: kb.set_mode(SLOT_MODES[slot]),
                                lambda _r: self.state.message.emit(f"The keyboard is now on profile {slot}"),
                                lambda e: error(self, str(e))))
