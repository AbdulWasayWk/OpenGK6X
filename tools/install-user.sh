#!/usr/bin/env bash
# Install OpenGK6X for the current user from this checkout (no root needed):
#   ~/.local/bin/opengk6x, opengk6x-gui                     commands
#   ~/.local/share/applications/opengk6x.desktop            app-menu entry
#   ~/.local/share/icons/hicolor/scalable/apps/opengk6x.svg icon
#
#   tools/install-user.sh            install
#   tools/install-user.sh --remove   undo (your profiles, macros and effects in ~/.config/opengk6x stay)
#
# Device access: the wired keyboard needs packaging/70-opengk6x.rules (tools/setup-dev.sh udev; OpenRGB's rules
# also cover it). Model data: run `opengk6x setup-data GK6X_Setup_8.0.7.zip` once.
# (For a system-wide install use the PKGBUILD in packaging/ instead; don't use both.)
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
BIN=${XDG_BIN_HOME:-$HOME/.local/bin}
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
APPS=$DATA/applications
ICONS=$DATA/icons/hicolor/scalable/apps

if [[ ${1:-} == --remove ]]; then
    rm -f "$BIN"/opengk6x{,-gui} "$APPS/opengk6x.desktop" "$ICONS/opengk6x.svg"
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
    echo "removed (your data in ~/.config/opengk6x is kept)"
    exit 0
fi

mkdir -p "$BIN" "$APPS" "$ICONS"
for name in opengk6x opengk6x-gui; do
    module=opengk6x
    [[ $name == opengk6x-gui ]] && module=opengk6x.gui
    printf '#!/bin/sh\nPYTHONPATH=%q exec python3 -m %s "$@"\n' "$REPO" "$module" > "$BIN/$name"
    chmod +x "$BIN/$name"
done
install -m644 "$REPO/opengk6x/gui/opengk6x.svg" "$ICONS/opengk6x.svg"
sed "s|^Exec=opengk6x-gui|Exec=$BIN/opengk6x-gui|" "$REPO/packaging/opengk6x.desktop" > "$APPS/opengk6x.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
echo "installed: $BIN/opengk6x, $BIN/opengk6x-gui, app-menu entry \"OpenGK6X\""
case ":$PATH:" in *":$BIN:"*) ;; *) echo "note: $BIN is not on your PATH" ;; esac
if [[ ! -d $DATA/opengk6x/vendor ]]; then
    echo "next: copy the keyboard data from the official app once:  opengk6x setup-data GK6X_Setup_8.0.7.zip"
fi
