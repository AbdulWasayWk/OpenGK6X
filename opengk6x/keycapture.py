"""Linux key codes (evdev, as in linux/input-event-codes.h) ↔ HID keyboard usages, for capturing keys pressed in
the GUI (Qt reports the XKB keycode = evdev code + 8 as the native scan code on X11 and Wayland)."""

# HID usage → evdev code (the kernel's hid-input mapping, page 0x07)
HID_TO_EVDEV = {
    **dict(zip(range(0x04, 0x1E), [30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25, 16, 19, 31,
                                    20, 22, 47, 17, 45, 21, 44])),                      # a-z
    **{0x1E + i: 2 + i for i in range(10)},                                             # 1-9, 0
    0x28: 28, 0x29: 1, 0x2A: 14, 0x2B: 15, 0x2C: 57, 0x2D: 12, 0x2E: 13, 0x2F: 26, 0x30: 27, 0x31: 43,
    0x33: 39, 0x34: 40, 0x35: 41, 0x36: 51, 0x37: 52, 0x38: 53, 0x39: 58,
    **{0x3A + i: 59 + i for i in range(10)}, 0x44: 87, 0x45: 88,                        # F1-F12
    0x46: 99, 0x47: 70, 0x48: 119, 0x49: 110, 0x4A: 102, 0x4B: 104, 0x4C: 111, 0x4D: 107, 0x4E: 109,
    0x4F: 106, 0x50: 105, 0x51: 108, 0x52: 103, 0x53: 69, 0x54: 98, 0x55: 55, 0x56: 74, 0x57: 78, 0x58: 96,
    0x59: 79, 0x5A: 80, 0x5B: 81, 0x5C: 75, 0x5D: 76, 0x5E: 77, 0x5F: 71, 0x60: 72, 0x61: 73, 0x62: 82,
    0x63: 83, 0x64: 86, 0x65: 127, 0x67: 117, **{0x68 + i: 183 + i for i in range(12)},  # F13-F24
    0x85: 121, 0x87: 89, 0x88: 93, 0x89: 124, 0x8A: 92, 0x8B: 94, 0x90: 122, 0x91: 123,
}
EVDEV_TO_HID = {v: k for k, v in HID_TO_EVDEV.items()}
EVDEV_TO_HID[43] = 0x31                                   # backslash (also ISO #)

# evdev code → modifier name (bindings.MODIFIERS)
EVDEV_MODIFIERS = {29: "lctrl", 42: "lshift", 56: "lalt", 125: "lwin",
                   97: "rctrl", 54: "rshift", 100: "ralt", 126: "rwin"}


def from_native_scancode(scancode: int) -> tuple[str, int] | None:
    """Qt nativeScanCode → ("modifier", name) / ("key", HID usage), or None if unknown."""
    code = scancode - 8
    if code in EVDEV_MODIFIERS:
        return "modifier", EVDEV_MODIFIERS[code]
    if code in EVDEV_TO_HID:
        return "key", EVDEV_TO_HID[code]
    return None
