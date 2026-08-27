#!/bin/bash
# Serial overnight run. Nothing overlaps: this box is 8 physical cores and a
# 24GB WSL guest, and two concurrent -j16 jobs previously drove it into swap
# collapse. Every stage is -j8 and runs alone.
# Ordered cheap-answers-first so a late failure still leaves results.
COV12=/mnt/c/Coverity/cov-analysis-linux64-2025.12.2
COV9=/mnt/c/Coverity/cov-analysis-linux64-2025.9.0
LIC=/mnt/c/Coverity/cov-analysis-win64-2025.12.0/bin/license.dat
CFG=/home/etice/llvm-cov-config/coverity_config.xml
SRC=/home/etice/llvm-project
CM="-DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_PROJECTS=clang -DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_ENABLE_ASSERTIONS=OFF -DLLVM_PARALLEL_LINK_JOBS=2 -DLLVM_INCLUDE_BENCHMARKS=OFF -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++"
R=/home/etice/results
mkdir -p $R
say(){ echo "[$(date -Is)] $*" | tee -a $R/RESULTS.txt; }
mem(){ free -g | awk '/^Mem:/{printf "mem used=%sG avail=%sG", $3, $7}'; }

say "############ OVERNIGHT RUN START  cores=$(nproc) logical / 8 physical"
say "############ $(mem)"

########## 1. callgraph metrics: does --enable-callgraph-metrics add the TU?
say "=== [1] CGM: --enable-callgraph-metrics on a copy of the preserved FFmpeg idir"
rm -rf /home/etice/ff-cgm
cp -a /home/etice/preserved/ffmpeg-2026-08-24/idir_local /home/etice/ff-cgm
s=$(date +%s)
"$COV9/bin/cov-analyze" --dir /home/etice/ff-cgm -sf "$LIC" --enable-callgraph-metrics > $R/1-cgm.log 2>&1
say "    rc=$? wall=$(( $(date +%s)-s ))s"
ls -la /home/etice/ff-cgm/output/ 2>/dev/null | grep -i callgraph | tee -a $R/RESULTS.txt

########## 2. Linux kernel idir: analysis timing at kernel scale
say "=== [2] Linux kernel idir (supplied): extract, identify, analyze"
mkdir -p /home/etice/linux-idir
s=$(date +%s)
tar xJf /mnt/c/Users/EdTice/Downloads/linux-intermediate.tar.xz -C /home/etice/linux-idir 2>>$R/2-kernel.log
say "    extract rc=$? wall=$(( $(date +%s)-s ))s size=$(du -sh /home/etice/linux-idir | cut -f1)"
KID=$(find /home/etice/linux-idir -maxdepth 3 -type d -name emit | head -1)
KID=$(dirname "$KID")
say "    idir root: $KID"
say "    emit version: $(sed -n 2p $KID/emit/version 2>/dev/null) ($(sed -n 1p $KID/emit/version 2>/dev/null))"
for inst in "$COV9" "$COV12"; do
  n=$("$inst/bin/cov-manage-emit" --dir "$KID" list 2>&1 | grep -c "Expected version")
  say "    $(basename $inst): $([ "$n" -eq 0 ] && echo READS-IT || echo refuses)"
done
KCOV="$COV12"; "$COV12/bin/cov-manage-emit" --dir "$KID" list >/dev/null 2>&1 || KCOV="$COV9"
say "    using $(basename $KCOV)"
say "    TUs: $("$KCOV/bin/cov-manage-emit" --dir "$KID" list-json 2>/dev/null | grep -c primaryFilename)"
s=$(date +%s); "$KCOV/bin/cov-analyze" --dir "$KID" -sf "$LIC" > $R/2-kernel-t1.log 2>&1
K1=$?; KT1=$(( $(date +%s)-s )); say "    KERNEL T1 (first) rc=$K1 wall=${KT1}s"
grep -E "Files analyzed|Functions analyzed|Defect occurrences" "$KID/output/summary.txt" 2>/dev/null | tee -a $R/RESULTS.txt
s=$(date +%s); "$KCOV/bin/cov-analyze" --dir "$KID" -sf "$LIC" > $R/2-kernel-t2.log 2>&1
KT2=$(( $(date +%s)-s )); say "    KERNEL T2 (re-analyze) wall=${KT2}s"
awk -v a=$KT1 -v b=$KT2 'BEGIN{if(b>0)printf "    KERNEL incremental speedup = %.1fx\n", a/b}' | tee -a $R/RESULTS.txt

