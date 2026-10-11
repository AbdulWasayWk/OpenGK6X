#!/usr/bin/env bash
# Dev-environment setup for OpenGK6X. Run as your normal user; it calls sudo.
#
#   tools/setup-dev.sh udev      install packaging/70-opengk6x.rules (access to the 2.4 GHz dongle's config interface)
#   tools/setup-dev.sh usbmon    load usbmon and let you capture the keyboard's USB bus (until reboot)
#
# The usbmon access is temporary (gone after a reboot or module reload): re-run `usbmon` before each capture session.
set -euo pipefail
cd "$(dirname "$0")/.."

VID=1ea7
PIDS=(0907 0067)   # wired, 2.4 GHz dongle

install_udev() {
    echo "==> Installing /etc/udev/rules.d/70-opengk6x.rules"
    sudo install -m 644 packaging/70-opengk6x.rules /etc/udev/rules.d/70-opengk6x.rules
    sudo udevadm control --reload
    sudo udevadm trigger --subsystem-match=hidraw
}

usbmon_access() {
    local d bus buses=()
    for d in /sys/bus/usb/devices/*; do
        [[ -f $d/idVendor && $(<"$d/idVendor") == "$VID" ]] || continue
        [[ " ${PIDS[*]} " == *" $(<"$d/idProduct") "* ]] && buses+=("$(<"$d/busnum")")
    done
    (( ${#buses[@]} )) || { echo "No GK6X keyboard/dongle ($VID:${PIDS[*]}) on USB" >&2; exit 1; }
    sudo modprobe usbmon
    for bus in $(printf '%s\n' "${buses[@]}" | sort -u); do
        echo "==> Granting $USER read access to /dev/usbmon$bus (until reboot)"
        sudo setfacl -m "u:$USER:r" "/dev/usbmon$bus"
    done
}

case "${1:-}" in
    udev)   install_udev ;;
    usbmon) usbmon_access ;;
    *)      echo "usage: $0 udev|usbmon" >&2; exit 2 ;;
esac
echo "==> Done"
