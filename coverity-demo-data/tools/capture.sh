#!/bin/bash
# Capture one version of a project into an intermediate directory.
#
# Phase 1 of the demo-data pipeline. Freely re-runnable: this stage makes no
# commits and burns no first-detected dates.
#
# Two invariants this script exists to enforce:
#
#   1. FIXED BUILD PATH. The source path is part of the defect merge key, so
#      every version must be built in the same directory, checked out in place.
#      A per-version directory prevents CIDs from merging across snapshots and
#      makes every defect look newly introduced in every snapshot.
#
#   2. VERIFIED BUILD. cov-build exits 0 even when the underlying build fails,
#      and reports its capture percentage over units ATTEMPTED rather than
#      units that should exist -- so a build that dies halfway reports a
#      confident 100% over a truncated scope.
#
# Configure via environment, or edit the defaults:
#   COV_BIN   Coverity Analysis bin directory
#   SRC       fixed build tree (a dedicated clone -- not your working checkout)
#   WS        workspace for idirs, config and logs
#   CONFIGURE_CMD   how to configure the project (default: ./configure)
#   BUILD_CMD       how to build it (default: make -- keep it SERIAL)
set -euo pipefail

TAG="${1:?usage: capture.sh <tag>}"

COV_BIN="${COV_BIN:?set COV_BIN to the Coverity Analysis bin directory}"
SRC="${SRC:?set SRC to the fixed build tree}"
WS="${WS:?set WS to the workspace directory}"
CONFIGURE_CMD="${CONFIGURE_CMD:-./configure}"
# Serial on purpose. A project whose makefile races will capture a different
# scope on different runs, moving defect counts for reasons unrelated to code.
BUILD_CMD="${BUILD_CMD:-make}"

IDIR="$WS/idirs/$TAG"
CFG="$WS/cfg"

mkdir -p "$CFG" "$WS/logs"
rm -rf "$IDIR"; mkdir -p "$IDIR"

cd "$SRC"
git checkout -qf "$TAG"
# Stale generated files from the previous version would otherwise be captured,
# putting artifacts of our own process into the version deltas.
git clean -xdfq

# One template configuration, created once and reused for every version.
# --template is mandatory; see the coverity-compiler-configuration skill.
if [ ! -e "$CFG/coverity_config.xml" ]; then
  "$COV_BIN/cov-configure" --config "$CFG/coverity_config.xml" \
      --template --compiler gcc --comptype gcc \
      > "$WS/logs/cov-configure.log" 2>&1
fi

echo "[$TAG] configure..."
$CONFIGURE_CMD > "$WS/logs/$TAG.configure.log" 2>&1

echo "[$TAG] cov-build..."
"$COV_BIN/cov-build" --config "$CFG/coverity_config.xml" --dir "$IDIR" \
    $BUILD_CMD > "$WS/logs/$TAG.build.log" 2>&1

# cov-build's own exit code cannot be trusted here -- check the log.
if grep -qE "^\[WARNING\] Build command .* exited with code [1-9]" "$WS/logs/$TAG.build.log" \
   || grep -qE "^(make|make\[[0-9]+\]): \*\*\* " "$WS/logs/$TAG.build.log"; then
  echo "[$TAG] BUILD FAILED -- capture is truncated, refusing to proceed" >&2
  grep -E "^(make|make\[[0-9]+\]): \*\*\* " "$WS/logs/$TAG.build.log" | head -5 >&2
  exit 1
fi

CU=$(grep -oE "^Emitted [0-9]+ C/C\+\+ compilation units" "$WS/logs/$TAG.build.log" \
     | grep -oE "[0-9]+" | tail -1)
echo "$TAG $CU" >> "$WS/logs/cu-counts.txt"
echo "[$TAG] captured $CU compilation units (build clean)"

# Compare cu-counts.txt across versions before committing anything. A step
# change with no corresponding code change is a capture problem, not a finding.
