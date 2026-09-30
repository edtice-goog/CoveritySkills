#!/bin/bash
# The offline half of the CVSS audit, end to end, plus the sample defects
# the report is meant to score:
#   1. dump the CWE ancestor graph the generator really walks (ChildOf
#      edges over its serialized 2017 CWE data) -- needs a JDK
#   2. audit every CWE a Coverity checker can assign against the master
#      profile, and print the gap
#   3. resolve the five CWEs a customer usually asks about, step by step
#   4. check the generator's arithmetic against the CVSS specification
#   5. capture and analyze the fixtures, so there are real defects whose
#      CWEs span scored, zero-by-design, and multi-CWE checkers
#
#   usage: run.sh <coverity-analysis>/bin [reports-dir] [workdir]
#
# Steps 1-4 need only an installed Coverity Reports package and a JDK (the
# analysis install ships one).  Step 5 needs a C compiler that
# cov-configure can template.  Nothing here touches Coverity Connect:
# committing these defects and running cov-generate-cvss-report against
# them is Step 2 onward of SKILL.md, and it writes triage attributes.
set -euo pipefail
BIN="${1:?usage: run.sh <coverity-analysis>/bin [reports-dir] [workdir]}"
REPORTS="${2:-C:/Program Files/Coverity/Coverity Reports}"
WORK="${3:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HERE/../tools"
CC="${CC:-gcc}"

mkdir -p "$WORK"
echo "== 1. the ancestor graph the generator walks"
python3 "$TOOLS/cvss_profile_audit.py" --reports-dir "$REPORTS" \
    graph --out "$WORK/cwe_childof.json"

echo
echo "== 2. the gap across every CWE a Coverity checker can assign"
python3 "$TOOLS/cvss_profile_audit.py" --reports-dir "$REPORTS" \
    audit --graph "$WORK/cwe_childof.json" --csv "$WORK/mapping.csv" \
    | sed -n '1,20p'

echo
echo "== 3. the five CWEs the question is usually about"
python3 "$TOOLS/cvss_profile_audit.py" --reports-dir "$REPORTS" \
    resolve 561 563 570 398 704 --graph "$WORK/cwe_childof.json" \
    | grep -E "^CWE-|class|score"

echo
echo "== 4. the arithmetic: CWE-190's mapped vector, as reported vs. as specified"
python3 "$TOOLS/cvss_profile_audit.py" score \
    "CVSS:3.0/AV:N/AC:L/PR:L/UI:N/S:C/C:N/I:N/A:L"

echo
echo "== 5. the sample defects"
# --aggressiveness-level high matters: UNUSED_VALUE (CWE-563) does not fire
# without it on these shapes (16 defects vs 19), and its absence looks like a
# mapping failure rather than an analysis setting.  --enable-audit-mode makes
# no difference here; that was measured, not assumed.
rm -rf "$WORK/idir" "$WORK/proj"
mkdir -p "$WORK/proj"
cp "$HERE/fixtures/"*.c "$WORK/proj/"
"$BIN/cov-configure" --config "$WORK/cfg/coverity_config.xml" --template \
    --compiler "$CC" --comptype gcc >/dev/null
( cd "$WORK/proj" && "$BIN/cov-build" --config "$WORK/cfg/coverity_config.xml" \
    --dir "$WORK/idir" "$CC" -c gap.c quality.c scored.c ) | tail -2
"$BIN/cov-analyze" --dir "$WORK/idir" --all --aggressiveness-level high \
    --strip-path "$WORK/proj/" | sed -n '/Defect occurrences/,$p'

echo
echo "== 6. the same code under MISRA C 2012, which is where the gap lives"
# Ordinary quality-and-security analysis of this fixture hits no
# zero-by-default CWE at all, and neither did three real C/C++ projects.
# A coding-standard analysis does, because MISRA's CWEs (1177, 1164, 1076,
# 691, 664, 682, 696, 908) are the ones that postdate the generator's 2017
# CWE data.  That contrast is the point of running both.
MISRA_CFG="$(dirname "$BIN")/config/coding-standards/misrac2012/misrac2012-all.config"
if [ -f "$MISRA_CFG" ]; then
    rm -rf "$WORK/idir_misra"
    cp -r "$WORK/idir" "$WORK/idir_misra"
    "$BIN/cov-analyze" --dir "$WORK/idir_misra" \
        --coding-standard-config "$MISRA_CFG" \
        --strip-path "$WORK/proj/" | sed -n '/Defect occurrences/,$p' | head -6
else
    echo "  (no misrac2012-all.config in this install; skipped)"
fi

echo
echo "workdir: $WORK"
echo "  cwe_childof.json  the generator's real ancestor graph"
echo "  mapping.csv       every CWE, its class, its vector and both scores"
echo "  idir              the sample defects, ready to cov-commit-defects"
echo "  idir_misra        the same code with the MISRA C 2012 checkers"
echo
echo "The Connect half is SKILL.md Steps 2-4, and it writes:"
echo "  tools/cvss_attributes.py setup                 the four triage attributes"
echo "  cov-commit-defects --stream <s> --dir <idir>"
echo "  cov-generate-cvss-report --scores / --report"
echo "  tools/cvss_issue_export.py <project>           the CWEs, for --issues"
