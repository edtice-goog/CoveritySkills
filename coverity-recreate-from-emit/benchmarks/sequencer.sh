#!/bin/bash
# ONE sequencer. Everything after the overnight run, strictly serial.
# Previously three chains raced: T3 fired when T2 ended, which is exactly when
# overnight stage 7 (FFmpeg) starts, and postrun fired after that.
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.12.2
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
IDIR=/home/etice/llvm-idir-timed
R=/home/etice/results
say(){ echo "[$(date -Is)] $*" | tee -a $R/RESULTS.txt; }

# T2's summary is captured the moment T2 ends, BEFORE anything can overwrite it.
# T1's summary was lost exactly this way: T2 truncated it, and the driver's grep
# did not include "Time taken by analysis".
say "############ SEQUENCER: waiting for T2 to end so its summary can be saved"
while pgrep -f "cov-analyze --dir $IDIR" >/dev/null 2>&1; do sleep 30; done
cp -a $IDIR/output/summary.txt $R/summary-T2.txt 2>/dev/null
say "=== T2 captured"
grep -E "Time taken by analysis|Files analyzed|Functions analyzed|Defect occurrences found" \
     $R/summary-T2.txt 2>/dev/null | sed 's/^/    T2  /' | tee -a $R/RESULTS.txt
grep -h "Time taken by analysis" $R/6-t2.log 2>/dev/null | sed 's/^/    T2 log: /' | tee -a $R/RESULTS.txt

say "############ waiting for the overnight run to finish (stage 7 FFmpeg)"
while ! grep -q "OVERNIGHT RUN DONE" /home/etice/overnight.log 2>/dev/null; do sleep 60; done
say "=== overnight run complete"

say "############ T3: --force full analysis, daylight, clean wall clock"
s=$(date +%s)
"$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" --force > $R/9-t3-force.log 2>&1
rc=$?; T3=$(( $(date +%s)-s ))
say "    T3 rc=$rc wall=${T3}s"
cp -a $IDIR/output/summary.txt $R/summary-T3.txt 2>/dev/null
grep -E "Time taken by analysis|Files analyzed|Functions analyzed|Defect occurrences found" \
     $R/summary-T3.txt 2>/dev/null | sed 's/^/    T3  /' | tee -a $R/RESULTS.txt

say "############ post-run: kernel, then reuse"
/home/etice/postrun-body.sh >> $R/postrun-body.log 2>&1
say "############ SEQUENCER DONE"
