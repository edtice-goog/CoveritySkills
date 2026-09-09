#!/bin/bash
# Build and analyze the PATHOUT fixtures, then print the lines the skill
# teaches you to read. Verifies, on the installation you point it at, that:
#   - ifs_from_zero trips the default limit and ifs_from_param does not
#   - demo::Widget::f(int) trips it and is logged under its mangled name
#   - --print-paths adds "Pathed out: N paths traversed by <CHECKER>" lines
#   - find --print-definitions returns the function from the AST
#
#   usage: fixture.sh <install>/bin [workdir]
set -euo pipefail
BIN="${1:?usage: fixture.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IDIR="$WORK/idir-pathout-fixture"
rm -rf "$IDIR"

"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/fixtures/ifs_known_vs_unknown.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c++ "$HERE/fixtures/overloads.cpp" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" --print-paths > "$WORK/analyze.stdout" 2>&1 || { tail -20 "$WORK/analyze.stdout"; exit 1; }

LOG="$IDIR/output/analysis-log.txt"
echo "== wur lines for the fixture functions (PATHOUT=1 marks the ones that hit the limit)"
grep -E '^wur: .*n: (ifs_from_zero|ifs_from_param|_ZN4demo6Widget1fE[id]) in TU' "$LOG" | sed 's/ mem=[0-9]* max=[0-9]*//'
echo "== which checker hit it (only present with --print-paths)"
grep 'Pathed out' "$LOG" | sort | uniq -c | sort -rn | head -12
echo "== summary lines"
grep -E '^summary: (Exceeded path limit|paths_exceeded)' "$LOG"
echo "== nothing about it on the console:"
grep -c -i 'path limit\|PATHOUT' "$WORK/analyze.stdout" || true
echo "== the function, from the AST, by mangled name"
"$BIN/cov-manage-emit" --dir "$IDIR" --ticker-mode none find '_ZN4demo6Widget1fEi$' --kind f --print-definitions | head -12
echo "== the report tool"
python3 "$HERE/../tools/pathout_report.py" --dir "$IDIR" --bin "$BIN" --out "$WORK/pathout"
echo "== the slice: ifs_from_zero as a standalone file, re-emitted and re-analyzed"
python3 "$HERE/../tools/slice_function.py" --dir "$IDIR" --bin "$BIN" --tu 1 --name ifs_from_zero --out "$WORK/slice" --obfuscate --emit --analyze
echo "== the obfuscated twin (the 'verify' line above says whether the analysis matched)"
head -30 "$WORK/slice/ifs_from_zero.obf.c"
