#!/bin/bash
# The slice set, end to end on the fixture in evals/sliceset/:
#   get_value() dereferences pick()'s result without a test; pick() returns
#   NULL for a negative id, and get_value() never passes one. Both carry a
#   primary event of the finding, so both are the slice set.
#   1. emit, analyze, save pick's model (on purpose: it must be ignored)
#   2. slice the SET (--name get_value --name pick): line 1 names it
#   3. assemble: pick is code, its model is ignored and the log says so; fuzz:
#      the claim `r != NULL` never fails -> refuted by execution
#   4. the control: a single-name slice of get_value with pick as a model
#      stub; the claim fails on the first input through `pick=0`
#      (returnsnull) -> the stub adjudicates a false positive as real, which is
#      why a function on the finding's own path is never a stub
#
#   usage: run_sliceset.sh <coverity-install>/bin [workdir]
#   SLICER=<path to slice_function.py> overrides the default beside this skill.
set -euo pipefail
BIN="${1:?usage: run_sliceset.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
SLICER="${SLICER:-$HERE/../../coverity-function-slice/tools/slice_function.py}"
[ -f "$SLICER" ] || { echo "slice_function.py not found ($SLICER); set SLICER"; exit 1; }
CLANG="${CLANG_CL:-C:/Program Files/LLVM/bin/clang-cl.exe}"
[ -x "$CLANG" ] || { echo "clang-cl not found at $CLANG; set CLANG_CL"; exit 1; }
LLVM_ROOT="$(dirname "$(dirname "$CLANG")")"
command -v cygpath >/dev/null && LLVM_ROOT="$(cygpath -u "$LLVM_ROOT")"
ASAN_DIR="$(dirname "$(find "$LLVM_ROOT/lib/clang" -name 'clang_rt.asan_dynamic-x86_64.dll' | head -1)")"
export PATH="$ASAN_DIR:$LLVM_ROOT/bin:$PATH"
IDIR="$WORK/idir"; rm -rf "$IDIR" "$WORK/models" "$WORK/set" "$WORK/one"

echo "== 1. the fixture, analyzed; pick's derived model saved (it must be ignored for the set)"
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/sliceset/pair.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" > "$WORK/analyze.log" 2>&1
mkdir -p "$WORK/models"
OUT="$("$BIN/cov-find-function" --dir "$IDIR" --save -of "$WORK/models" --module generic pick)"
BASE="$(echo "$OUT" | grep -o 'File name base: .*' | head -1 | sed 's/File name base: //' | tr -d '\r')"
echo "pick $BASE defs=1" > "$WORK/models/index.txt"
echo "   pick's model edges: $(grep -o 'label="[^"]*"' "$WORK/models/$BASE.dot" | grep -v '^label="pick"' | sed 's/label=//' | tr '\n' ' ')"

echo "== 2. the slice set"
python3 "$SLICER" --dir "$IDIR" --bin "$BIN" --tu 1 --name get_value --name pick --out "$WORK/set" --emit | grep "set     :\|members\|cov-emit"
SET="$WORK/set/get_value.set.slice.c"
echo "   line 1: $(head -1 "$SET")"

echo "== 3. assemble and fuzz the set: pick is code"
python3 "$TOOLS/fz_target.py" --slice "$SET" --models "$WORK/models" --harness "$HERE/sliceset/harness.c" \
    --claim 'r != NULL' --before 'return r->value;' --keep sink --out "$WORK/target-set.c"
( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od -I"$TOOLS" target-set.c -Fe:fuzz-set.exe > build-set.log 2>&1 ) || { tail -5 "$WORK/build-set.log"; exit 1; }
set +e
( cd "$WORK" && ./fuzz-set.exe -max_total_time=20 -seed=1 > run-set.log 2>&1 ); rc=$?
set -e
echo "   exit $rc; $(grep -m1 -o 'fz: CLAIM HOLDS.*\|fz: summary.*' "$WORK/run-set.log" | cut -c1-90)"
[ "$rc" = 0 ] || { echo "   FAIL: the claim failed with pick as code"; exit 1; }

echo "== 4. the control: get_value alone, pick as a model stub"
python3 "$SLICER" --dir "$IDIR" --bin "$BIN" --tu 1 --name get_value --out "$WORK/one" --emit | grep "cov-emit"
python3 "$TOOLS/fz_target.py" --slice "$WORK/one/get_value.slice.c" --models "$WORK/models" --harness "$HERE/sliceset/harness.c" \
    --claim 'r != NULL' --before 'return r->value;' --keep sink --out "$WORK/target-one.c" | grep "pick\|slice set"
( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od -I"$TOOLS" target-one.c -Fe:fuzz-one.exe > build-one.log 2>&1 ) || { tail -5 "$WORK/build-one.log"; exit 1; }
set +e
( cd "$WORK" && ./fuzz-one.exe -max_total_time=20 -seed=1 > run-one.log 2>&1 ); rc=$?
set -e
echo "   exit $rc; $(grep -m1 -o 'fz: CLAIM HOLDS.*' "$WORK/run-one.log" | cut -c1-70); $(grep -m1 -o 'stub choices on this input:.*' "$WORK/run-one.log")"
[ "$rc" = 77 ] || { echo "   unexpected: the stubbed control did not fail the claim"; exit 1; }
echo "== verdicts"
echo "   set    : refuted by execution -- pick as code never returns NULL for what get_value passes"
echo "   control: 'confirmed' through pick=0 (returnsnull), a behaviour the real pick cannot show here: the stub adjudicated a false positive as real"
