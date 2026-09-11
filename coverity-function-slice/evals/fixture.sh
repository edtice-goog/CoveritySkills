#!/bin/bash
# Emit the fixtures, extract by mangled name, slice, obfuscate and verify.
# Checks, on the installation you point it at, that:
#   - find --print-definitions returns a function from the AST, and picks a
#     C++ overload by its mangled name
#   - a slice of a C function with for(;;) and function-local unnamed types
#     emits and analyzes (local_enum_forever.c: the two forms that dropped
#     eight nginx functions from their slices), and its obfuscated twin
#     verifies identical
#   - a C++ free function calling a static member of a class with a nested
#     enum slices, with the declarations placed back inside the class
#
#   usage: fixture.sh <install>/bin [workdir]     (keep workdir SHORT: cov-emit
#          fails to create its lock file under a long output path)
set -euo pipefail
BIN="${1:?usage: fixture.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IDIR="$WORK/idir-slice-fixture"
rm -rf "$IDIR"

"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/fixtures/local_enum_forever.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c++ "$HERE/fixtures/overloads.cpp" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" --print-paths > "$WORK/analyze.stdout" 2>&1 || { tail -20 "$WORK/analyze.stdout"; exit 1; }

echo "== the log names C functions plainly and C++ functions by mangled name"
grep -E '^wur: .*n: (local_enum_forever|_ZN4demo6Widget1fE[id]) in TU' "$IDIR/output/analysis-log.txt" | sed 's/ mem=[0-9]* max=[0-9]*//'
echo "== the overloads, listed with their mangled names"
"$BIN/cov-manage-emit" --dir "$IDIR" --ticker-mode none find 'Widget' --kind f | grep -o 'demo::Widget::f([a-z]*) */\*[^*]*\*/' || true
echo "== one overload, from the AST, by mangled name"
"$BIN/cov-manage-emit" --dir "$IDIR" --ticker-mode none find '_ZN4demo6Widget1fEi$' --kind f --print-definitions | head -12

echo "== C: for(;;) and function-local unnamed enum/struct (the pretty-printer writes 'for (; true; )' and"
echo "==    'enum fn::[unnamed type of ...]'; without the rewrites cov-emit drops the function and no wur: line appears)"
python3 "$HERE/../tools/slice_function.py" --dir "$IDIR" --bin "$BIN" --tu 1 --name local_enum_forever --out "$WORK/slice-local" --obfuscate --emit --analyze
echo "== the rewritten forms in the slice"
grep -n '^#define true\|^enum __cov_anon\|^struct __cov_anon\|for (; true; )\|^  enum __cov_anon\|^  struct __cov_anon' "$WORK/slice-local/local_enum_forever.slice.c"
echo "== the obfuscated twin (the 'verify' line above says whether the analysis matched)"
head -30 "$WORK/slice-local/fn_0.obf.c"

echo "== C++: a free function calling a static member, nested enum, flexible array member, __func__"
CXXDIR="$WORK/idir-slice-cxx"
rm -rf "$CXXDIR"
"$BIN/cov-emit" --dir "$CXXDIR" --c++ "$HERE/fixtures/nested_members.cpp" | tail -1
"$BIN/cov-analyze" --dir "$CXXDIR" > "$WORK/analyze-cxx.stdout" 2>&1 || { tail -20 "$WORK/analyze-cxx.stdout"; exit 1; }
grep -E '^wur: .*n: _Z5drivei in TU' "$CXXDIR/output/analysis-log.txt" | sed 's/ mem=[0-9]* max=[0-9]*//'
python3 "$HERE/../tools/slice_function.py" --dir "$CXXDIR" --bin "$BIN" --tu 1 --name _Z5drivei --out "$WORK/slice-cxx" --obfuscate --emit --analyze
echo "== the class body as the slicer reconstructed it"
sed -n '/^class /,/^};/p' "$WORK/slice-cxx/_Z5drivei.slice.cpp"