########## 3. plain LLVM build (B)
say "=== [3] B: plain ninja build, clean, -j8, no cov-build"
rm -rf /home/etice/llvm-build-plain
cmake -G Ninja -S $SRC/llvm -B /home/etice/llvm-build-plain $CM > $R/3-cfg.log 2>&1
s=$(date +%s); ninja -C /home/etice/llvm-build-plain -j8 > $R/3-plain.log 2>&1
rcb=$?; B=$(( $(date +%s)-s )); say "    B rc=$rcb wall=${B}s  $(mem)"

########## 4. clean capture (C)
say "=== [4] C: clean cov-build capture, fresh idir + build dir, -j8"
rm -rf /home/etice/llvm-build-timed /home/etice/llvm-idir-timed
cmake -G Ninja -S $SRC/llvm -B /home/etice/llvm-build-timed $CM >> $R/3-cfg.log 2>&1
s=$(date +%s)
"$COV12/bin/cov-build" --dir /home/etice/llvm-idir-timed --config "$CFG" ninja -C /home/etice/llvm-build-timed -j8 > $R/4-capture.log 2>&1
C=$(( $(date +%s)-s )); say "    C wall=${C}s  $(mem)"
say "    build failures: $(grep -cE 'FAILED:|exited with code' $R/4-capture.log)"
say "    compiler config dirs (probes): $(find /home/etice/llvm-idir-timed/emit/*/config -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)"

########## 5. T1 / T2 on the LLVM idir
say "=== [5] T1 first analysis"
s=$(date +%s); "$COV12/bin/cov-analyze" --dir /home/etice/llvm-idir-timed -sf "$LIC" > $R/5-t1.log 2>&1
T1=$(( $(date +%s)-s )); say "    T1 wall=${T1}s"
grep -E "Files analyzed|Functions analyzed|Defect occurrences" /home/etice/llvm-idir-timed/output/summary.txt 2>/dev/null | tee -a $R/RESULTS.txt
say "=== [6] T2 immediate re-analysis, zero changes"
s=$(date +%s); "$COV12/bin/cov-analyze" --dir /home/etice/llvm-idir-timed -sf "$LIC" > $R/6-t2.log 2>&1
T2=$(( $(date +%s)-s )); say "    T2 wall=${T2}s"

say "=== PREDICTION vs MEASURED (LLVM, gcc, -j8, quiet)"
awk -v B=$B -v C=$C -v t1=$T1 -v t2=$T2 'BEGIN{
 if(B<=0){print "    B invalid"; exit}
 printf "    plain build B : %6ds   1.00B\n", B;
 printf "    capture C     : %6ds   %.2fB    predicted ~2B\n", C, C/B;
 printf "    analyze T1    : %6ds   %.2fB    predicted ~2xC (=%.2fB)\n", t1, t1/B, 2*C/B;
 printf "    analyze T2    : %6ds   %.2fB    predicted <=0.5B\n", t2, t2/B;
 if(t2>0) printf "    T1/T2         : %.1fx           predicted ~10x\n", t1/t2;
}' | tee -a $R/RESULTS.txt

########## 7. FFmpeg three-arm incremental
say "=== [7] FFmpeg warmup / incremental / --force"
/home/etice/exp-ffmpeg-incr.sh > $R/7-ffmpeg.log 2>&1
grep -E "WARMUP|INCR|FULL|RESULT|speedup|full/incr|warmup/incr" $R/7-ffmpeg.log | tee -a $R/RESULTS.txt

say "############ OVERNIGHT RUN DONE $(date -Is)"
say "############ full results in $R/RESULTS.txt"
