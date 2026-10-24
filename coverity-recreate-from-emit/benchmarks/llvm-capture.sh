#!/bin/bash
# ---------------------------------------------------------------------------
# Configuration. Override by exporting these before running; nothing here is
# tied to the machine the measurements were taken on.
#
#   COV   Coverity Analysis install root            (required)
#   LIC   licence file                              (default: $COV/bin/license.dat)
#   WORK  scratch root for idirs, builds and logs   (default: $TMPDIR/coverity-bench)
#   SRC   the subject under test                    (required where used)
# ---------------------------------------------------------------------------
COV="${COV:?set COV to a Coverity Analysis install root}"
SRC="${SRC:?set SRC to an llvm-project checkout}"
WORK="${WORK:-${TMPDIR:-/tmp}/coverity-bench}"
CFG=$WORK/llvm-cov-config/coverity_config.xml
IDIR=$WORK/llvm-idir-ref
rm -rf "$IDIR"
echo "=== BASELINE COMMIT: $(git -C $SRC rev-parse HEAD)"
echo "=== CAPTURE START $(date -Is)"
s=$(date +%s)
"$COV/bin/cov-build" --dir "$IDIR" --config "$CFG" \
    ninja -C $WORK/llvm-build -j16
rc=$?
e=$(date +%s)
echo "=== CAPTURE DONE rc=$rc wall=$((e-s))s $(date -Is)"
echo "=== emit summary"
"$COV/bin/cov-manage-emit" --dir "$IDIR" list 2>/dev/null | tail -3
echo "=== TU count"
"$COV/bin/cov-manage-emit" --dir "$IDIR" list-json 2>/dev/null | grep -c "\"file\"" || true
echo "=== build log health (rule 9: the build must actually build)"
grep -cE "exited with code|make: \*\*\*|FAILED:" "$IDIR/build-log.txt" 2>/dev/null || echo 0
du -sh "$IDIR"
