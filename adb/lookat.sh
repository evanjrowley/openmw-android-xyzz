#!/usr/bin/env bash
# Closed-loop aim at the nearest actor matching NAME, using engine
# telemetry instead of screenshots. Optionally walk into activation
# range and activate.
#
# Usage: lookat.sh NAME [--walk] [--activate]
#   --walk      approach until tdist <= ~2.0 (learned move calibration)
#   --activate  press Activate (left trigger) once the crosshair tooltip
#               (faced=...) confirms the aim, retrying on miss
#
# Loop: state.sh gives yaw and tbearing (bearing to the target, degrees,
# relative to current yaw). Each iteration pulses the right stick for a
# computed duration; the first pulse is also a calibration probe that
# learns the sign and deg/ms rate of injected look input, so engine or
# sensitivity changes self-correct. After every pulse the script waits
# for the camera to settle (consecutive yaw readings agree) and forces
# an explicit axis release, since a lost pulse-release would otherwise
# keep rotating the view.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

name=""
walk=0
activate=0
for a in "$@"; do
  case "$a" in
    --walk) walk=1 ;;
    --activate) activate=1 ;;
    *) name="$a" ;;
  esac
done
[ -n "$name" ] || { echo "usage: $0 NAME [--walk] [--activate]" >&2; exit 2; }

get_state() {
  # Retry once: a flaky adb shell read must not kill the whole loop under
  # `set -e`; empty results are handled by the field guards.
  local s
  s=$("$HERE/state.sh" "$name" 2>/dev/null | sed 's/.*\[Android DebugState\] //' || true)
  if [ -z "$s" ]; then
    sleep 1
    s=$("$HERE/state.sh" "$name" 2>/dev/null | sed 's/.*\[Android DebugState\] //' || true)
  fi
  printf '%s' "$s"
}
field_num() { printf '%s' "$1" | { grep -o "$2=[-0-9.]*" | head -1 | cut -d= -f2 || true; } }
field_str() { printf '%s' "$1" | { grep -o "$2='[^']*'" | sed "s/^$2='//;s/'\$//" || true; } }

# Wait until the camera stops moving; echoes the settled yaw.
settled_yaw() {
  local prev cur i
  prev=$(field_num "$(get_state)" yaw)
  for i in 1 2 3 4 5 6; do
    sleep 0.6
    cur=$(field_num "$(get_state)" yaw)
    if [ "$(awk -v a="$cur" -v b="$prev" 'BEGIN{print (a-b<0?-a+b:a-b)<0.3?1:0}')" = 1 ]; then
      echo "$cur"
      return
    fi
    prev="$cur"
  done
  echo "$cur"
}

st=$(get_state)
echo "aim: $st"

sign=0       # +1 if positive RIGHTX increases yaw, -1 otherwise
rate=0.02    # |deg| per ms at |axis| 0.6

turn_to() {  # $1 = desired bearing change (deg, signed)
  local ms dir
  ms=$(awk -v b="$1" -v r="$rate" 'BEGIN {
    ms = (b < 0 ? -b : b) / r; if (ms < 80) ms = 80; if (ms > 2500) ms = 2500;
    printf "%d", ms }')
  dir=$(awk -v b="$1" -v s="$sign" 'BEGIN { print (b * s) >= 0 ? "0.6" : "-0.6" }')
  "$HERE/joy.sh" pulse 2 "$dir" "$ms"
  "$HERE/joy.sh" axis 2 0
  settled_yaw >/dev/null
}

# --- learn look-input sign + rate from a calibration pulse ---------------
yaw0=$(field_num "$st" yaw)
"$HERE/joy.sh" pulse 2 0.6 250
"$HERE/joy.sh" axis 2 0
yaw1=$(settled_yaw)
dyaw=$(awk -v a="$yaw1" -v b="$yaw0" 'BEGIN { print a - b }')
sign=$(awk -v d="$dyaw" 'BEGIN { print d >= 0 ? 1 : -1 }')
rate=$(awk -v d="$dyaw" 'BEGIN { r = (d < 0 ? -d : d) / 250; if (r < 0.004) r = 0.004; print r }')
st=$(get_state)
echo "calibration: sign=$sign rate=${rate}deg/ms"

# --- turn until the crosshair is on the target ---------------------------
for _ in 1 2 3 4 5 6 7 8; do
  bearing=$(field_num "$st" tbearing)
  faced=$(field_str "$st" faced)
  [ -n "$bearing" ] || { echo "no target matching '$name' in range"; exit 1; }
  if [ "$(awk -v b="$bearing" 'BEGIN{print (b<0?-b:b)<=2?1:0}')" = 1 ]; then
    break
  fi
  turn_to "$bearing"
  st=$(get_state)
done

# --- optionally walk into activation range -------------------------------
if [ "$walk" = 1 ]; then
  for _ in 1 2 3 4 5; do
    dist=$(field_num "$st" tdist)
    [ -n "$dist" ] || break
    [ "$(awk -v d="$dist" 'BEGIN { print d > 2.0 ? 1 : 0 }')" = 1 ] || break
    "$HERE/joy.sh" pulse 1 -0.7 250
    "$HERE/joy.sh" axis 1 0
    sleep 0.6
    st=$(get_state)
    moved=$(awk -v a="$dist" -v b="$(field_num "$st" tdist)" 'BEGIN { print a - b }')
    left=$(awk -v d="$(field_num "$st" tdist)" -v m="$moved" 'BEGIN {
      d = d - 1.9; if (d < 0) d = 0; ms = m > 0.5 ? d / m * 250 : 400;
      if (ms < 100) ms = 100; if (ms > 2500) ms = 2500; printf "%d", ms }')
    [ "$(awk -v d="$(field_num "$st" tdist)" 'BEGIN{print d>2.0?1:0}')" = 1 ] || break
    "$HERE/joy.sh" pulse 1 -0.7 "$left"
    "$HERE/joy.sh" axis 1 0
    sleep 0.6
    st=$(get_state)
  done
fi

echo "aim: $st"

# --- optionally activate (with re-aim retries) ----------------------------
if [ "$activate" = 1 ]; then
  for _ in 1 2 3; do
    "$HERE/joy.sh" pulse 4 1.0 350
    sleep 1.5
    st=$(get_state)
    gui=$(field_num "$st" gui)
    if [ -n "$gui" ] && [ "$gui" != "-1" ]; then
      echo "ACTIVATED: target='$name' (gui mode $gui)"
      echo "aim: $st"
      exit 0
    fi
    # miss: re-aim from the current residual bearing and try again
    for _ in 1 2 3 4; do
      bearing=$(field_num "$st" tbearing)
      [ -n "$bearing" ] || break
      [ "$(awk -v b="$bearing" 'BEGIN{print (b<0?-b:b)<=1.5?1:0}')" = 1 ] && break
      turn_to "$bearing"
      st=$(get_state)
    done
  done
  echo "activate failed after retries"
  echo "aim: $st"
  exit 1
fi
