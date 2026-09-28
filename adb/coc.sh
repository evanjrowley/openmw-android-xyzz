#!/usr/bin/env bash
# coc to a cell and report the resulting telemetry line.
#
# Usage: coc.sh "Cell, Name" [load_seconds=8]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

"$HERE/con.sh" "coc \"$1\""
sleep "${2:-8}"
"$HERE/state.sh"
