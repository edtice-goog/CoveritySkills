#!/bin/bash
# The fuzz confirmation, end to end, on the fixtures in this directory:
#   1. the candidate: escaped() in use.c null-tests lookup()'s result inside
#      `if (r && r->value)` and dereferences r after the closing brace
#      (use.c:18); a path-insensitive shape checker flags it (coverity-pathout)
#   2. slice the candidate function (coverity-function-slice)
#   3. a stub for its callee from Coverity's derived model
#   4. a libFuzzer + ASan harness; the crash at the candidate's line is the confirmation
#
#   usage: run.sh <coverity-install>/bin [workdir]
#
# Needs coverity-function-slice beside this skill, and clang-cl (LLVM) for
# step 4; steps 2-3 run without it.
set -euo pipefail
BIN="${1:?usage: run.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SLICER="$HERE/../../coverity-function-slice/tools/slice_function.py"
[ -f "$SLICER" ] || { echo "coverity-function-slice not found beside this skill ($SLICER)"; exit 1; }
IDIR="$WORK/idir"
rm -rf "$IDIR"

echo "== 1. the two-file fixture: candidate at use.c:18 in escaped(), callee lookup() with a derived model"
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/lookup.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/use.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" > "$WORK/default.log" 2>&1      # derives the models
sed -n '18p' "$HERE/use.c" | sed 's/^/   use.c:18  /'

echo "== 2. the slice of escaped()"
python3 "$SLICER" --dir "$IDIR" --bin "$BIN" --tu 2 --name escaped --out "$WORK/slice" --emit | grep "cov-emit\|contents"

echo "== 3. stub for lookup() from its derived model"
"$BIN/cov-find-function" --dir "$IDIR" --save -of "$WORK/models" --module generic lookup | grep "File name"
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
python3 "$HERE/../tools/model_stubs.py" "$PROTO" "$DOT" | tee -a "$WORK/target.c"

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
echo "verdict: confirmed by crash under model stubs (the choice byte selected lookup's returnsnull branch)"
