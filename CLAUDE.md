# OpenGK6X — Project Source of Truth

> This file is the single source of truth for the project: goals, decisions, status and
> findings. **Update it as work progresses**: tick off tasks, record findings, log decisions.
> Wire-level detail lives in `docs/PROTOCOL.md`; summarize it here.

## Goal

An open-source Linux app for the user's **Skyloong GK104 Pro** (a GK6X-family keyboard), replacing the official
Windows "GK6X" software (user request 2026-10-11):

1. **Key remapping**: base layer, layers 1–3, Fn layers (whatever the official app offers).
2. **Lighting**: built-in effects, colors, brightness/speed, per-key colors, key-press lighting.
3. **Macros**: record/edit, assign to keys, repeat modes.
4. **Feature parity with the official app** ("basically everything the original software could do"). See *Feature catalog*.
5. Connections: **wired first** (what the user uses now); then the 2.4 GHz dongle and Bluetooth, if the keyboard
   can be configured over them.
6. Scope: the user's CachyOS (Arch) machine first. Portability comes later.

Sibling project: **OpenNollie** (`~/Projects/OpenNollie`, done 2026-10-11), the same idea for the Nollie 16CH
RGB controller. Reuse its structure, conventions and tooling; this project follows the same playbook.

## Environment facts

- Host: CachyOS, KDE Plasma 6 (Wayland), kernel 7.x, shell `fish`. Python 3.14 with `python-hidapi`
  (`hid.device()` API) and `pyside6` 6.11 from pacman, no venv. Python 3.11 at
  `~/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11`. Tools: `7z`, `cabextract`, `wine`,
  `dumpcap`/`tshark` (user is in `wireshark`), `objdump`, `strings`. Not installed: `innoextract`, Ghidra, `uv`.
- **Keyboard, wired: USB `1ea7:0907`** "SEMITE USB-HID Gaming Keyboar", bcdDevice 3.00, bus 3 port `3-2`.
  - if0 boot keyboard · **if1 = config interface** (vendor page `0xFF00`, 64 B IN/OUT, no report IDs) ·
    if2 = system/consumer/NKRO/mouse reports. Pick if1 by `usage_page == 0xFF00`.
  - **Model ID 656802056**, firmware ID `0x84223311`, firmware **v5.118**, key matrix 16 × 8 (read 2026-10-11 with
    `opengk6x info`). In the vendor's Windows-app data (pixeltris, V6.0.0.76) this model is called "104RGB".
  - Access: OpenRGB's `60-openrgb.rules` already grants `uaccess` for `1ea7:0907` (all interfaces). OpenRGB has a
    GK104 Pro driver (direct per-key lighting) but **isn't running**; if it ever runs it will grab the keyboard.
