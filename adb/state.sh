#!/usr/bin/env bash
# Ask the engine for one "[Android DebugState]" telemetry line and print it.
# Requires the 0011-android-debug-telemetry patch (debug builds only).
#
# Usage: state.sh [hint]
#   Without hint: pos/yaw/pitch/cell/gui + crosshair focus (faced/fdist).
#   With hint:    adds target/tbearing/tdist for the nearest actor whose
#                 name contains the hint (tbearing is degrees relative to
#                 the current yaw).
#
# The engine answers asynchronously on its own frame; this polls openmw.log
# until a fresh line appears.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PKG="${OMW_PKG:-is.xyz.omw_nightly.debug}"
LOG="${OMW_LOG:-/sdcard/omw_nightly/config/openmw.log}"
A=(adb ${OMW_SERIAL:+-s "$OMW_SERIAL"})

mark=$("${A[@]}" shell "grep -c 'Android DebugState' $LOG 2>/dev/null || true" | tr -d '\r')
# NB: adb drops empty arguments, so only pass the hint extra when non-empty.
hintArgs=()
[ -n "${1:-}" ] && hintArgs=(--es hint "$1")
"${A[@]}" shell am broadcast -p "$PKG" -a is.xyz.omw.debug.STATE "${hintArgs[@]}" >/dev/null

for _ in $(seq 1 25); do
  sleep 0.4
  n=$("${A[@]}" shell "grep -c 'Android DebugState' $LOG 2>/dev/null || true" | tr -d '\r')
  [ "$n" -gt "$mark" ] && break
done

"${A[@]}" shell "grep 'Android DebugState' $LOG | tail -1" | tr -d '\r'
