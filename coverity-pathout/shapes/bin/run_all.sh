#!/bin/bash
# Run EVERY shape checker over one intermediate directory in a single
# cov-analyze pass and write the hits as cov-format-errors v10 JSON. For the
# case where no defect has escaped yet: a PATHOUT is known, nothing else is,
# so every shape is a hypothesis.
#
#   usage: bin/run_all.sh <coverity-install>/bin <idir> [outdir]
#
# The idir must be a COPY: cov-analyze replaces <idir>/output, and the
# original analysis-log.txt is what the coverity-pathout skill reads first.
# The script refuses an idir that already has an output/ unless IN_PLACE=1.
#
# Writes <outdir>/candidates.json (default: <idir>/../shapes-out) and prints a
# per-checker count. Filter to PATHOUT functions afterwards with the skill's
# tools/pathout_filter.py; the README maps each checker to the components
# whose path-out makes its hits relevant.
set -euo pipefail
BIN="${1:?usage: run_all.sh <install>/bin <idir> [outdir]}"
IDIR="${2:?usage: run_all.sh <install>/bin <idir> [outdir]}"
OUT="${3:-$(dirname "$IDIR")/shapes-out}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

if [ -d "$IDIR/output" ] && [ "${IN_PLACE:-0}" != 1 ]; then
  echo "refusing: $IDIR already has an output/ directory. Run this on a copy (cp -rp), or set IN_PLACE=1 to overwrite it." >&2
  exit 2
fi
mkdir -p "$OUT"
ARGS=()
for cxm in "$HERE"/checkers/*.cxm; do ARGS+=(--codexm "$cxm"); done
echo "analyzing $IDIR with ${#ARGS[@]} shape checkers ..." | sed 's/ [0-9]* shape/ '"$(( ${#ARGS[@]} / 2 ))"' shape/'
"$BIN/cov-analyze" --dir "$IDIR" --disable-default "${ARGS[@]}" > "$OUT/cov-analyze.log" 2>&1 || {
  echo "cov-analyze failed; see $OUT/cov-analyze.log" >&2
  grep -A4 'Failed to parse\|ERROR' "$OUT/cov-analyze.log" | head -12 >&2
  exit 1
}
"$BIN/cov-format-errors" --dir "$IDIR" --json-output-v10 "$OUT/candidates.json" > "$OUT/cov-format-errors.log" 2>&1
echo "hits per checker (all functions; filter to PATHOUT functions next):"
grep -o '"checkerName" *: *"[^"]*"' "$OUT/candidates.json" | sed 's/.*: *"//; s/"$//' | sort | uniq -c | sort -rn
echo "written: $OUT/candidates.json"
