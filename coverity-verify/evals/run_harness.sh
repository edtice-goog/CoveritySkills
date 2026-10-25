#!/bin/bash
# The router and the harness route, end to end on two fixtures:
#   A. evals/harness/app.c (+ cfg.c in the same idir): a native-checker shape,
#      handle() copies lookup_cfg()'s result without a test. Router: native
#      finding, TU compiles with the recovered flags -> HARNESS. The TU is
#      compiled as-is (handle and its static helper trim run as code, <string.h>
#      is the real header), lookup_cfg is the one external and gets its model
#      stub; the claim fails on an input through returnsnull, which the real
#      lookup_cfg has -> confirmed.
#   B. evals/harness/declined/app2.c: includes a header found only through -I
#      at capture time, and the target is static. The manifest cannot supply
#      the header, tu.c does not compile from it -> the router DECLINES harness
#      with that reason and falls back to EXTRACTION; the slice of handle2()
#      emits (the slicer prints the declarations from the emit) and the run
#      proceeds as today.
#
#   usage: run_harness.sh <coverity-install>/bin [workdir]
#   MANIFEST=<path to tu_manifest.py> overrides the stand-in in evals/harness/.
set -euo pipefail
BIN="${1:?usage: run_harness.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
SLICER="${SLICER:-$HERE/../../coverity-function-slice/tools/slice_function.py}"
MANIFEST="${MANIFEST:-$HERE/harness/manifest_stub.py}"
CLANG="${CLANG_CL:-C:/Program Files/LLVM/bin/clang-cl.exe}"
[ -x "$CLANG" ] || { echo "clang-cl not found at $CLANG; set CLANG_CL"; exit 1; }
LLVM_ROOT="$(dirname "$(dirname "$CLANG")")"
command -v cygpath >/dev/null && LLVM_ROOT="$(cygpath -u "$LLVM_ROOT")"
ASAN_DIR="$(dirname "$(find "$LLVM_ROOT/lib/clang" -name 'clang_rt.asan_dynamic-x86_64.dll' | head -1)")"
export PATH="$ASAN_DIR:$LLVM_ROOT/bin:$PATH"
IDIR="$WORK/idir"; rm -rf "$IDIR" "$WORK/models" "$WORK/manA" "$WORK/manB" "$WORK/outA" "$WORK/sliceB" "$WORK/target-B.c"

# app.c includes <string.h>; bare cov-emit has no system include path, so the
# EMIT sees the stand-in in harness/sysinc (a real build records its own). The
# harness route's build does not: clang-cl compiles the TU against the real header.
echo "== 1. one idir, three TUs; lookup_cfg's derived model saved"
"$BIN/cov-emit" --dir "$IDIR" --c "$HERE/harness/cfg.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c --sys_include "$HERE/harness/sysinc" "$HERE/harness/app.c" | tail -1
"$BIN/cov-emit" --dir "$IDIR" --c -I"$HERE/harness/declined/inc" "$HERE/harness/declined/app2.c" | tail -1
"$BIN/cov-analyze" --dir "$IDIR" > "$WORK/analyze.log" 2>&1
"$BIN/cov-format-errors" --dir "$IDIR" --emacs-style 2>/dev/null | grep -i "null\|handle" | head -4 | sed 's/^/   /' || true
mkdir -p "$WORK/models"
OUT="$("$BIN/cov-find-function" --dir "$IDIR" --save -of "$WORK/models" --module generic lookup_cfg)"
BASE="$(echo "$OUT" | grep -o 'File name base: .*' | head -1 | sed 's/File name base: //' | tr -d '\r')"
echo "lookup_cfg $BASE defs=1" > "$WORK/models/index.txt"

