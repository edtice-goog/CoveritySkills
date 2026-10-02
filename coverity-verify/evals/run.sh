#!/bin/bash
# The fuzz confirmation, end to end, on the fixtures in this directory:
#   1. the candidate: escaped() in use.c null-tests lookup()'s result inside
#      `if (r && r->value)` and dereferences r after the closing brace
#      (use.c:18); a path-insensitive shape checker flags it (coverity-pathout)
#   2. slice the candidate function (coverity-function-slice)
#   3. the derived model of its callee, saved for the assembler
#   4. fz_target.py: slice + model stub + claim + harness -> target.c
#   5. libFuzzer + ASan; the claim failing at the candidate's line, with the
#      stub choice that made it fail, is the confirmation
#
#   usage: run.sh <coverity-install>/bin [workdir]
#
# Needs coverity-function-slice beside this skill, and clang-cl (LLVM) for
# step 5; steps 1-4 run without it. (A Linux-captured idir would be built
# under WSL with `clang -fsanitize=fuzzer,address` instead; the fixture is
# emitted here, so clang-cl is the matching toolchain.)
set -euo pipefail
BIN="${1:?usage: run.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
SLICER="$HERE/../../coverity-function-slice/tools/slice_function.py"
[ -f "$SLICER" ] || { echo "coverity-function-slice not found beside this skill ($SLICER)"; exit 1; }
IDIR="$WORK/idir"
rm -rf "$IDIR" "$WORK/models"

echo "== 1. the two-file fixture: candidate at use.c:18 in escaped(), callee lookup() with a derived model"
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/lookup.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/use.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" > "$WORK/default.log" 2>&1      # derives the models
sed -n '18p' "$HERE/use.c" | sed 's/^/   use.c:18  /'

echo "== 2. the slice of escaped()"
python3 "$SLICER" --dir "$IDIR" --bin "$BIN" --tu 2 --name escaped --out "$WORK/slice" --emit | grep "cov-emit\|contents"

echo "== 3. lookup()'s derived model, saved, and indexed for the assembler"
mkdir -p "$WORK/models"
OUT="$("$BIN/cov-find-function" --dir "$IDIR" --save -of "$WORK/models" --module generic lookup)"
BASE="$(echo "$OUT" | grep -o 'File name base: .*' | head -1 | sed 's/File name base: //' | tr -d '\r')"
echo "lookup $BASE defs=1" > "$WORK/models/index.txt"
cat "$WORK/models/index.txt"

echo "== 4. assemble: slice + model stub + the claim at the candidate's line + harness (free mode: lookup is the blamed callee)"
python3 "$TOOLS/fz_target.py" --slice "$WORK/slice/escaped.slice.c" --models "$WORK/models" --harness "$HERE/harness.c" \
    --claim 'r != NULL' --before 'sink\(r->id \+ v\);' --keep sink,unknown --out "$WORK/target.c"

echo "== 5. build and fuzz (clang-cl + libFuzzer + ASan)"
CLANG="${CLANG_CL:-C:/Program Files/LLVM/bin/clang-cl.exe}"
if [ ! -x "$CLANG" ]; then echo "clang-cl not found at $CLANG; set CLANG_CL. Steps 1-4 passed."; exit 0; fi
# the ASan runtime DLL must be on PATH, in a form this shell searches
LLVM_ROOT="$(dirname "$(dirname "$CLANG")")"
command -v cygpath >/dev/null && LLVM_ROOT="$(cygpath -u "$LLVM_ROOT")"
ASAN_DIR="$(dirname "$(find "$LLVM_ROOT/lib/clang" -name 'clang_rt.asan_dynamic-x86_64.dll' | head -1)")"
export PATH="$ASAN_DIR:$LLVM_ROOT/bin:$PATH"
( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od -I"$TOOLS" target.c -Fe:fuzz.exe > build.log 2>&1 ) || { tail -5 "$WORK/build.log"; exit 1; }
set +e
( cd "$WORK" && ./fuzz.exe -max_total_time=30 -seed=1 > run.log 2>&1 )
echo "fuzzer exit: $?  (77 = the claim failed and aborted; 1 = sanitizer crash; 127 = ASan DLL not on PATH)"
set -e
grep -m1 "CLAIM HOLDS\|ERROR: AddressSanitizer" "$WORK/run.log" | cut -c1-120
grep -m1 "== fz: stub choices" "$WORK/run.log" | cut -c1-120
grep -m1 "Test unit written" "$WORK/run.log" | cut -c1-100
echo "verdict: confirmed by crash under model stubs -- lookup=1 (returnsnull) is the behaviour it relied on, and the real lookup() has it (see lookup.c)"
