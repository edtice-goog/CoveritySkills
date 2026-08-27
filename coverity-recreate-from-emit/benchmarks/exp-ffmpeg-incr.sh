#!/bin/bash
# Controlled incremental-vs-full on ONE idir, one variable (--force).
#
# CRITICAL: the preserved idir was analyzed by the WIN64 binary. Re-analyzing
# with the LINUX binary invalidates the incremental cache -- cov-analyze says
# "Incremental analysis could not be used because analysis binary changed" and
# does a FULL analysis. So the first run under this binary is full no matter
# what. Run a WARMUP to establish this binary's state, and only then measure a
# true incremental. Without this the experiment measures full-vs-full ~= 1.0x.
COV=/mnt/c/Coverity/cov-analysis-linux64-2025.9.0
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
SRC=/home/etice/preserved/ffmpeg-2026-08-24/idir_local
IDIR=/home/etice/ff-incr
say(){ echo "[$(date -Is)] $*"; }
notices(){ grep -c "Incremental analysis could not be used" "$1" 2>/dev/null || echo 0; }
sums(){ grep -E "Functions analyzed|Defect occurrences found" "$IDIR/output/summary.txt" 2>/dev/null | sed 's/^/      /'; }

say "copying preserved idir (working on a COPY, original untouched)"
rm -rf "$IDIR"; cp -a "$SRC" "$IDIR" || exit 1

say "=== WARMUP: first run under THIS binary (expected FULL: binary changed)"
s=$(date +%s); "$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" > /home/etice/exp-ff-warm.out 2>&1
rcw=$?; e=$(date +%s); TW=$((e-s))
say "WARMUP rc=$rcw wall=${TW}s  binary-changed notices=$(notices /home/etice/exp-ff-warm.out)"

say "=== INCREMENTAL: same binary, nothing changed"
s=$(date +%s); "$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" > /home/etice/exp-ff-incr.out 2>&1
rci=$?; e=$(date +%s); TI=$((e-s))
say "INCR rc=$rci wall=${TI}s  binary-changed notices=$(notices /home/etice/exp-ff-incr.out)"; sums

say "=== FULL: same idir, same binary, --force"
s=$(date +%s); "$COV/bin/cov-analyze" --dir "$IDIR" -sf "$LIC" --force > /home/etice/exp-ff-full.out 2>&1
rcf=$?; e=$(date +%s); TF=$((e-s))
say "FULL rc=$rcf wall=${TF}s"; sums

say "=== RESULT  warmup=${TW}s  incremental=${TI}s  full=${TF}s"
awk -v w=$TW -v i=$TI -v f=$TF 'BEGIN{
  if(i>0) printf "    full/incremental = %.1fx\n", f/i;
  if(i>0) printf "    warmup/incremental = %.1fx  (warmup should resemble full)\n", w/i;
}'
say "=== FFINCR DONE"
