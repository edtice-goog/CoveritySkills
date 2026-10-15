#!/bin/bash
# Compile the fixtures, run every checker alone, and print the lines each
# one reports. Compare against the HIT markers in fixtures/*.c.
#   usage: bin/run_fixtures.sh <coverity-install>/bin [workdir]
set -euo pipefail
BIN="${1:?usage: run_fixtures.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
IDIR="$WORK/idir-fixtures"
rm -rf "$IDIR"
for f in "$HERE"/fixtures/*.c; do "$BIN/cov-emit" --dir "$IDIR" --c "$f" | tail -1; done
for cxm in "$HERE"/checkers/*.cxm; do
  name="$(basename "$cxm" .cxm)"
  echo "== $name"
  # HIT markers between the "---- <name> ----" banner and the next banner
  echo "   expected: $(awk -v s="---- $name ----" 'FNR==1 {p=0} index($0, s) {p=1; next} /^\/\* ----/ {p=0} p && /HIT/ {printf "%d ", FNR}' "$HERE"/fixtures/*.c)"
  if ! "$BIN/cov-analyze" --dir "$IDIR" --disable-default --codexm "$cxm" > "$WORK/$name.log" 2>&1; then
    grep -A4 "Failed to parse\|ERROR" "$WORK/$name.log" | head -8
    continue
  fi
  echo "   reported: $("$BIN/cov-format-errors" --dir "$IDIR" --emacs-style 2>/dev/null | grep -B1 'Candidate' | grep -o '[a-z_]*\.c:[0-9]*' | cut -d: -f2 | sort -n | uniq | tr '\n' ' ')"
done
