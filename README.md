# OpenGK6X

An open-source Linux app for **GK6X keyboards**, built for the **Skyloong GK104 Pro**: key remapping, layers,
Fn keys, macros and lighting, without the official Windows software.

**Status: early work in progress.** Today it can identify the keyboard (read-only). Reverse engineering the
official app is next. See `CLAUDE.md` for the plan and `docs/PROTOCOL.md` for the protocol.

## Try it

```bash
python3 -m opengk6x info
```

Needs `python-hidapi` (`sudo pacman -S python-hidapi pyside6`) and access to the keyboard's configuration
interface. If OpenRGB is installed, the wired keyboard already works. For the 2.4 GHz dongle, or without OpenRGB,
install the udev rule (grants only the configuration interface, not the keys you type):

```bash
tools/setup-dev.sh udev
```

## Development

```bash
python3 -m unittest discover -s tests -t .
```

Prior art: [pixeltris/GK6X](https://github.com/pixeltris/GK6X) (MIT) and OpenRGB's Skyloong GK104 Pro driver.

## License

GPL-3.0-or-later. Not affiliated with Skyloong or the makers of the GK6X software.
