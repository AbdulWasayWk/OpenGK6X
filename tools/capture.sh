#!/usr/bin/env bash
# Record GK6X USB traffic on the host (also works while the keyboard is passed through to the Windows VM).
#
#   tools/capture.sh <name> [seconds] [wired|dongle]     -> captures/<name>.pcapng
#
# Runs until Ctrl-C, or for [seconds] if given (0 = until Ctrl-C). Needs read access to /dev/usbmonN:
# run `tools/setup-dev.sh usbmon` once per boot.
set -euo pipefail
cd "$(dirname "$0")/.."

name=${1:?usage: $0 <name> [seconds] [wired|dongle]}
case ${3:-wired} in
    wired)  pid=0907 ;;
    dongle) pid=0067 ;;
    *)      echo "link must be wired or dongle" >&2; exit 2 ;;
esac
out="captures/$name.pcapng"
[[ -e $out ]] && { echo "$out already exists" >&2; exit 1; }

dev=""
for d in /sys/bus/usb/devices/*; do
    [[ -f $d/idVendor && $(<"$d/idVendor") == 1ea7 && $(<"$d/idProduct") == "$pid" ]] && dev=$d
done
[[ -n $dev ]] || { echo "1ea7:$pid not found on USB" >&2; exit 1; }
bus=$(<"$dev/busnum")
[[ -r /dev/usbmon$bus ]] || { echo "/dev/usbmon$bus not readable; run tools/setup-dev.sh usbmon" >&2; exit 1; }

args=(-q -i "usbmon$bus" -w "$out")
[[ ${2:-0} != 0 ]] && args+=(-a "duration:$2")
echo "==> Capturing bus $bus (1ea7:$pid is device $(<"$dev/devnum")) to $out. Ctrl-C to stop."
dumpcap "${args[@]}"
