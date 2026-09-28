#!/usr/bin/env bash
# Inject controller input into the running OpenMW debug build via the
# DebugInputReceiver broadcast surface (debug builds only).
#
# Usage: joy.sh <cmd> [args...]
#   axis <id> <value>              single axis event (id: 0/1=left, 2/3=right, 4/5=triggers)
#   pulse <id> <value> <ms>        hold axis for ms; the on-device release
#                                  carries no ADB latency jitter
#   stick <0|1> <x> <y>            both axes of one stick
#   down <keycode> / up <keycode>  Android keycode (A=96 B=97 X=99 Y=100,
#                                  L1=102 R1=103, L3=106 R3=107, dpad=19-22,
#                                  start=108 select=109)
#   tap <keycode> [ms]             down + up
#   info                           receiver device listing (from logcat)
#
# Env: OMW_SERIAL (adb -s target), OMW_PKG (default is.xyz.omw_nightly.debug).
set -euo pipefail
PKG="${OMW_PKG:-is.xyz.omw_nightly.debug}"
A=(adb ${OMW_SERIAL:+-s "$OMW_SERIAL"})

b() { "${A[@]}" shell am broadcast -p "$PKG" "$@" >/dev/null; }

case "${1:-}" in
  axis)  b -a is.xyz.omw.debug.JOY_AXIS  --ei axis "$2" --ef value "$3" ;;
  pulse) b -a is.xyz.omw.debug.JOY_PULSE --ei axis "$2" --ef value "$3" --ei duration_ms "$4" ;;
  stick) b -a is.xyz.omw.debug.JOY_STICK --ei stick "$2" --ef x "$3" --ef y "$4" ;;
  down)  b -a is.xyz.omw.debug.PAD_BUTTON --ei keycode "$2" --ez down true ;;
  up)    b -a is.xyz.omw.debug.PAD_BUTTON --ei keycode "$2" --ez down false ;;
  tap)   "$0" down "$2"; sleep "${3:-0.15}"; "$0" up "$2" ;;
  info)  b -a is.xyz.omw.debug.INFO; sleep 0.6
         "${A[@]}" logcat -d -s OmwDebugInput:V | tail -8 ;;
  *)     echo "usage: $0 axis|pulse|stick|down|up|tap|info ..." >&2; exit 2 ;;
esac
