#!/bin/bash
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.12.2
CFG=/home/etice/llvm-cov-config/coverity_config.xml
IDIR=/home/etice/llvm-idir-ref
rm -rf "$IDIR"
echo "=== BASELINE COMMIT: $(git -C /home/etice/llvm-project rev-parse HEAD)"
echo "=== CAPTURE START $(date -Is)"
s=$(date +%s)
"$COV/bin/cov-build" --dir "$IDIR" --config "$CFG" \
    ninja -C /home/etice/llvm-build -j16
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
