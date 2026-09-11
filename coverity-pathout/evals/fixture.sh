#!/bin/bash
# Build and analyze the PATHOUT fixtures, then print the lines the skill
# teaches you to read. Verifies, on the installation you point it at, that:
#   - ifs_from_zero trips the default limit and ifs_from_param does not
#   - demo::Widget::f(int) trips it and is logged under its mangled name
#   - --print-paths adds "Pathed out: N paths traversed by <CHECKER>" lines
#   - find --print-definitions returns the function from the AST
#   - a slice of a C function with for(;;) and function-local unnamed types
#     emits and analyzes (local_enum_forever.c: the two forms that dropped
#     eight nginx functions from their slices)
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
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/fixtures/local_enum_forever.c" | tail -1
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
head -30 "$WORK/slice/fn_0.obf.c"

echo "== C: for(;;) and function-local unnamed enum/struct (the pretty-printer writes 'for (; true; )' and"
echo "==    'enum fn::[unnamed type of ...]'; without the rewrites cov-emit drops the function and no wur: line appears)"
python3 "$HERE/../tools/slice_function.py" --dir "$IDIR" --bin "$BIN" --tu 3 --name local_enum_forever --out "$WORK/slice-local" --obfuscate --emit --analyze
echo "== the rewritten forms in the slice"
grep -n '^#define true\|^enum __cov_anon\|^struct __cov_anon\|for (; true; )\|^  enum __cov_anon\|^  struct __cov_anon' "$WORK/slice-local/local_enum_forever.slice.c"

echo "== C++: a free function calling a static member, nested enum, flexible array member, __func__"
CXXDIR="$WORK/idir-pathout-cxx"
rm -rf "$CXXDIR"
"$BIN/cov-emit" --dir "$CXXDIR" --c++ "$HERE/fixtures/nested_members.cpp" | tail -1
"$BIN/cov-analyze" --dir "$CXXDIR" > "$WORK/analyze-cxx.stdout" 2>&1 || { tail -20 "$WORK/analyze-cxx.stdout"; exit 1; }
grep -E '^wur: .*PATHOUT=1 n: _Z5drivei in TU' "$CXXDIR/output/analysis-log.txt" | sed 's/ mem=[0-9]* max=[0-9]*//'
python3 "$HERE/../tools/slice_function.py" --dir "$CXXDIR" --bin "$BIN" --tu 1 --name _Z5drivei --out "$WORK/slice-cxx" --obfuscate --emit --analyze
echo "== the class body as the slicer reconstructed it"
sed -n '/^class /,/^};/p' "$WORK/slice-cxx/_Z5drivei.slice.cpp"
