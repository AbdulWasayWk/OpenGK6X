# GK6X protocol (Skyloong GK104 Pro)

Status legend: **✔ verified** on the user's keyboard · **✔ in code** read in the official app (GK6+ 8.0.7,
`vendor-app/asar/src`) but not yet seen on the wire · **ref** from prior art, not yet verified here ·
**?** unknown. Sources: pixeltris/GK6X (MIT, C#, archived 2026-03) and OpenRGB `SkyloongController`
(GPL-2.0-or-later). Both are cloned in `reference/` (gitignored). The official app (`vendor-app/`) and
captures will replace "ref" with "✔" as we go.

## Transport ✔

| Link | USB ID | Config interface | Notes |
|---|---|---|---|
| Cable | `1ea7:0907` "SEMITE USB-HID Gaming Keyboar", bcdDevice 3.00 | **if1**: usage page `0xFF00`, usage `0x50`, 64 B IN (EP 0x83) + 64 B OUT (EP 0x04), no report IDs | if0 = boot keyboard; if2 = report IDs 1 (system), 2 (consumer), 4 (NKRO bitmap), 5 (mouse) |
| 2.4 GHz | `1ea7:0067` "Nordic Semiconductor nRF52 USB Product", bcdDevice 2.01 | **if3**: same report descriptor as wired if1 | if0 keyboard, if1 mouse, if2 system/consumer/NKRO. Whether config passes through the dongle: **?** |
| Bluetooth | ? | ? | **?** |

hidapi: write `0x00` + 64 B; read 64 B. Pick the interface by `usage_page == 0xFF00`.

## Packet framing ✔

Every request and every reply is one 64-byte report:

| Bytes | Meaning |
|---|---|
| 0 | opcode |
| 1 | sub-command (for some opcodes: the layer) |
| 2..5 | opcode-specific: in replies byte 2 = result (1 = OK); in multi-report writes = offset/length (below) |
| 6..7 | CRC16, little-endian |
| 8..63 | payload, 56 (`0x38`) bytes |

**CRC** = CRC-16/CCITT-FALSE (poly `0x1021`, init `0xFFFF`) over all 64 bytes with bytes 6..7 zeroed. ✔ (replies)

Note: OpenRGB computes the CRC over the 65-byte buffer *including* the hidapi report-ID byte and stores it at
buffer bytes 7..8 (= report bytes 6..7). That's a different value from the one above, yet OpenRGB's driver works,
so the firmware may not check the CRC on some commands. Our requests use the pixeltris form (which the replies also use).

**Multi-report writes** (ref): data is split into 56-byte chunks, one report each, carrying the chunk's offset
and length: opcodes `22 25 26 31` use bytes 2..3 = offset (u16 LE), byte 4 = length; opcodes `16 1A 27` use
bytes 2..4 = offset (u24 LE), byte 5 = length (OpenRGB's 0x1A agrees; pixeltris puts offset bits 16..23 at byte 5,
harmless while offsets stay below 64 KiB). Single-report commands leave bytes 2..5 zero (or byte 2 = data type for `21`). Every report gets a reply.

The keyboard also sends **unsolicited reports** (e.g. `0x18` key callbacks in driver mode); skip them when waiting
for a reply.

## Handshake / info (`0x01`) ✔

The official app (GK6+ 8.0.7, `src/libs/cmd.js`, `src/drivers/cor-m3-mk.js`) probes with `01 01`, then `01 02`, then
`01 08`, and rejects the keyboard unless the firmware ID is in its `modellist.json`.

| Request | App name | Reply payload (from byte 8) | User's keyboard |
|---|---|---|---|
| `01 01` | VER | u32 firmware ID, u16 version (shown `v<hi>.<lo>`) | `0x84223311`, **v5.118** |
| `01 02` | DEVICE_ID | 6 bytes, little-endian 48-bit ID | not sent yet |
| `01 08` | MODEL_ID | u32 model ID, u16 `0xFFFF`, u16 CRC16 of the previous 6 bytes | **656802056** |
| `01 09` | MATRIX | u8 key columns, u8 key rows | 16 × 8 (key tables = 16·8·4 = 512 B) |

Model 656802056 + FWID `0x84223311` = "104RGB" in the vendor data shipped with pixeltris (updated to the Windows app
V6.0.0.76) and in **GK6+ 8.0.7** (same keys; new images/positions). GK6+ 8.0.1 didn't list it.

## Opcodes (`cmd.js`, ✔ in code; on hardware only `01` so far)

Write commands put a chunk address and length in the 4 header bytes (u32 LE at byte 2):
**A** = `(len << 16) + addr` → bytes 2..3 addr, byte 4 len; **B** = `(len << 24) + addr` → bytes 2..4 addr, byte 5 len.
Chunks are ≤ 56 bytes; each one is acknowledged (reply byte 1 is read as the ack).

| Op | Sub | App name | Notes |
|---|---|---|---|
| `01` | 01/02/08/09 | VER / DEVICE_ID / MODEL_ID / MATRIX | above |
| `03` | | (restart, pixeltris) | can reboot into boot modes ("CDBoot", USB `1ea7:0905`): **never send** |
| `0B` | mode | CHANGE_MODE | sub = 1 base, 2–4 profiles/layers 1–3, 5 online (driver). The keyboard also **sends** `0B <mode>` when the user switches on the keyboard; the app treats anything but 1 or 5 as "not driver-controlled" |
| `0C` | 00 | Ping | online mode: every 2 s |
| `15` | 01 | MouseEvent | online mode (PC-side macros) |
| `15` | 02 | KeyEvent | online mode |
| `15` | 03 | ToggleKeyReport | payload `01`/`00`: key reports on/off |
| `15` | 04 | (keyboard → PC) | key report: bytes 8..23 = bitmap of pressed key indexes |
| `16` | type | SetKeyTable (B) | online mode key table: type 1 = keys (u32 per matrix index, 512 B), 3 = "game light" keys (1 B per index, `0xFF` = none) |
| `17` | 01 | setLEConfig | 9 B: LE model, sub-model, brightness, speed, direction, R/2, G/2, B/2, enable. App default 240, 1, 18, 3, 0, 0,0,0, 15 |
| `18` | | (keyboard → PC) | macro report, ignored by the app |
| `1A` | 01 | SetLEDefine (B) | online real-time lighting: 132 × `R G B 100` (528 B) in 56 B chunks |
| `1A` | 02 | SaveLEDefine | show the frame |
| `21` | mode | CleanData | byte 2 = data type: 1 keys, 3 mode-LE, 4 macros, 5 light keys, 6 light data, 7 Fn keys |
| `22` | mode | writeKeyData (A) | u32 driver value per matrix index |
| `24` | mode | writeModeLE (A) | built-in lighting config for the profile |
| `25` | mode | writeMacro (A) | macros |
| `26` | mode | writeLightKey (A) | key-press lighting key list |
| `27` | mode | writeLightData (B) | lighting effect data |
| `31` | mode | writeFnData (A) | Fn-layer driver values |
| `41` | 01 | WRITE_MAC_VID ("changePid") | rewrites the keyboard's USB identity: **never send** |

## Profiles ("modes") ✔

**Write replies ✔** (profile 1 write, 2026-10-11): every packet gets `[op, status, 0 0 0 0, CRC, 0…]` with a valid
CRC. Status `00` for `21`, `22`, `31` (accepted: the key change took effect); **`01` for `26`, `27`** (lighting data:
evidently rejected on this model, see *Lighting on this keyboard*); `0B` echoes the mode.

### Lighting on this keyboard ✔ (model config `hasModeLe: false`)
- Offline profiles 1–3 have **no lighting of their own**: the firmware answers `26`/`27` with `01` and shows nothing
  from it. The official UI greys out the effect picker for modes 2–4 when `hasModeLe` is false (it still sends the
  data, since `profile.js` doesn't check).
- The lighting is chosen on the keyboard in every profile: **Fn+=** cycles the firmware's built-in effects,
  **Fn+−** cycles the **custom effects stored as the standard profile's effect list** (`DriverLE`, written to mode 1
  with `21 01 06` + `27 01 …`). Brightness Fn+↑/↓, speed Fn+←/→ (firmware; the Up key flashes as an indicator).
- After our profile 1 write the profile came up dark until the user picked an effect with Fn+=/Fn+−.
- ⚠ The keyboard can't be read back, so writing mode 1's lighting replaces the user's custom effects for good.


`0B <mode>` selects one; the keyboard reports `0B <mode>` when the user switches with Fn keys.

| Mode | App `ModeIndex` | Contents the app writes |
|---|---|---|
| 1 | standard | **lighting effects list only** (`DriverLE`, 5 by default: spectrum cycle, Macice Blue, RGB gradient, windmill, rainbow wave). The app never writes the standard keymap |
| 2, 3, 4 | offline profiles 1–3 | keys, Fn keys, macros, main lighting effect (`ModeLE`), per-key press lighting (`KeyLE`), optional per-key colors (`LEData`) |
| 5 | online (`ModeIndex` 0) | nothing stored: the PC drives keys/lighting while the app runs (`16`, `17`, `1A`, `15`) |

Per-model defaults: `resources/device/<ModelID>/data/profile_offline_{std,1,2,3}.json`, `profile_online_1.json`.

## Offline profile write (`libs/profile.js writeDeviceConfig`) ✔ on hardware (keys)

All writes go to `mode` (2–4, or 1 for the effects list). Chunks ≤ 56 B; the app sleeps 1 ms between chunks on
firmware IDs starting `83`/`84` (ours), 10 ms otherwise. Order:

1. `01 09` (matrix → table size cols × rows × 4 = 512 B)
2. keys: `21 m 01`, then `22 m` chunks (A) of the key table
3. Fn keys: `21 m 07`, then `31 m` chunks (A)
4. per-key colors (only if the profile has `LEData`): `21 m 03`, then `24 m` chunks (A) of 176 × `R G B 100`
5. macros: `21 m 04`, then `25 m` chunks (A) of count × 512 B
6. press-lighting index: `21 m 05`, then `26 m` chunks (A) of 128 B
7. lighting data: `21 m 06`, then `27 m` chunks (**B**)
8. `0B m` if m ≠ 1

### Key table (`22` / `31`)
128 × u32 LE "driver value", indexed by the key's matrix index (`KeySet[].Index` = `LogicCode` in `keymap.js`);
unset entries `FFFFFFFF`. Macro keys: `0A0100xx` with xx = macro slot.

| Driver value | Meaning |
|---|---|
| `0x0200KKMM` | key: HID usage KK + modifier bits MM (01 LCtrl, 02 LShift, 04 LAlt, 08 LWin, 10 RCtrl, 20 RShift, 40 RAlt, 80 RWin). `0x02000000` = disabled. E.g. `0x02000601` = Ctrl+C |
| `0x0101000b` | mouse button bit b: 01 left, 02 right, 04 middle, 08 back, 10 forward |
| `0x0300uuuu` | consumer (media) usage, e.g. `00CD` play/pause, `00E9` volume up |
| `0x0901001x` | toggle custom (10) / key (11) light effect |
| `0x0902000x`, `0x0903000x`, `0x0906000x` | brightness up/down, effect speed fast/slow, backlight switch/pause |
| `0x0A070001..4` | switch to standard / offline 1–3 |
| `0x0A0C00MM` | Space with hold-modifier MM ("LCtrl[LongPress(Space)]") |
| `0x0A0100xx` | macro xx |
| `0x0C000002` | system sleep |

Full list (207 entries, with UI names): app `ui/js/9271.*.js` → `vendor-app/decoded/keyfuncs.json`.

### Macros (`25`)
512 B per macro, slots in order of first use: header `u16 0x55AA, u16 CRC16(actions), u8 count, u8 slot,
u8 stop mode, u8 repeats`, then `count` × 4 B actions `[data0, data1, status, type]`:
type 1 key (data0 = HID usage or 0 with data1 = modifier bit; status 1 down, 2 up), type 2 mouse
(data0 1 left / 2 right; status 1 down, 2 up), type 3 delay (ms = data0 + 256·data1). The app appends `Delay 5`.
Max (512 − 8) / 4 = 126 actions. Macro text format (`.cms`): `[General] Name, ScriptID, Repeats, StopMode` +
`[Script]` lines `KeyDown "Q"`, `Delay 137`, … Note: Fn-layer macros index `pMacroIndex[256 + i]` past the
256-byte index table in the app (looks broken there).

### Press-lighting index (`26`)
128 B by matrix index: `FF` = none, else the number of an effect in the lighting data (0 = the profile's main effect).

### Lighting data (`27`)
Up to 128 KiB − 512. Bytes 0..511: one 16 B header per effect `u32 frame address, u32 frame count, u32 logic
address, u32 logic count` (rest `FF`); effect data from 512 on:
- frames: 26 B each, `u16 3, u16 22, 22 B bitmap` of lit LEDs (176 LED indexes); `Count` in the effect file repeats a frame
- logic ("LEConfigs"): 32 B each, `u8 type, u8 32, 22 B bitmap, R G B 0, u16 data0, u16 data1`.
  Type 0 static color; 1 color cycle (data0 = 360 / Count); 2 breathing (data0 = 100 / Count, data1 = StayCount)
- a profile without an effect file but with `ModeLE.LEData` gets one static frame: `u16 0, u16 704, 176 × R G B 100`

Playback (app `cmleplayer.js`, one tick per 50 ms on the PC; the keyboard runs its own clock): each tick shows one
frame (frames repeated `Count` times); a lit LED takes the color of the first LEConfig whose `Keys` contain it;
type 1 turns the hue by 360/Count° per tick (keyboard data: data0 = ⌊360/Count⌋), type 2 fades in by L/Count per
tick, holds `StayCount` ticks, fades out, holds dark (data0 = ⌊100/Count⌋, data1 = StayCount).

The **custom effects list** (Fn + −) is the standard profile's lighting: ModeIndex 1 with `DriverLE` = up to 5 effect
GUIDs → `21 01 04`, `21 01 05` + `26 01` (all FF), `21 01 06` + `27 01` light data; no `0B` afterwards.

Effect files (`.le`, CMF type LIGHT) are JSON: `{GUID, Name, Frames: [{Count, Data: {led: "0xRRGGBB"}}],
LEConfigs: [{Type, Count, StayCount?, Color, Keys: [led…]}]}`. LED indexes are `LocationCode`s (0..175).

## CMF files (`.cmf` profiles, `.le`, `.cms`) ✔ decoded
32 B header (magic `0x434D4631`, CRCs, time, size, type, 8 B name) + body XORed with a CRC-16 key stream.
`tools/re/cmf_decode.py`. The app keeps user data in `Account/<id>/Devices/<ModelID>/<GUID>.cmf`, `Account/0/LE/`.

## Open questions

- `17 01` LE config (model 240/241, …): used only in online mode; `hasModeLe` is false for our model.
- Readback: the app never reads profiles back from the keyboard, so OpenGK6X must keep its own copy.
- Config over the 2.4 GHz dongle and over Bluetooth: the official app (8.0.7) only drives the wired `0907`.