echo "== A. the manifest of app.c's TU, the router, the harness route"
python3 "$MANIFEST" --dir "$IDIR" --bin "$BIN" --tu 2 --name handle --out "$WORK/manA" --models "$WORK/models"
python3 "$TOOLS/verify_route.py" --manifest "$WORK/manA" --origin native --compile --out "$WORK/manA/route.json"
grep -q '"route": "harness"' "$WORK/manA/route.json" || { echo "   FAIL: expected the harness route for A"; exit 1; }
python3 "$TOOLS/fz_harness.py" --manifest "$WORK/manA" --models "$WORK/models" --driver "$HERE/harness/driver.c" \
    --claim 'v != NULL' --before 'strncpy\(buf, v, 15\);' --dir "$IDIR" --bin "$BIN" --out "$WORK/outA"
echo "   the TU's only edit:"; diff "$WORK/manA/tu.c" "$WORK/outA/tu.fz.c" | sed 's/^/      /' || true
cmd //c "$(cygpath -w "$WORK/outA/build.bat")" > "$WORK/outA/build.log" 2>&1 || { tail -8 "$WORK/outA/build.log"; exit 1; }
set +e
( cd "$WORK/outA" && ./fz.exe -max_total_time=20 -seed=1 > run.log 2>&1 ); rc=$?
set -e
echo "   exit $rc; $(grep -m1 -o 'fz: CLAIM HOLDS.*' "$WORK/outA/run.log" | cut -c1-60); $(grep -m1 -o 'stub choices on this input:.*' "$WORK/outA/run.log")"
[ "$rc" = 77 ] || { echo "   FAIL: expected the claim to fail through lookup_cfg's returnsnull"; exit 1; }
echo "   record: $(python3 -c "import json,sys; r=json.load(open(sys.argv[1])); print('route', r['route'], '| as code', r['as_code'], '| stubbed', [s['name'] for s in r['stubbed']], '| real libc', r['real_libc'], '| TU included', r['tu_included_not_linked'])" "$WORK/outA/route.json")"

echo "== B. the manifest of app2.c's TU, the router declines, extraction takes over"
python3 "$MANIFEST" --dir "$IDIR" --bin "$BIN" --tu 3 --name handle2 --out "$WORK/manB" --models "$WORK/models"
python3 "$TOOLS/verify_route.py" --manifest "$WORK/manB" --origin native --compile --out "$WORK/manB/route.json"
grep -q '"route": "extraction"' "$WORK/manB/route.json" || { echo "   FAIL: expected the router to decline harness for B"; exit 1; }
python3 "$SLICER" --dir "$IDIR" --bin "$BIN" --tu 3 --name handle2 --out "$WORK/sliceB" --emit | grep "cov-emit"
python3 "$TOOLS/fz_target.py" --slice "$WORK/sliceB/handle2.slice.c" --models "$WORK/models" --harness "$HERE/harness/declined/harness2.c" \
    --claim 'v != NULL' --before 'local_len\(v\)|LOCAL_LEN\(v\)' --out "$WORK/target-B.c" | grep "lookup_cfg\|slice set"
( cd "$WORK" && "$CLANG" -fsanitize=fuzzer,address -Zi -Od -I"$TOOLS" target-B.c -Fe:fuzz-B.exe > build-B.log 2>&1 ) || { tail -5 "$WORK/build-B.log"; exit 1; }
set +e
( cd "$WORK" && ./fuzz-B.exe -max_total_time=20 -seed=1 > run-B.log 2>&1 ); rc=$?
set -e
echo "   exit $rc; $(grep -m1 -o 'fz: CLAIM HOLDS.*' "$WORK/run-B.log" | cut -c1-60); $(grep -m1 -o 'stub choices on this input:.*' "$WORK/run-B.log")"
[ "$rc" = 77 ] || { echo "   FAIL: expected the extraction fallback to reach the same confirmation"; exit 1; }
echo "== verdicts"
echo "   A: route harness; confirmed by crash under model stubs (lookup_cfg=returnsnull; the real lookup_cfg has it): a defect"
echo "   B: route extraction, harness declined with the reason in route.json; the same confirmation from the slice"
