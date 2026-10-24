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
LIC="${LIC:-$COV/bin/license.dat}"
SRC="${SRC:?set SRC to an analyzed reference idir}"
WORK="${WORK:-${TMPDIR:-/tmp}/coverity-bench}"
IDIR=$WORK/ff-cgm
echo "=== copying preserved idir (original untouched)"
rm -rf "$IDIR"; cp -a "$SRC" "$IDIR" || exit 1
echo "=== re-analyzing WITH --enable-callgraph-metrics $(date -Is)"
s=$(date +%s)
"$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" --enable-callgraph-metrics > $WORK/exp-cgm-analyze.log 2>&1
rc=$?
e=$(date +%s)
echo "=== rc=$rc wall=$((e-s))s $(date -Is)"
grep -E "Files analyzed|Functions analyzed|Defect occurrences" "$IDIR/output/summary.txt" 2>/dev/null
echo "=== callgraph artifacts produced"
ls -la "$IDIR"/output/*callgraph* 2>/dev/null
echo "=== CGM DONE"
