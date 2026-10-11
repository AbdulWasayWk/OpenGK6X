# OpenGK6X

An open-source Linux app for **GK6X keyboards**, made for the **Skyloong GK104 Pro**: remap keys, set up the Fn
layer, record macros and design lighting effects, without the official Windows software. Everything is stored in the
keyboard, so it keeps working with no software running, on any computer, over the cable, the 2.4 GHz receiver or
Bluetooth.

![Keys page](docs/screenshots/keys.png)

## What it can do

- **Three profiles of your own** (profile 1–3) on top of the keyboard's standard layout. For each key, normal and
  with **Fn held**, pick anything the official app offers:
  - any key or **shortcut** (Ctrl+Shift+T, Super+D, …), or press the shortcut to capture it
  - media keys, browser keys, calculator, mouse buttons, sleep
  - lighting controls (brightness, effect speed, on/off)
  - **switch profile** keys
  - **Space dual-role**: tap for Space, hold for Ctrl / Shift / Alt / Super
  - **macros**, run N times, while held, or until pressed again
- **Macros**: record what you type (with the pauses), or build them step by step (key press/release/tap, waits,
  mouse clicks); a compact text form (`+ctrl c -ctrl 100ms enter`) for quick edits.
- **Lighting**: the official effect library with a live animated preview, your own effects (one color, paint the
  keys, breathing, color cycle, rainbow wave in any direction, sweeping band), and the **custom effects list** the
  keyboard cycles with **Fn + −**.
- **Import and export**: profiles (`.gpr`/`.cmf`), macros (`.cms`) and effects (`.le`) from and for the official app,
  or its whole data folder; plus one-file OpenGK6X backups.
- A command line (`opengk6x`) for all of it.

Better than the original: every profile starts from the layout printed on the keys (the official app's defaults for
profiles 2 and 3 are a Mac layout and "Backspace = Delete"; the Mac layout is offered as a starting point instead),
**macros work on the Fn layer** (the official app gives them all the first macro), and writing a profile **keeps the
lighting effect you picked** (the official app resets it).

![Lighting page](docs/screenshots/lighting.png)

## Install (Arch Linux)

1. **Dependencies:** `sudo pacman -S python-hidapi pyside6 7zip`
2. **OpenGK6X itself**, either:
   - as a package: `cd packaging && makepkg -si` (builds from the GitHub repo), or
   - for your user from this folder (no root): `tools/install-user.sh` — adds `opengk6x`, `opengk6x-gui` to
     `~/.local/bin` and "OpenGK6X" to the app menu. `tools/install-user.sh --remove` undoes it.
3. **Keyboard access** (once): `tools/setup-dev.sh udev` installs `packaging/70-opengk6x.rules` (the package does
   this for you). It grants your user the keyboard's configuration interface only, not the keys you type. Then
   unplug and replug the keyboard.
4. **Keyboard data** (once): the layout and defaults of each keyboard model, and the effect library, come from the
   official app (they belong to its maker, so they aren't included). Download *GK6X Setup 8.0.7* from Epomaker's
   [Skyloong driver page](https://epomaker.com/blogs/software/skyloong-driver), then:
   ```
   opengk6x setup-data GK6X_Setup_8.0.7.zip
   ```
   It copies only that data into `~/.local/share/opengk6x/vendor`; nothing from the official app runs.

## Using it

Connect the keyboard **with its USB cable** (settings are written over the cable; afterwards they work over every
connection). Open **OpenGK6X** from the app menu.

- **Keys**: choose profile 1, 2 or 3. A profile OpenGK6X hasn't written yet is marked *not set up*: the keyboard
  may still hold settings from the official app, which keyboards can't send back. Start from the standard layout
  (or the Mac layout), click a key, choose what it does, and press **Apply to keyboard**. The keyboard switches to
  that profile; **Use on keyboard** switches to it without writing. The standard profile is the keyboard's own
  layout and isn't changed.
- **Macros**: **New**, then **Record…** or add steps. Assign macros to keys on the Keys page. After editing a macro,
  apply the profiles that use it (the Keys page shows them as changed).
- **Lighting**: click effects to preview them; **New…** opens the effect editor. Add up to five effects to the
  custom list and press **Write to keyboard**. The first time, this replaces the custom effects the keyboard came
  with or the official app wrote. On the keyboard: **Fn + =** built-in effects, **Fn + −** your custom effects,
  **Fn + ↑/↓** brightness, **Fn + ←/→** speed. The keyboard plays effects more slowly than the preview.
- **Keyboard**: connection and firmware, switching profiles, backups, official app files, the keyboard's own
  shortcuts.

**If something goes wrong**: switch back to the standard profile (Keyboard page, or `opengk6x mode standard`), or
hold **Fn + Esc + Q** to reset the keyboard to factory settings (then use "I reset the keyboard" on the Keyboard
page, and apply your profiles again).

### Command line

```
opengk6x info                                   # model and firmware
opengk6x keys | actions [search]                # key names | what keys can do
opengk6x bind 2 "Caps Lock" esc                 # change a key (saved, then written); --fn for the Fn layer
opengk6x bind 2 F5 macro:greet --repeat while_held
opengk6x unbind 2 "Caps Lock" | profile list | profile show 2 | profile apply 2 | profile reset 2
opengk6x macro set greet "+shift h -shift i 50ms enter" | macro list | macro delete greet
opengk6x effects [search] | lighting show | lighting set "Rainbow Waves" Flame | lighting apply
opengk6x mode standard|1|2|3                    # switch the keyboard's profile
opengk6x export backup.json | import backup.json
opengk6x import ~/old-windows/GK6XPlus-CMS      # the official app's data folder (or .gpr/.cmf/.cms/.le files)
opengk6x export --official folder/              # files the official app can import
```

## Where things are

- `~/.config/opengk6x/` — your profiles (`<model>/profiles.json`), custom effects list (`<model>/lighting.json`),
  macros (`macros.json`), effects (`effects/`). These are the only record of what's in the keyboard.
- `~/.local/state/opengk6x/` — logs of what was last written.
- `~/.local/share/opengk6x/vendor/` — the official app's keyboard data (`setup-data`).

## Limits

- Settings can only be written over the USB cable (the official app has the same limit).
- On the GK104 Pro, profiles 1–3 don't have their own lighting; the keyboard's effect choice (Fn + = / −) is shared.
- The keyboard can't report what's stored in it.
- Online mode (lighting and key actions run by the PC while the app is open) isn't there yet.

## Development

```
python3 -m unittest discover -s tests -t .      # 35+ tests; no keyboard needed
python3 -m opengk6x.gui                         # run from the checkout
```

`docs/PROTOCOL.md` documents the USB protocol and data formats, `CLAUDE.md` the project's findings and decisions.
The profile writer reproduces the official app byte for byte: `tools/re/golden_profile.js` runs the app's own code
against a fake keyboard, and `tests/golden/` holds its output for the test profiles. Prior art:
[pixeltris/GK6X](https://github.com/pixeltris/GK6X) and OpenRGB's Skyloong GK104 Pro driver.

## License

GPL-3.0-or-later. Not affiliated with Skyloong, Epomaker or the makers of the GK6X software.
