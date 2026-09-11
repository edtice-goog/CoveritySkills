#!/bin/bash
# Build and analyze the PATHOUT fixture, then print the lines the skill
# teaches you to read. Verifies, on the installation you point it at, that:
#   - ifs_from_zero trips the default limit and ifs_from_param does not
#   - --print-paths adds "Pathed out: N paths traversed by <CHECKER>" lines
#   - the report tool joins the log and the metrics
#   - the path-insensitive shape checker reports the shape and none of its
#     three nearest non-shapes
#
#   usage: fixture.sh <install>/bin [workdir]
set -euo pipefail
BIN="${1:?usage: fixture.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IDIR="$WORK/idir-pathout-fixture"
rm -rf "$IDIR"

"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/fixtures/ifs_known_vs_unknown.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" --print-paths > "$WORK/analyze.stdout" 2>&1 || { tail -20 "$WORK/analyze.stdout"; exit 1; }

LOG="$IDIR/output/analysis-log.txt"
echo "== wur lines for the fixture functions (PATHOUT=1 marks the one that hit the limit)"
grep -E '^wur: .*n: (ifs_from_zero|ifs_from_param) in TU' "$LOG" | sed 's/ mem=[0-9]* max=[0-9]*//'
echo "== which checker hit it (only present with --print-paths)"
grep 'Pathed out' "$LOG" | sort | uniq -c | sort -rn | head -12
echo "== summary lines"
grep -E '^summary: (Exceeded path limit|paths_exceeded)' "$LOG"
echo "== nothing about it on the console:"
grep -c -i 'path limit\|PATHOUT' "$WORK/analyze.stdout" || true
echo "== the report tool"
python3 "$HERE/../tools/pathout_report.py" --dir "$IDIR" --bin "$BIN" --out "$WORK/pathout"

echo "== the shape checker on shape.c: expect lines 20 and 59, not 30/40/49"
SDIR="$WORK/idir-shape"
rm -rf "$SDIR"
"$BIN/cov-emit" --dir "$SDIR" --c "$HERE/escape-hunt/shape.c" | tail -1
"$BIN/cov-analyze" --dir "$SDIR" --disable-default --codexm "$HERE/escape-hunt/null_check_then_deref.cxm" > "$WORK/cxm.log" 2>&1 || { grep -A4 'Failed to parse\|ERROR' "$WORK/cxm.log" | head -8; exit 1; }
"$BIN/cov-format-errors" --dir "$SDIR" --emacs-style 2>/dev/null | grep -B1 "Candidate" | grep -o "shape.c:[0-9]*" | sort -u
echo "== the filter on those hits, against this fixture's own --print-paths log (nothing paths out in shape.c, so 0 kept)"
"$BIN/cov-format-errors" --dir "$SDIR" --json-output-v10 "$WORK/candidates.json" > /dev/null 2>&1
python3 "$HERE/../tools/pathout_filter.py" --findings "$WORK/candidates.json" --log "$LOG" --relevant auto | head -3
