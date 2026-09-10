#!/bin/bash
# The escape hunt, end to end, on the fixtures in this directory:
#   1. the path-insensitive shape checker over an idir (candidates only)
#   2. slice the candidate function
#   3. a stub for its callee from Coverity's derived model
#   4. a libFuzzer + ASan harness; the crash at the candidate's line is the confirmation
#
#   usage: run.sh <coverity-install>/bin [workdir]
#
# Needs clang-cl (LLVM) for step 4; steps 1-3 run without it. The PATHOUT
# filter (tools/pathout_filter.py) is not exercised here -- these fixtures
# are small enough that nothing paths out; it was run on a 9,533-function
# idir instead (CALIBRATION.md).
set -euo pipefail
BIN="${1:?usage: run.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../../tools"
IDIR="$WORK/idir"
rm -rf "$IDIR"

echo "== 1. shape checker on shape.c: expect lines 20 and 59, not 30/40/49"
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/shape.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" --disable-default --codexm "$HERE/null_check_then_deref.cxm" > "$WORK/cxm1.log" 2>&1
"$BIN/cov-format-errors" --dir "$IDIR" --emacs-style 2>/dev/null | grep -B1 "Candidate" | grep -o "shape.c:[0-9]*" | sort -u

echo "== 2. the two-file fixture: candidate in escaped(), callee with a derived model"
IDIR2="$WORK/idir2"; rm -rf "$IDIR2"
"$BIN/cov-emit" --dir "$IDIR2" --c "$HERE/lookup.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR2" --c "$HERE/use.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR2" --disable-default --codexm "$HERE/null_check_then_deref.cxm" > "$WORK/cxm2.log" 2>&1
"$BIN/cov-format-errors" --dir "$IDIR2" --emacs-style 2>/dev/null | grep -B1 "Candidate" | grep -o "use.c:[0-9]*" | sort -u
"$BIN/cov-analyze" --dir "$IDIR2" > "$WORK/default2.log" 2>&1      # derives the models
python3 "$TOOLS/slice_function.py" --dir "$IDIR2" --bin "$BIN" --tu 2 --name escaped --out "$WORK/slice" --emit | grep "cov-emit\|contents"

echo "== 3. stub for lookup() from its derived model"
"$BIN/cov-find-function" --dir "$IDIR2" --save -of "$WORK/models" --module generic lookup | grep "File name"
DOT="$(ls "$WORK"/models/*.generic.dot | head -1)"
PROTO="$(grep -m1 'lookup(' "$WORK/slice/escaped.slice.c")"
cp "$WORK/slice/escaped.slice.c" "$WORK/target.c"
cat >> "$WORK/target.c" <<'EOF'

/* ---- fuzz-driven stub support (definitions in harness.c) */
extern int __stub_nondet(void);
extern void *__stub_alloc(int n);
extern void *__stub_object(int n);
static int __stub_choice(int n) { int c = __stub_nondet(); return n > 0 ? (c % n + n) % n : c; }
EOF
python3 "$TOOLS/model_stubs.py" "$PROTO" "$DOT" | tee -a "$WORK/target.c"

echo "== 4. build and fuzz (clang-cl + libFuzzer + ASan)"
CLANG="${CLANG_CL:-C:/Program Files/LLVM/bin/clang-cl.exe}"
if [ ! -x "$CLANG" ]; then echo "clang-cl not found at $CLANG; set CLANG_CL. Steps 1-3 passed."; exit 0; fi
# the ASan runtime DLL must be on PATH, in a form this shell searches
LLVM_ROOT="$(dirname "$(dirname "$CLANG")")"
command -v cygpath >/dev/null && LLVM_ROOT="$(cygpath -u "$LLVM_ROOT")"
ASAN_DIR="$(dirname "$(find "$LLVM_ROOT/lib/clang" -name 'clang_rt.asan_dynamic-x86_64.dll' | head -1)")"
export PATH="$ASAN_DIR:$LLVM_ROOT/bin:$PATH"
( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od target.c "$HERE/harness.c" -Fe:fuzz.exe > build.log 2>&1 ) || { tail -5 "$WORK/build.log"; exit 1; }
set +e
( cd "$WORK" && ./fuzz.exe -max_total_time=30 -seed=1 > run.log 2>&1 )
echo "fuzzer exit: $?  (1 = crash found; 127 = ASan DLL not on PATH)"
set -e
grep -m1 "ERROR: AddressSanitizer" "$WORK/run.log" | cut -c1-120
grep -m1 "#0 .* in escaped" "$WORK/run.log" | grep -o "target.c:[0-9]*" | while read loc; do n="${loc#*:}"; echo "crash at $loc: $(sed -n "${n}p" "$WORK/target.c" | sed 's/^ *//')"; done
grep -m1 "Test unit written" "$WORK/run.log" | cut -c1-100
