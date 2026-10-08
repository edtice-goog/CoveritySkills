#!/bin/bash
# The fix check ("fixed, or silenced?") end to end on the fixture:
#   A  = use.c                    FORWARD_NULL at the dereference after the guard (a true positive)
#   B1 = fixcheck/use_fixed.c     the null is handled: a fix
#   B2 = fixcheck/use_silenced.c  the dereference moves into rec_id(), a helper
#                                 outside the capture; the analyzer sees no dereference
#   1. toggle: emit + analyze each copy beside the same lookup.c; which copies
#      still carry the finding
#   2. verify A: slice, lookup's model stub, the claim at the line, fuzz; the
#      crashing input c and the stub choice behind it
#   3. verify B1 and B2 with the SAME claim, the SAME stub, and the callee the
#      change introduced (rec_id) as real code; replay c, then fuzz
#   4. the verdict on each change
#
#   usage: run_fixcheck.sh <coverity-install>/bin [workdir]
#
# Needs coverity-function-slice beside this skill and clang-cl (LLVM); the
# fixture is emitted here, so clang-cl is the matching toolchain.
set -euo pipefail
BIN="${1:?usage: run_fixcheck.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
SLICER="$HERE/../../coverity-function-slice/tools/slice_function.py"
[ -f "$SLICER" ] || { echo "coverity-function-slice not found beside this skill ($SLICER)"; exit 1; }
CLANG="${CLANG_CL:-C:/Program Files/LLVM/bin/clang-cl.exe}"
[ -x "$CLANG" ] || { echo "clang-cl not found at $CLANG; set CLANG_CL"; exit 1; }
LLVM_ROOT="$(dirname "$(dirname "$CLANG")")"
command -v cygpath >/dev/null && LLVM_ROOT="$(cygpath -u "$LLVM_ROOT")"
ASAN_DIR="$(dirname "$(find "$LLVM_ROOT/lib/clang" -name 'clang_rt.asan_dynamic-x86_64.dll' | head -1)")"
export PATH="$ASAN_DIR:$LLVM_ROOT/bin:$PATH"

declare -A SRC=([A]="$HERE/use.c" [B1]="$HERE/fixcheck/use_fixed.c" [B2]="$HERE/fixcheck/use_silenced.c")
EVID='fz: CLAIM HOLDS.*\|fz: summary.*'

echo "== 1. toggle: the same lookup.c beside each copy of use.c; default checkers"
for v in A B1 B2; do
  IDIR="$WORK/idir-$v"; rm -rf "$IDIR"
  "$BIN/cov-emit" --dir "$IDIR" --c "$HERE/lookup.c" > /dev/null
  "$BIN/cov-emit" --dir "$IDIR" --c "${SRC[$v]}" > /dev/null
  "$BIN/cov-analyze" --dir "$IDIR" > "$WORK/analyze-$v.log" 2>&1
  "$BIN/cov-format-errors" --dir "$IDIR" --json-output-v10 "$WORK/findings-$v.json" > /dev/null 2>&1
  python3 "$HERE/fixcheck/findings_in.py" "$WORK/findings-$v.json" escaped | sed "s/^/   $v: /"
done

echo "== 2-3. the same claim and the same model stub on every copy; rec_id() is real code"
mkdir -p "$WORK/models"
OUT="$("$BIN/cov-find-function" --dir "$WORK/idir-A" --save -of "$WORK/models" --module generic lookup)"
BASE="$(echo "$OUT" | grep -o 'File name base: .*' | head -1 | sed 's/File name base: //' | tr -d '\r')"
echo "lookup $BASE defs=1" > "$WORK/models/index.txt"
for v in A B1 B2; do
  python3 "$SLICER" --dir "$WORK/idir-$v" --bin "$BIN" --tu 2 --name escaped --out "$WORK/slice-$v" --emit | grep -q "cov-emit: emitted" || echo "   $v: slice did not emit"
  python3 "$TOOLS/fz_target.py" --slice "$WORK/slice-$v/escaped.slice.c" --models "$WORK/models" --harness "$HERE/fixcheck/harness.c" \
      --claim 'r != NULL' --before '^\s*sink\(' --keep sink,unknown,rec_id --out "$WORK/target-$v.c" > "$WORK/assemble-$v.log"
  echo "   $v: claim sites $(grep -c '__fz_claim' "$WORK/target-$v.c")"
  ( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od -I"$TOOLS" "target-$v.c" -Fe:"fuzz-$v.exe" > "build-$v.log" 2>&1 ) || { tail -5 "$WORK/build-$v.log"; exit 1; }
done

set +e
echo "   A: fuzz 20 s"
( cd "$WORK" && ./fuzz-A.exe -max_total_time=20 -seed=1 -artifact_prefix="$WORK/crash-A-" > run-A.log 2>&1 ); echo "      exit $? (77 = the claim failed)"
grep -m1 "CLAIM" "$WORK/run-A.log" | cut -c1-100 | sed 's/^/      /'
grep -m1 "== fz: stub choices" "$WORK/run-A.log" | cut -c1-100 | sed 's/^/      /'
C="$(ls "$WORK"/crash-A-* 2>/dev/null | head -1)"
[ -n "$C" ] || { echo "   no crashing input from A"; exit 1; }
echo "   c = $(od -An -tx1 "$C" | tr -s ' ')"
for v in B1 B2; do
  ( cd "$WORK" && ./fuzz-$v.exe "$C" > "replay-$v.log" 2>&1 ); rc=$?
  echo "   $v: replay c -> exit $rc; $(grep -m1 -o "$EVID" "$WORK/replay-$v.log" | cut -c1-80)"
  ( cd "$WORK" && ./fuzz-$v.exe -max_total_time=20 -seed=1 -artifact_prefix="$WORK/crash-$v-" > "run-$v.log" 2>&1 ); rc=$?
  echo "   $v: fuzz 20 s -> exit $rc; $(grep -m1 -o "$EVID" "$WORK/run-$v.log" | cut -c1-80)"
done
set -e
echo "== 4. verdicts"
echo "   A : confirmed by crash under model stubs (lookup=1, returnsnull; the real lookup has it)"
echo "   B1: the finding is gone, the claim never fails, and B1 differs from A on c (returns instead of crashing): FIXED"
echo "   B2: the finding is gone, but the claim fails on c with the callee the change introduced as real code: SILENCED, NOT FIXED"
