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

| Request | Reply payload (from byte 8) | User's keyboard |
|---|---|---|
| `01 09` | 2 bytes: buffer sizes A, B | 16, 8 |
| `01 01` | u32 firmware ID, u8 minor, u8 major | `0x84223311`, 5.118 |
| `01 08` | u32 model ID, u16 `0xFFFF`, u16 CRC16 of the previous 6 bytes | **656802056** |
| `01 02` | ref: unknown (always -1) | not sent |

Model 656802056 + FWID `0x84223311` = "104RGB" in the 2021 vendor data shipped with pixeltris
(`Data/device/modellist.json`, `Data/device/656802056/`). The official app keys its per-model data on the model ID.

## Opcodes (ref, pixeltris)

| Op | Name | Notes |
|---|---|---|
| `01` | Info | above |
| `03` | Restart keyboard | can reboot into special modes ("CDBoot"); **never send boot-mode variants** |
| `0B` | Set layer | sub = layer: 1 base, 2–4 layers 1–3, 5 driver ("online"). OpenRGB sends `0B 05` on connect and `0B 04` on disconnect (**?** why 4) |
| `0C` | Ping / keep-alive | app pings every ~300 ms while connected; OpenRGB sends one on connect |
| `15` | Driver macro | driver layer only |
| `16` | Driver layer: set key values | sub 1 keys, 2 Fn keys, 3 press-lighting |
| `17` | Driver layer: config | |
| `18` | Key callback (keyboard → PC) | driver layer |
| `1A` | Driver layer: real-time lighting | sub 1 = data, 2 = show. Per-key `R G B brightness` × 132 (528 B); OpenRGB "Direct" mode |
| `21` | Layer: reset data type | sub = layer, byte 2 = type: 1 keys, 3 LE data, 4 macros, 5 press-lighting, 6 lighting, 7 Fn keys |
| `22` | Layer: set key values | u32 "driver value" per key (logic code order) |
| `23`, `24` | ? | |
| `25` | Layer: set macros | `AA 55` magic, CRC, actions (key, modifier, state, type, delay) |
| `26` | Layer: set press-lighting effect | |
| `27` | Layer: set lighting | static per-key colors or frame-based dynamic effects |
| `31` | Layer: set Fn key values | |

Key data: per-model `keymap.js` (key name, logic code, location code, position) and "driver values" (u32 per
action) in the vendor data. Layers and Fn layers are written whole (reset type, then all values).

## Open questions

- Is anything stored in the keyboard readable (keymap, lighting, macros)? pixeltris only writes. If not, the app
  must keep its own copy of what it wrote.
- Built-in lighting modes (`ModeLE` / `LESet` in profile.json: model, sub-model, brightness, speed, direction, color):
  which opcode sets them on this board?
- Config over the 2.4 GHz dongle and over Bluetooth.
- Firmware version format: shown as `5.118` here (major = byte 13, minor = byte 12); compare with the official app.
