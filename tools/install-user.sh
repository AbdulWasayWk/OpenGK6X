#!/usr/bin/env bash
# Install OpenGK6X for the current user from this checkout (no root needed):
#   ~/.local/bin/opengk6x, opengk6x-gui                     commands (running the code in this checkout)
#   ~/.local/share/applications/opengk6x.desktop            app-menu entry
#   ~/.local/share/icons/hicolor/scalable/apps/opengk6x.svg icon
#
#   tools/install-user.sh [GK6X_Setup_8.0.7.zip]   install; with the official installer, also copy its keyboard data
#   tools/install-user.sh --remove                 undo (your profiles, macros and effects in ~/.config/opengk6x stay)
#
# Device access needs a udev rule (root): tools/setup-dev.sh udev (OpenRGB's rules also cover the wired keyboard).
# (For a system-wide install use the PKGBUILD in packaging/ instead; don't use both.)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
BIN=${XDG_BIN_HOME:-$HOME/.local/bin}
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
APPS=$DATA/applications
ICONS=$DATA/icons/hicolor/scalable/apps
AUTOSTART=${XDG_CONFIG_HOME:-$HOME/.config}/autostart/opengk6x-live.desktop

if [[ ${1:-} == --remove ]]; then
    pkill -u "$USER" -f "python3 -m opengk6x.gui" 2>/dev/null || true
    rm -f "$BIN"/opengk6x{,-gui} "$APPS/opengk6x.desktop" "$ICONS/opengk6x.svg" "$AUTOSTART"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
    echo "removed. Kept: your data in ~/.config/opengk6x, ~/.local/state/opengk6x and the keyboard data in"
    echo "$DATA/opengk6x/vendor (delete them to remove everything). Device access rule, if you added it:"
    echo "    sudo rm /etc/udev/rules.d/70-opengk6x.rules"
    exit 0
fi

missing=()
python3 -c "import hid" 2>/dev/null || missing+=(python-hidapi)
python3 -c "import PySide6" 2>/dev/null || missing+=(pyside6)
command -v 7z >/dev/null || missing+=(7zip)
if (( ${#missing[@]} )); then
    echo "missing packages: ${missing[*]}"
    echo "    sudo pacman -S --needed ${missing[*]}"
    exit 1
fi

mkdir -p "$BIN" "$APPS" "$ICONS"
for name in opengk6x opengk6x-gui; do
    module=opengk6x
    [[ $name == opengk6x-gui ]] && module=opengk6x.gui
    printf '#!/bin/sh\nPYTHONPATH=%q exec python3 -m %s "$@"\n' "$REPO" "$module" > "$BIN/$name"
    chmod +x "$BIN/$name"
done
install -m644 "$REPO/opengk6x/gui/opengk6x.svg" "$ICONS/opengk6x.svg"
# Icon by file path: Plasma's icon cache may not know an icon newly added to ~/.local/share/icons
sed -e "s|^Exec=opengk6x-gui|Exec=$BIN/opengk6x-gui|" -e "s|^Icon=opengk6x$|Icon=$ICONS/opengk6x.svg|" \
    "$REPO/packaging/opengk6x.desktop" > "$APPS/opengk6x.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
echo "installed: $BIN/opengk6x, $BIN/opengk6x-gui, app-menu entry \"OpenGK6X\""
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on your PATH" ;; esac

if [[ -n ${1:-} ]]; then
    "$BIN/opengk6x" setup-data "$1"
elif [[ ! -d $DATA/opengk6x/vendor ]]; then
    echo "next: copy the keyboard data from the official app once (download GK6X_Setup_8.0.7.zip from Epomaker):"
    echo "    opengk6x setup-data ~/Downloads/GK6X_Setup_8.0.7.zip"
fi

if ! grep -qsi '1ea7' /etc/udev/rules.d/*.rules /usr/lib/udev/rules.d/*.rules; then
    echo "next: give your user access to the keyboard (once, needs sudo), then replug it:"
    echo "    tools/setup-dev.sh udev"
fi