- **2.4 GHz dongle (probably this keyboard's): USB `1ea7:0067`** "Nordic Semiconductor nRF52 USB Product",
  bus 1 port `1-4`. if0 keyboard, if1 mouse, if2 system/consumer, **if3 = same config interface** as wired if1.
  Access: `packaging/70-opengk6x.rules`, installed by the user 2026-10-11 (`/etc/udev/rules.d/`); grants if3 only.
- **Vendor app in `vendor-app/`**: `GK6X-Setup-8.0.7.zip` (Epomaker download, sha256 `4cd43ac9…2d5c0f`) →
  `GK6X Setup 8.0.7.exe` (NSIS/electron-builder, 2024-12-28) → `nsis/`, `app/` (Electron "GK6+" 8.0.7) → `asar/`
  (`tools/re/asar_extract.py`). Plain readable JS: `asar/src/libs/{cmd,driver,profile,device,cmlemanager,
  cmleplayer,macro,keymap,cmfcodec}.js`; Vue UI bundle `asar/ui/js/` (key functions: `9271.*.js`; LE lists per
  category: `1785.*.js`); model data `asar/resources/device/656802056/`; effect/macro library
  `asar/resources/res/data/{le,macro}`. Decoded copies in `vendor-app/decoded/` (`tools/re/cmf_decode.py`;
  `keyfuncs.json` via a node `vm` dump of the UI chunk). The user deleted 8.0.1 (it didn't support this keyboard).
- **Keyboard shortcuts** (model `config.json` UserManual): BT/USB/2.4G switch, Win/Mac switch, Fn+−/+ cycle the
  standard effects, Fn+↑/↓ brightness, Fn+←/→ speed, **Fn+Esc+Q = clear all config (factory reset)**.
- Windows VM `win10` (libvirt, `qemu:///system`, user is in `libvirt`), shut off. Used for OpenNollie captures.
  ⚠ Passing the keyboard through to the VM takes it away from the host while attached (the mouse stays). The
  host still sees the traffic: `tools/setup-dev.sh usbmon` (once per boot, sudo), then
  `tools/capture.sh <name> [secs] [wired|dongle]` → `captures/<name>.pcapng`.
- Git: public repo **github.com/AbdulWasayWk/OpenGK6X** (`origin`, SSH; branch `master`), GPL-3.0-or-later
  (compatible with pixeltris MIT and OpenRGB GPL-2.0+). The user asked to push; keep pushing finished work.

## Prior art (in `reference/`, gitignored)

- **pixeltris/GK6X** (MIT, C#, archived 2026-03): CLI + the vendor's web GUI hosted locally. Writes keymaps (base,
  layers 1–3, Fn), macros, static/dynamic lighting, press lighting. Handshake, CRC, opcodes and data formats
  (`GK6X/*.cs`). Ships the vendor's 2021 `Data/` (proprietary, "jikedingzhi"), which already has our model
  `Data/device/656802056/` (keymap.js, profiles, config.json).
- **OpenRGB `Controllers/SkyloongController`** (GPL-2.0+): GK104 Pro direct mode: `0C` ping, `0B 05` online /
  `0B 04` offline, `1A` real-time per-key RGBA (528 B in 56 B chunks).

## Protocol summary

Full detail: `docs/PROTOCOL.md`. 64-byte reports: `[op, sub, 4 op-specific bytes, CRC16 LE, 56 B payload]`,
CRC-16/CCITT-FALSE over the report with the CRC zeroed. Every request gets a reply (byte 2 = 1 on success).
Handshake `01 09` / `01 01` / `01 08` verified. Everything else (layers `0B`, keys `22`/`31`, macros `25`,
lighting `27`, press lighting `26`, reset `21`, driver layer `15`–`1A`) is from prior art and unverified here.

## Feature catalog (official app → OpenGK6X)

From GK6+ 8.0.7 (`config.json` FuncTable: Configure keyboard, LE library, Macro library). Status: `[ ]` for all.

| App area | Features | Status |
|---|---|---|
| Device | detect (VER/DEVICE_ID/MODEL_ID), firmware version, picture of the keyboard (`keymap.js` positions) | [x] CLI `info`, GUI Keyboard page; keyboard picture drawn by us |
| Profiles | standard (effects list only) + offline profiles 1–3 stored in the keyboard; switch with `0B` or Fn keys; online (PC-driven) profiles; profile import/export (`.cmf`, `.gpr`) | [x] offline 1–3 (CLI + GUI), switching, import/export; [ ] online profiles |
| Key mapping | per key and per Fn key: any key + modifiers, combos (Ctrl+C…), disable, mouse buttons, media keys, lighting controls, profile switching, Space dual-role (hold = modifier), sleep, macros; online-only: open app/URL/file | [x] all offline actions (`bindings.py`, 199 + combos); [ ] online-only app/URL |
| Lighting | effect library (the UI's default list: 28 general + 3 for category 840 on ours), main effect per profile, per-key press lighting, per-key static colors, effect editor (frames + color logic: static / cycle / breathing), standard-mode effect list (Fn+−, 5 slots) | [x] library + live preview (`effects.Player` = app's cmleplayer), our editor (one color, key colors, breathing, cycle, rainbow wave, sweep), custom list (5 slots) CLI + GUI, .le import/export; [ ] first hardware write of the custom list (needs the user's OK: replaces their effects); per-profile lighting N/A on this model |
| Macros | library (148 presets), recorder/editor (key/mouse down-up, delays), repeat count, stop mode, assign to keys | [x] CLI + GUI (recorder, step editor, text form, .cms import/export); hardware playback not yet verified |
| Online mode | live per-key lighting effects rendered by the PC, macros/app launch on key press, game profiles (`Game`, `Application`) | [ ] (decide if wanted) |
| Firmware update | (none in 8.0.7: `firmware.js` is empty) | N/A |

## Architecture (proposed; same stack as OpenNollie)

**Python 3 + hidapi + PySide6 (Qt)**.

```
opengk6x/
  protocol.py    # packet framing, CRC, command builders + parsers (pure, no I/O)
  device.py      # hidapi transport (wired if1 / dongle if3), request/response, high-level ops
  cli.py         # `opengk6x …` (now: info)
  (later) model data (layouts, key names, driver values), profiles, macros, lighting, gui/
tests/           # unit tests against captured bytes
packaging/       # 70-opengk6x.rules (later: PKGBUILD, desktop file)
tools/           # setup-dev.sh (udev, usbmon), capture.sh
captures/        # .pcapng from RE sessions (gitignored)
vendor-app/      # official app + extracted files (gitignored, never commit)
reference/       # pixeltris/GK6X + OpenRGB driver (gitignored)
docs/PROTOCOL.md
```

## Definition of done

The app is **done** when every item below is checked. Keep this list current.
**Status 2026-10-11: every item is checked; the user declared the app done.** New work goes in as new items.

- [x] Every official feature that works on the GK104 Pro: offline profiles 1–3 (keys, Fn layer, macros), profile
      switching, custom effects list (Fn+−) + effect library + editor, online/live mode (lighting, key actions,
      PC macros), import/export of the official files (verified on hardware by the user, 2026-10-11)
- [x] Improvements: GK104 Pro picture with the knob (remappable) and screen; Fn-layer macros that work; lighting
      kept on profile writes; standard layout as every profile's base (Mac layout as a preset); typing effects;
      backups; CLI for everything
- [x] Safety: standard keys never written; confirmation before replacing unknown keyboard data (profiles,
      custom effects); live mode always switches back (Ctrl+C / terminal close / quit / disconnect)
- [x] Packaging like OpenNollie: README install-from-scratch (package / user), updating, uninstall;
      install-user.sh (checks deps, optional official zip → setup-data, udev hint, --remove incl. live autostart;
      installed for the user); PKGBUILD verified from a fresh GitHub clone (46 tests, package contents);
      udev rule installed; GitHub: github.com/AbdulWasayWk/OpenGK6X (pushed)
- [x] Knob options (user request 2026-10-12, as in the official app): turn left / turn right / press as separate
      parts of one knob in the picture + editor panel (normal and Fn layer), CLI `knob-left/-right/-press`
- [x] Wireless: profiles 1–3 aren't used over 2.4 GHz; **the Standard profile is** and its keys are now editable
      (keys only: macros/Fn layer refused). Custom effects carry over. Configuration needs the cable.

## Later (not part of done)
- [ ] Knob **press** on the Standard profile: our full standard write set it to the official default (lighting
      on/off); the user didn't say yet what it did before (turns were restored to volume, 2026-10-11).
- [ ] Ubuntu/Debian and Fedora packaging (as in OpenNollie's notes: python3-hid / python3-hidapi, PySide6, 7zip).
- [ ] Ideas the official app lists but never implemented: music-reactive lighting (live mode, PipeWire monitor),
      per-application profile switching (needs active-window info; KWin script on Wayland).
- [ ] Other GK6X models: only tested on the GK104 Pro; physical layouts / firmware quirks for others need owners.

## Roadmap & status

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

### Phase 0: Environment ✅ (2026-10-11)
- [x] Project skeleton, git, udev rule (installed 2026-10-11; dongle if3 only), capture tooling, prior art cloned
- [x] Read-only handshake from Linux works: `python3 -m opengk6x info` (model 656802056, fw `0x84223311`)

### Phase 1: Reverse engineering ✅ (2026-10-11)
- [x] Official app EXE from the user (GK6+ 8.0.1) unpacked: Electron, plain JS, `node-hid`
- [x] 8.0.7 (from Epomaker, via the user) supports model 656802056; unpacked; model data + library decoded
- [x] Protocol from code: command table, profiles/modes, offline profile write sequence, key/Fn tables + driver
      values, macro format, lighting data format, CMF files → `docs/PROTOCOL.md`
- [ ] Still to read: `cmleplayer.js`/`cmlemanager.js` (online lighting playback), `macro.js` (recorder), UI pages
      for the remaining options (LE category filter, key-function menus)
- [ ] Capture: the official app in the VM (or wine) while the user goes through every page → `captures/`
- [x] *Feature catalog* filled in from the app
- [ ] Wireless: does the dongle answer the handshake? Bluetooth: is there a config channel at all?

### Phase 2: Protocol library
- [x] Offline profile writer = the app's `profile.js`, byte for byte (`profile.py`; golden tests from the app's own
      code via `tools/re/golden_profile.js`). CLI `keys`, `mode`, `profile write SLOT [--set KEY=BINDING]`
- [x] **First hardware write (2026-10-11): profile 1 = default + App→Q.** User confirmed Menu types q; switched back
      to standard with `opengk6x mode standard`. Lighting in profiles: see findings
- [x] Bindings catalog, profile store (changes from the standard layout), macros, import/export (official + backup)
- [x] Verified on hardware: macros (normal + Fn layer with our registration fix), profile_N keys, knob remap;
      Space long-press types don't work on this firmware (hidden)
- [~] Wireless: config over the receiver impossible (no answer); custom effects carry over; profiles 1–3 over
      wireless still to test (switch to profile 1 on the cable, then flip to 2.4 GHz)
- [x] Lighting: custom effects list (standard profile `DriverLE`, mode 1, no `0B`), effect player/preview, editor
- [x] Custom list written on hardware by the user from the GUI (3 library effects): works, Fn+− cycles them;
      effects run much slower on the keyboard than the 50 ms-tick preview (accepted by the user)
- [x] Online mode core (`online.py`) verified on hardware: typing works, key reports, frames ~17 ms
- [x] Live mode (`live.py` + GUI Live page + tray + `--tray` autostart + CLI `live run`): effect at full speed,
      typing effects (glow / ripple), key actions (command / URL / text / macro via `15 02`), exit profile;
      start/stop verified through the GUI controller on hardware
- [ ] User test of live mode: action keys not typing, text/macros typed via `15 02`, typing effects, tray

### Phase 3: App
- [x] CLI (`info keys actions mode bind unbind profile macro export import setup-data`)
- [x] GUI `python3 -m opengk6x.gui` (Keys, Macros, Lighting info, Keyboard pages); offscreen screenshots checked;
      launched on the user's desktop 2026-10-11 for a first look
- [ ] Packaging (PKGBUILD, desktop file, install script), README

## Open questions
- Does the keyboard check the packet CRC? (OpenRGB sends a different one and works.)
- What does the firmware do with a profile write if the keyboard is in that profile at the time?
- Can the keyboard report what's stored on it? The official app never reads profiles back (keeps its own copy).
- Is the `1ea7:0067` dongle this keyboard's receiver? (Same vendor ID and config interface; likely.)
- Can the per-model data be shipped? It's the vendor's (proprietary). Options: read it from the user's copy of the
  official app at runtime (like OpenNollie's layout presets), or write our own GK104 Pro layout.

## Findings log
<!-- Newest first. Format: YYYY-MM-DD: finding (source: capture/file/test) -->
- 2026-10-11: **The standard profile's key table is writable and is what the keyboard uses over 2.4 GHz.**
  Profiles 1–3 aren't used over 2.4 GHz (profile 1 stays selected: back on the cable its remaps return). The
  official app never writes standard keys (its UI forbids it) but does write standard *lighting* (the custom
  effects list), which is why effects carry over. Tests (user's OK, minimal first): a single 4-byte `22 01` write
  (Menu → q) → reply `22 00`, Menu typed q on the cable **and on 2.4 GHz**; full clear + table (`21 01 01`,
  `22 01` ×10) → `00`, everything normal. **Macros (`25 01`) and the Fn layer (`31 01`) are refused for mode 1:
  reply status `F0`** (an F5 macro key did nothing; a single Fn entry had no effect). So: remaps everywhere via the
  Standard profile; Fn layer and macros only in profiles 1–3, cable only. The full write puts the official profile 1
  default values in every key; the factory values might differ (asked about the knob). (source: hardware + user)
- 2026-10-11: Live mode verified by the user: effect speed/brightness, typing effect colors (after fixing a max()
  blend that hid every color but white), key actions (command/URL/text/macro), tray. A yellow-green "4" key after
  switching from 2.4 GHz back to the cable was the keyboard's own status light (went away by itself).
- 2026-10-11: **Parity check of the remaining official features**: the 4 "combination" effects (sync RGB, music
  volume ×2, CS:GO) have no event source in 8.0.7 (no audio capture, no game-state server; only dead
  `g_LEGameEventMap` code), and 8.0.7 has no per-application profile switching (`Application.AppPath` is only used
  by the online "open app" task). Firmware update: `firmware.js` is empty. So nothing else to port. (source: vendor-app)
- 2026-10-11: **No configuration over 2.4 GHz**: with the keyboard linked to the receiver, the receiver still
  doesn't answer the handshake, and `0B 02` sent through it gets no reply. Custom lighting effects carry over to
  wireless; whether offline profiles 1–3 apply over wireless is still open (the user's first test didn't switch to
  profile 1 first). (source: user)
- 2026-10-11: **Online mode works**: entering as the app does (ping, `0B 05`, ping, `15 03 01`, `16 01` key table
  with 0-fill, `16 03` all FF, `17 01`) keeps typing normal and sends `15 04` key reports (only on changes; nothing
  while idle). A `1A` frame (10 chunks + `1A 02`) takes ~17 ms (≈59 fps possible). The keyboard does **not** leave
  online mode by itself when pings stop (it stayed blue for minutes). Bug found: hidapi `read(n, 0)` *blocks*, which
  froze the first live test on frame 1; Ctrl+C mid-read then skipped the exit. (source: hardware + user)
- 2026-10-11: **Hardware checklist (profile 1, user):** macros on normal keys ✓ (slots 0 and 1); `profile_standard`
  on Fn+1 ✓; Menu→q ✓. **Fn-layer macros run only if their slot is also on a normal-layer key**: Fn-only slot 1
  typed nothing; slot also on F7 ✓; Fn-only slot 1 *registered at the unused matrix position 9* ✓ (our fix,
  `profile._register_fn_macros`; spare positions from `layouts.spare_indexes`). **Space "long-press" types
  (`0x0A0C00MM`) don't work on this firmware**: tap = space, holding just repeats (hidden for the GK104 Pro).
  **Physical GK104 Pro:** no PrtSc/ScrLk/Pause and no Ins/Home/PgUp/Del/End/PgDn keys; a **knob** in their place
  and a **screen** over the nav block. The knob = the template's "Scroll Lock" knob variant: turn left = matrix 125
  ("Scroll Lock VOLU"), turn right = 126 ("VOLD"), press = 124 ("MUTE"); defaults brightness −/+ and lighting
  on/off, Fn + turn = volume. Knob press remapped to Mute ✓. (source: hardware + user)
- 2026-10-11: **Custom effects list works** (written from the GUI by the user, 3 library effects, 40 packets): Fn+−
  cycles them; they run much slower than the preview. **Reply status `01` is the normal OK for lighting writes
  (`26`/`27`)**, `00` for `21`/`22`/`31`; so in profiles 1–3 the lighting data was accepted, just not used on this
  model. (Corrects the earlier "rejected" reading.) (source: hardware + user)
- 2026-10-11: **Effect playback** (app `cmleplayer.js`, 50 ms per tick): frames expanded by Count; a lit LED takes
  the color of the first LEConfig listing it; type 1 turns the hue 360/Count° per tick, type 2 fades in over Count
  ticks, holds StayCount, fades out, holds dark. The keyboard's frame data is only a bitmap of lit LEDs, so colors
  come only from LEConfigs. The standard profile's custom list has **5 slots** in the UI (`DriverLE[0..4]`). The
  library offered per keyboard is the UI bundle's default `les` list (53; `LeCate` = layout it was drawn for,
  `LeType` combination = online-only); `setup-data` extracts it to `res/data/le/library.json`. (source: vendor-app)
- 2026-10-11: **Leaving out the lighting packets keeps the profile's lighting.** Profile 1 rewritten without
  `21 m 05`/`26`/`21 m 06`/`27` (24 packets): the white effect the user had picked with Fn+=/− stayed. With them (the
  official app's way) the profile came up dark. (source: hardware + user)
- 2026-10-11: **First write works.** `opengk6x profile write 1 --set App=q` (40 packets, 0.2 s): Menu typed q in
  profile 1. Replies: `00` for `21`/`22`/`31`, **`01` for `26`/`27`**, `0B` echoes the mode; all CRCs valid.
  **Lighting on this model** (`hasModeLe: false`): profiles 1–3 don't use lighting data (the official UI greys
  the picker out for them; `01` turned out to be the normal lighting ack), so profile 1 came up dark until the user pressed **Fn+=** (built-in
  effects) / **Fn+−** (the user's **custom effects**, stored as the standard profile's `DriverLE` list). Fn+↑/↓ is
  brightness (firmware), not profile 1's Fn+F1/F2 entries. The user has custom effects in the keyboard that can't be
  read back. (source: hardware + user)
- 2026-10-11: **GK6+ 8.0.7 supports this keyboard** (model 656802056 / FWID `0x84223311`, "104RGB"); keymap.js has
  the same 124 keys as pixeltris's copy. Same command set as 8.0.1; still wired-only (`0907`), so **the official app
  can't configure over the dongle or Bluetooth** either. The app writes offline profiles 1–3 (modes 2–4) whole
  (clear + chunks per data type) and **never writes the standard layer's keys** (mode 1 gets only its effects list).
  Library: 183 effects, 148 macros (CMF-obfuscated, decoded). Key functions: 207 driver values. Factory reset on the
  keyboard: Fn+Esc+Q. (source: vendor-app/asar 8.0.7)
- 2026-10-11: **The user's EXE (GK6+ 8.0.1) can't drive this keyboard**: its driver rejects any firmware ID that isn't
  in `resources/device/modellist.json` ("invalid device"), and `0x84223311` / model 656802056 aren't there (8.0.1
  dropped 656802039–058 vs the Windows-app V6 data). It also only knows the wired PID `0907` (+ bootloader `0905`), no
  dongle. Its `Env.json` points at jikedingzhi driverID=90, which pixeltris lists as the Mac download. Epomaker's
  download page lists **GK6X_Setup_8.0.7.zip** (144 MB, 2025-07-07) for the GK104 PRO. (source: vendor-app/asar,
  epomaker.com/blogs/software/skyloong-driver)
- 2026-10-11: App protocol (`cmd.js`) = pixeltris's, with names: `01 09` is the **key matrix** (16 × 8 here; we
  had called it buffer sizes), `01 02` a 48-bit device ID, firmware version shown `v<hi>.<lo>` = v5.118. New:
  `17 01` built-in LE config, `15 01..04` online key/mouse events + key reports, `16` online key table, `24` mode-LE,
  and two to never send: `41 01` (rewrites USB VID/PID) and boot modes (`1ea7:0905` "CDBoot"). (source: vendor-app)
- 2026-10-11: **The dongle (`1ea7:0067` if3) accepts writes but doesn't answer the handshake** (no report at all
  within 1 s) while the keyboard is in wired mode. Retest with the keyboard switched to 2.4 GHz. The udev rule
  works: on the dongle only if3 is user-accessible. (source: hidapi on host)
- 2026-10-11: **Handshake works from Linux on the wired interface**: `01 09` → buffers 16, 8; `01 01` → firmware ID
  `0x84223311`, bytes 5.118; `01 08` → model **656802056** (with its own CRC, valid). All replies have valid CRCs
  (CRC-16/CCITT-FALSE, pixeltris form). The pair matches the "104RGB" entry in the vendor's 2021 `modellist.json`.
  (source: `opengk6x info`, reference/pixeltris-GK6X)
- 2026-10-11: OpenRGB computes its packet CRC including the hidapi report-ID byte, which gives a different value from
  the one replies use; OpenRGB's driver works anyway, so the firmware may skip CRC checks on some commands. We use the
  form the keyboard itself uses. (source: OpenRGB SkyloongGK104ProController.cpp)

## Decision log
- 2026-10-12: **Knobs are one control** (user: the first try, a row of 3 drop-downs over the picture, was confusing).
  `layouts.Knob` (left/right/press key-map names); `Layout.knobs`, or `template_knobs` (the "all" layout: every
  VOLU/VOLD/MUTE variant triple, `find_knobs`). The picture draws a knob (dial = press, sides = turns, each showing
  its action); selecting it shows a 3-part panel in the editor; the list assigns to the chosen part, knob actions
  suggested first (`KNOB_ACTIONS`). Knob parts in `display_keys` have `Shape: "knob"` (no LED).
<!-- Newest first. Format: YYYY-MM-DD: decision; reason -->
- 2026-10-11: **Standard profile editable (keys only)**, first tab in the GUI, `bind standard …` in the CLI; profiles
  1–3 say they're cable-only on the GK104 Pro (`Layout.wireless_standard_only`). Reason: the user wants remaps on
  2.4 GHz, and the keyboard uses the standard layout there.
- 2026-10-11: **Physical layouts** (`layouts.py`, our data): the model's key map is a multi-variant template; a
  layout picks the real keys (GK104 Pro: knob drawn as 3 round keys at PrtSc/ScrLk/Pause, screen over the nav
  block). Stored per model in `~/.config/opengk6x/<model>/keyboard.json`; default GK104 Pro for 656802056.
  Every profile starts from the official profile 1 default (profiles 2/3 defaults are a Mac layout / Backspace =
  Delete; the Mac layout is a preset).
- 2026-10-11: The user handed over ownership of the plan ("make it more intuitive and better than the original, with
  all its features"). Order: bindings/profiles/macros (CLI) → import/export (official files + our backup) → GUI →
  custom effects (Fn+−) → online mode, packaging, wireless check.
- 2026-10-11: **Profiles are written without lighting data on models with `hasModeLe` false** (`build(lighting=
  False)`); the firmware doesn't use it, and the clears reset the user's effect choice. Fn-layer macros get their own
  slot (the app's bug gives them slot 0); `app_compatible=True` keeps the app's exact output for golden tests.
- 2026-10-11: Our data = profiles as *changes from the model's defaults* (key names → binding text) + a macro
  library, in `~/.config/opengk6x`; compiled to the official JSON, then by `profile.py`. A fingerprint of the
  written packets tells whether the keyboard still has what's stored. Slots never written by OpenGK6X are "unknown"
  and need confirmation (they may hold the user's settings from the official app).
- 2026-10-11: Same stack and layout as OpenNollie (Python + hidapi + PySide6); reason: proven on this machine, and
  the user asked to do "the same" as for the Nollie.
- 2026-10-11: The udev rule grants only the config interface (if1 wired, if3 dongle), not the interfaces that
  carry keystrokes; reason: a user-readable keyboard hidraw node lets any user process log keystrokes.

## Working conventions
- Ask the user before any `sudo` command or system change (packages, udev, modules, VM config).
- Keep this file current: update status, findings and decisions in the same session the work happens.
- Hardware writes follow the official app's exact packets (code + capture). Never fuzz unknown commands.
  Read-only queries first; verify each write by reading it back where the firmware allows it.
- **This is the user's only keyboard.** A bad keymap can leave them unable to type. Never write a layout that
  leaves no way back (keep Fn and a way to reach the Standard profile). Switch back to standard with `0B 01` from
  the CLI (mouse-only) or the keyboard; last resort **Fn+Esc+Q** (factory reset).
- The Standard profile's **keys** are written like a profile (clear + table + `0B 01`); never its Fn layer or
  macros (refused anyway). Confirm before the first write (it changes the keyboard's own layout).
- **Don't write the standard profile's lighting (mode 1, `21 01 06` / `27 01`) without the user's explicit OK**:
  it holds the user's custom effects (Fn+−), which can't be read back, so a write replaces them for good.
- Never send firmware-update / bootloader commands, `03` restart variants that enter boot modes, or `41 01`
  (rewrites the keyboard's USB VID/PID).
- The vendor app and its data are proprietary: keep them out of git; our code is written fresh from the documented
  protocol, not copied.
