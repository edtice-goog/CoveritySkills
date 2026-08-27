#!/bin/bash
# REUSE path at C++ scale. Two arms, because there are two cohorts:
#   ARM 1 (400-commit delta) -- CI / PR cohort. Correctness over a large
#         roll-forward, and the saving against a FULL capture.
#   ARM 2 (3 edited files)   -- desktop cohort. The saving against the
#         INCREMENTAL BUILD the developer just ran. This is the harder bar.
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.12.2
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
CFG=/home/etice/llvm-cov-config/coverity_config.xml
SRC=/home/etice/llvm-project
R=/home/etice/results
CM="-DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_PROJECTS=clang -DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_ENABLE_ASSERTIONS=OFF -DLLVM_PARALLEL_LINK_JOBS=2 -DLLVM_INCLUDE_BENCHMARKS=OFF -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++"
say(){ echo "[$(date -Is)] $*" | tee -a $R/RESULTS.txt; }
sums(){ grep -E "Files analyzed|Functions analyzed|Defect occurrences found" "$1/output/summary.txt" 2>/dev/null | sed "s/^/        /"; }
ratio(){ awk -v a="$1" -v b="$2" -v l="$3" 'BEGIN{if(a>0) printf "        %s = %.1fx\n", l, b/a}'; }

A=$(git -C $SRC log --format=%H | tail -1)
BH=$(git -C $SRC rev-parse HEAD)
say "REUSE: A=$A  B=$BH"
say "    commits between: $(git -C $SRC rev-list --count $A..$BH)"
say "    files changed  : $(git -C $SRC diff --name-only $A $BH | wc -l)"

########## ARM 1
say "=== [1] full capture at A (the reference idir)"
git -C $SRC checkout -q $A || exit 1
rm -rf /home/etice/llvm-build-A /home/etice/llvm-idir-A
cmake -G Ninja -S $SRC/llvm -B /home/etice/llvm-build-A $CM > $R/R-cfgA.log 2>&1
s=$(date +%s)
"$COV/bin/cov-build" --dir /home/etice/llvm-idir-A --config "$CFG" ninja -C /home/etice/llvm-build-A -j8 > $R/R-capA.log 2>&1
TA=$(( $(date +%s)-s )); say "    full capture at A: ${TA}s"

say "=== [2] roll tree forward to B, reuse the idir"
git -C $SRC checkout -q $BH || exit 1
rm -rf /home/etice/llvm-idir-reuse
cp -a /home/etice/llvm-idir-A /home/etice/llvm-idir-reuse
say "    staleness check (tool under test)"
s=$(date +%s)
python3 /mnt/c/Data/CoveritySkills/coverity-recreate-from-emit/tools/staleness.py \
  --bin "$COV/bin" --dir /home/etice/llvm-idir-reuse --tree $SRC > $R/R-staleness.log 2>&1
rcs=$?; say "    staleness rc=$rcs wall=$(( $(date +%s)-s ))s"
tail -12 $R/R-staleness.log | sed "s/^/        /" | tee -a $R/RESULTS.txt

say "=== [3] incremental capture into the reused idir"
cmake -G Ninja -S $SRC/llvm -B /home/etice/llvm-build-A $CM >> $R/R-cfgA.log 2>&1
s=$(date +%s)
"$COV/bin/cov-build" --dir /home/etice/llvm-idir-reuse --config "$CFG" ninja -C /home/etice/llvm-build-A -j8 > $R/R-capIncr.log 2>&1
TI=$(( $(date +%s)-s )); say "    incremental capture: ${TI}s"
ratio "$TI" "$TA" "CI cohort: full-capture / reuse" | tee -a $R/RESULTS.txt

say "=== [4] analyze the reused idir"
s=$(date +%s); "$COV/bin/cov-analyze" --dir /home/etice/llvm-idir-reuse -sf "$LIC" > $R/R-analyze.log 2>&1
say "    analyze reused: $(( $(date +%s)-s ))s"
say "=== [5] model provenance (PROVISIONAL tool -- text location, not TU)"
python3 /mnt/c/Data/CoveritySkills/coverity-recreate-from-emit/tools/model_provenance.py \
  --dir /home/etice/llvm-idir-reuse --tree $SRC > $R/R-provenance.log 2>&1
tail -12 $R/R-provenance.log | sed "s/^/        /" | tee -a $R/RESULTS.txt

say "=== [6] REUSED vs ORACLE -- the question that decides whether this works"
echo "      reused:" | tee -a $R/RESULTS.txt; sums /home/etice/llvm-idir-reuse | tee -a $R/RESULTS.txt
echo "      oracle:" | tee -a $R/RESULTS.txt; sums /home/etice/llvm-idir-timed | tee -a $R/RESULTS.txt
# Summary totals are NOT the verdict: a defect appearing in one place while
# another vanishes leaves the total unchanged. Compare the defect SETS.
say "    defect-set comparison (--self-test proves the oracle can disagree)"
python3 /mnt/c/Data/CoveritySkills/coverity-recreate-from-emit/tools/compare_analyses.py \
    --a /home/etice/llvm-idir-reuse --b /home/etice/llvm-idir-timed --self-test \
    > $R/R-compare.log 2>&1
rcc=$?
say "    compare rc=$rcc  (0=identical 1=different 2=REFUSED/unsound)"
tail -30 $R/R-compare.log | sed "s/^/        /" | tee -a $R/RESULTS.txt

########## ARM 2 -- the desktop cohort, the harder bar
say "=== [7] INNER LOOP: 3 edited files, vs the incremental build"
F1=$SRC/llvm/lib/Support/APInt.cpp
F2=$SRC/llvm/lib/Support/StringRef.cpp
F3=$SRC/clang/lib/Basic/Diagnostic.cpp
for f in $F1 $F2 $F3; do
  [ -f "$f" ] && echo "" >> "$f" && echo "// touched for inner-loop measurement" >> "$f"
done
say "    touched: $(for f in $F1 $F2 $F3; do [ -f $f ] && basename $f; done | tr "\n" " ")"

s=$(date +%s); ninja -C /home/etice/llvm-build-plain -j8 > $R/R-inc-plain.log 2>&1
IB=$(( $(date +%s)-s )); say "    incremental PLAIN build : ${IB}s"

rm -rf /home/etice/llvm-idir-inner
cp -a /home/etice/llvm-idir-reuse /home/etice/llvm-idir-inner
s=$(date +%s)
"$COV/bin/cov-build" --dir /home/etice/llvm-idir-inner --config "$CFG" ninja -C /home/etice/llvm-build-A -j8 > $R/R-inc-cap.log 2>&1
IC=$(( $(date +%s)-s )); say "    incremental CAPTURE     : ${IC}s"

s=$(date +%s); "$COV/bin/cov-analyze" --dir /home/etice/llvm-idir-inner -sf "$LIC" > $R/R-inc-anz.log 2>&1
IA=$(( $(date +%s)-s )); say "    incremental ANALYSIS    : ${IA}s"

say "    TOTAL inner-loop (capture+analyze) = $((IC+IA))s   vs plain incremental build ${IB}s"
ratio "$IB" "$((IC+IA))" "desktop cohort: tool-cost / incremental-build" | tee -a $R/RESULTS.txt
git -C $SRC checkout -- "$F1" "$F2" "$F3" 2>/dev/null
say "=== REUSE DONE"
