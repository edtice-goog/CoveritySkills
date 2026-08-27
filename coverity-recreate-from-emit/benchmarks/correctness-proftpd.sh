#!/bin/bash
# Correctness test: analyze an older tag, pull the idir forward, analyze again,
# then independently full-build+analyze the later tag and check they agree.
# All three arms run in the SAME directory so capture paths are identical --
# that removes path normalization as a variable.
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.12.2
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
SRC=/home/etice/proftpd
T=/home/etice/ct/tree
R=/home/etice/ct/results
CFG=/home/etice/ct/config/coverity_config.xml
OLD=v1.3.8
NEW=v1.3.9
say(){ echo "[$(date -Is)] $*" | tee -a $R/RESULTS.txt; }

# cov-build exits 0 and reports "100%" even when the build died early, because
# the percentage is of units ATTEMPTED. And with no --config it captures ZERO
# TUs while reporting no failure at all. Assert a TU floor, not just rc=0.
check_build(){
  local idir="$1" tag="$2"
  local bad=$(grep -cE "exited with code|make: \*\*\*" "$idir/build-log.txt" 2>/dev/null || echo 0)
  local tus=$("$COV/bin/cov-manage-emit" --dir "$idir" list-json 2>/dev/null | grep -c primaryFilename)
  say "    $tag: TUs=$tus  build-failure lines=$bad"
  if [ "$bad" -ne 0 ] || [ "$tus" -lt 50 ]; then
    say "    ABORT: $tag capture is not sound"
    tail -12 "$R/$tag-build.log" 2>/dev/null | sed "s/^/        /" | tee -a $R/RESULTS.txt
    return 1
  fi
  return 0
}

build_capture(){
  cd $T || return 1
  "$COV/bin/cov-build" --dir "$1" --config "$CFG" make >> "$R/$2-build.log" 2>&1
  check_build "$1" "$2"
}

analyze(){
  local s=$(date +%s)
  "$COV/bin/cov-analyze" --dir "$1" -sf "$LIC" > "$R/$2-analyze.log" 2>&1
  local rc=$?
  say "    $2 analyze rc=$rc wall=$(( $(date +%s)-s ))s"
  if [ $rc -ne 0 ]; then
    say "    ABORT: $2 analysis failed"
    tail -8 "$R/$2-analyze.log" | sed "s/^/        /" | tee -a $R/RESULTS.txt
    return 1
  fi
  grep -E "Files analyzed|Functions analyzed|Defect occurrences found" "$1/output/summary.txt" | sed "s/^/        /" | tee -a $R/RESULTS.txt
  return 0
}

rm -rf /home/etice/ct; mkdir -p $R /home/etice/ct/config
say "############ CORRECTNESS TEST  $OLD -> $NEW"
git clone -q --shared $SRC $T || exit 1

# Rule 1/5: without a compiler configuration cov-build captures nothing, exits 0,
# and reports no failure. This step is not optional.
"$COV/bin/cov-configure" --config "$CFG" --gcc > "$R/0-covconfig.log" 2>&1
say "    cov-configure rc=$?"
say "    delta: $(git -C $T diff --name-only $OLD $NEW | wc -l) files, $(git -C $T diff --name-only $OLD $NEW | grep -cE '\.c$') .c"

say "=== [1] full capture + analyze at $OLD  (reference idir)"
git -C $T checkout -q $OLD
( cd $T && ./configure -q ) >> "$R/1-old-configure.log" 2>&1
build_capture /home/etice/ct/idir-A 1-old || exit 1
analyze /home/etice/ct/idir-A 1-old || exit 1

say "=== [2] roll tree to $NEW, REUSE the idir, incremental capture"
cp -a /home/etice/ct/idir-A /home/etice/ct/idir-reuse
git -C $T checkout -q $NEW
say "    staleness check (tool under test)"
python3 /mnt/c/Data/CoveritySkills/coverity-recreate-from-emit/tools/staleness.py \
   --bin "$COV/bin" --dir /home/etice/ct/idir-reuse --tree $T > "$R/2-staleness.log" 2>&1
say "    staleness rc=$?"
tail -14 "$R/2-staleness.log" | sed "s/^/        /" | tee -a $R/RESULTS.txt
( cd $T && ./configure -q ) >> "$R/2-reuse-configure.log" 2>&1
build_capture /home/etice/ct/idir-reuse 2-reuse || exit 1
analyze /home/etice/ct/idir-reuse 2-reuse || exit 1

say "=== [3] ORACLE: clean full capture + analyze at $NEW, same directory"
( cd $T && make distclean ) >> "$R/3-clean.log" 2>&1
git -C $T clean -xdfq; git -C $T checkout -q $NEW
( cd $T && ./configure -q ) >> "$R/3-oracle-configure.log" 2>&1
build_capture /home/etice/ct/idir-oracle 3-oracle || exit 1
analyze /home/etice/ct/idir-oracle 3-oracle || exit 1

say "=== [4] REUSED vs ORACLE -- defect sets, not totals"
python3 /mnt/c/Data/CoveritySkills/coverity-recreate-from-emit/tools/compare_analyses.py \
   --a /home/etice/ct/idir-reuse --b /home/etice/ct/idir-oracle --self-test \
   > "$R/4-compare.log" 2>&1
say "    compare rc=$?   (0=IDENTICAL 1=DIFFERENT 2=REFUSED/unsound)"
cat "$R/4-compare.log" | tee -a $R/RESULTS.txt
say "############ CORRECTNESS TEST DONE"
