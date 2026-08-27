#!/bin/bash
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.9.0
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
SRC=/home/etice/preserved/ffmpeg-2026-08-24/idir_local
IDIR=/home/etice/ff-cgm
echo "=== copying preserved idir (original untouched)"
rm -rf "$IDIR"; cp -a "$SRC" "$IDIR" || exit 1
echo "=== re-analyzing WITH --enable-callgraph-metrics $(date -Is)"
s=$(date +%s)
"$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" --enable-callgraph-metrics > /home/etice/exp-cgm-analyze.log 2>&1
rc=$?
e=$(date +%s)
echo "=== rc=$rc wall=$((e-s))s $(date -Is)"
grep -E "Files analyzed|Functions analyzed|Defect occurrences" "$IDIR/output/summary.txt" 2>/dev/null
echo "=== callgraph artifacts produced"
ls -la "$IDIR"/output/*callgraph* 2>/dev/null
echo "=== CGM DONE"
