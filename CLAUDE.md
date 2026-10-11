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
- Git: local repo, branch `master`, GPL-3.0-or-later (compatible with pixeltris MIT and OpenRGB GPL-2.0+).
  No remote yet; push only when the user asks.

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
| Device | detect (VER/DEVICE_ID/MODEL_ID), firmware version, picture of the keyboard (`img/device_*.png`, `keymap.js` positions) | [~] `info` |
| Profiles | standard (effects list only) + offline profiles 1–3 stored in the keyboard; switch with `0B` or Fn keys; online (PC-driven) profiles; profile import/export (`.cmf`) | [ ] |
| Key mapping | per key and per Fn key: any key + modifiers, combos (Ctrl+C…), disable, mouse buttons, media keys, lighting controls, profile switching, Space dual-role (hold = modifier), sleep, macros; online-only: open app/URL/file | [ ] |
| Lighting | effect library (183 `.le`, 6 shown to all models + category 840 for ours), main effect per profile, per-key press lighting, per-key static colors, effect editor (frames + color logic: static / cycle / breathing), standard-mode effect list (Fn+−/+) | [ ] |
| Macros | library (148 presets), recorder/editor (key/mouse down-up, delays), repeat count, stop mode, assign to keys | [ ] |
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

## Roadmap & status

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

### Phase 0: Environment ✅ (2026-10-11)
- [x] Project skeleton, git, udev rule (installed 2026-10-11; dongle if3 only), capture tooling, prior art cloned
- [x] Read-only handshake from Linux works: `python3 -m opengk6x info` (model 656802056, fw `0x84223311`)

### Phase 1: Reverse engineering
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
- [ ] Layers + keymaps (with a safe test plan, see conventions), Fn layer
- [ ] Lighting: built-in modes, per-key static, press lighting, direct mode
- [ ] Macros
- [ ] Whatever else the catalog lists (profiles, polling rate, Win-lock, reset, …)

### Phase 3: App
- [ ] CLI, then a PySide6 GUI with a picture of the keyboard; packaging (PKGBUILD, desktop file)

## Open questions
- Does the keyboard check the packet CRC? (OpenRGB sends a different one and works.)
- What does the firmware do with a profile write if the keyboard is in that profile at the time?
- Can the keyboard report what's stored on it? The official app never reads profiles back (keeps its own copy).
- Is the `1ea7:0067` dongle this keyboard's receiver? (Same vendor ID and config interface; likely.)
- Can the per-model data be shipped? It's the vendor's (proprietary). Options: read it from the user's copy of the
  official app at runtime (like OpenNollie's layout presets), or write our own GK104 Pro layout.

## Findings log
<!-- Newest first. Format: YYYY-MM-DD: finding (source: capture/file/test) -->
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
<!-- Newest first. Format: YYYY-MM-DD: decision; reason -->
- 2026-10-11: Same stack and layout as OpenNollie (Python + hidapi + PySide6); reason: proven on this machine, and
  the user asked to do "the same" as for the Nollie.
- 2026-10-11: The udev rule grants only the config interface (if1 wired, if3 dongle), not the interfaces that
  carry keystrokes; reason: a user-readable keyboard hidraw node lets any user process log keystrokes.

## Working conventions
- Ask the user before any `sudo` command or system change (packages, udev, modules, VM config).
- Keep this file current: update status, findings and decisions in the same session the work happens.
- Hardware writes follow the official app's exact packets (code + capture). Never fuzz unknown commands.
  Read-only queries first; verify each write by reading it back where the firmware allows it.
- **This is the user's only keyboard.** A bad keymap can leave them unable to type. Like the official app, write
  keys only to offline profiles 1–3 (modes 2–4), never the standard layer (mode 1). Switch back to standard with
  `0B 01` from the CLI (mouse-only) or the keyboard; last resort **Fn+Esc+Q** (factory reset).
- Never send firmware-update / bootloader commands, `03` restart variants that enter boot modes, or `41 01`
  (rewrites the keyboard's USB VID/PID).
- The vendor app and its data are proprietary: keep them out of git; our code is written fresh from the documented
  protocol, not copied.
