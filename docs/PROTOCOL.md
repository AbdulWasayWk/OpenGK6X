# GK6X protocol (Skyloong GK104 Pro)

Status legend: **✔ verified** on the user's keyboard · **ref** from prior art, not yet verified here ·
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

The official app (GK6+ 8.0.1, `src/libs/cmd.js`, `src/drivers/cor-m3-mk.js`) probes with `01 01`, then `01 02`, then
`01 08`, and rejects the keyboard unless the firmware ID is in its `modellist.json`.

| Request | App name | Reply payload (from byte 8) | User's keyboard |
|---|---|---|---|
| `01 01` | VER | u32 firmware ID, u16 version (shown `v<hi>.<lo>`) | `0x84223311`, **v5.118** |
| `01 02` | DEVICE_ID | 6 bytes, little-endian 48-bit ID | not sent yet |
| `01 08` | MODEL_ID | u32 model ID, u16 `0xFFFF`, u16 CRC16 of the previous 6 bytes | **656802056** |
| `01 09` | MATRIX | u8 key columns, u8 key rows | 16 × 8 (key tables = 16·8·4 = 512 B) |

Model 656802056 + FWID `0x84223311` = "104RGB" in the vendor data shipped with pixeltris (updated to the Windows app
V6.0.0.76 on 2026-03-05). **GK6+ 8.0.1 doesn't list it** (it dropped models 656802039–058); Epomaker lists 8.0.7
for the GK104 PRO.

## Opcodes (app 8.0.1 `cmd.js` ✔ in code; on hardware only `01` so far)

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

Offline profile write (app `libs/profile.js`): for each type, `21 <mode> <type>` then the data in chunks, then
`0B <mode>` to switch to it. Detail to be documented from `profile.js`.

Online mode (`libs/driver.js setOnlineMode`): Ping, `0B 05`, Ping every 2 s, `15 03 01`; the PC then handles key
reports (macros, app launch, per-key lighting) and renders lighting effects itself (`cmleplayer.js`) via `1A`.

## Open questions

- Is anything stored in the keyboard readable (keymap, lighting, macros)? pixeltris only writes. If not, the app
  must keep its own copy of what it wrote.
- Built-in lighting: `17 01` (online) and `24` mode-LE data (offline); formats to be read from `profile.js`.
- Config over the 2.4 GHz dongle and over Bluetooth.
