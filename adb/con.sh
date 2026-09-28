#!/usr/bin/env bash
# Run ONE OpenMW console command over ADB: opens the console, clears the
# leaked backtick, types the command (spaces via %s, apostrophes via
# keyevent 75), presses Enter, and closes the console again. Only valid
# from game view (the console cannot be toggled over a menu dialog).
#
# Usage: con.sh 'coc "Balmora, Caius Cosades'"'"' House"'
set -euo pipefail
A=(adb ${OMW_SERIAL:+-s "$OMW_SERIAL"})

"${A[@]}" shell input keyevent 68   # open console
sleep 1.2
for _ in 1 2 3 4; do "${A[@]}" shell input keyevent 67; done  # clear leak
sleep 0.3

txt="$1"
IFS="'" read -ra parts <<< "$txt"
for idx in "${!parts[@]}"; do
  [ "$idx" -gt 0 ] && "${A[@]}" shell input keyevent 75   # apostrophe
  seg="${parts[$idx]}"
  [ -n "$seg" ] && "${A[@]}" shell "input text '${seg// /%s}'"
done
sleep 0.4

"${A[@]}" shell input keyevent 66   # Enter
sleep 1.5
"${A[@]}" shell input keyevent 68   # close console
sleep 0.8
