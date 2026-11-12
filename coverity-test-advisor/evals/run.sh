#!/bin/bash
# The gap fixture end to end: a two-commit C library, captured and analyzed
# at each commit with the same commands, the head's tests run under gcov, and
# Test Advisor's analyze and finish on the pair. Every case states what must
# be true.
#
#   base  parse_len() reads digits from s
#   head  parse_len() returns -1 when s is NULL (a new branch and a new
#         result for its callers); strutil_name() returns a longer string
#         (a body change no caller depends on); STRUTIL_VERSION goes 1 -> 2
#         (a changed line in no function)
#   tests none passes NULL
#
#   usage: run.sh <coverity-install>/bin [workdir]
#
# Linux only. Needs gcc (the Coverity build), gcc-14 and gcov-14 (the
# coverage build), git, and Python 3 ($PYTHON, default python3). $COV_SF, if
# set, is passed to cov-analyze as --security-file. $TA_TOOLS overrides the
# tools directory (default: the skill's tools/). The workdir is created if
# needed and its previous contents for this fixture are replaced.
set -euo pipefail
BIN="${1:?usage: run.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FX="$HERE/fixtures/gap"
TOOLS="${TA_TOOLS:-$HERE/../tools}"
PY="${PYTHON:-python3}"
SF=()
[ -n "${COV_SF:-}" ] && SF=(--security-file "$COV_SF")
FAILED=0
GIT=(git -c user.name=fixture -c user.email=fixture@example.invalid -c init.defaultBranch=main)

check() {   # check <name> <command...>: PASS when the command succeeds
    local name="$1"; shift
    if "$@"; then echo "PASS $name"; else echo "FAIL $name"; FAILED=1; fi
}

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
rm -rf "$WORK"/{repo,base,head,cov,gcov,cfg,idir-base,idir-head,idir-head-all,out,out-*}

# 1. The repository: the base commit, then the head on top of it.
mkdir -p "$WORK/repo"
cp -r "$FX/base/." "$WORK/repo/"
"${GIT[@]}" -C "$WORK/repo" init -q
"${GIT[@]}" -C "$WORK/repo" add -A
"${GIT[@]}" -C "$WORK/repo" commit -qm base
cp -r "$FX/head/." "$WORK/repo/"
"${GIT[@]}" -C "$WORK/repo" add -A
"${GIT[@]}" -C "$WORK/repo" commit -qm head
BASE="$(git -C "$WORK/repo" rev-parse HEAD~1)"
HEAD="$(git -C "$WORK/repo" rev-parse HEAD)"

# 2. Capture and analyze each commit with the same commands (a template
#    configuration, rule 1). Only the library is captured, as a project's
#    own build would build it; the tests are built in the coverage tree.
"$BIN/cov-configure" --config "$WORK/cfg/coverity_config.xml" --template \
    --compiler gcc --comptype gcc > "$WORK/configure.log" 2>&1
for side in base head; do
    sha=$BASE; [ "$side" = head ] && sha=$HEAD
    git -C "$WORK/repo" worktree add -q --detach "$WORK/$side" "$sha"
    (cd "$WORK/$side" && "$BIN/cov-build" --config "$WORK/cfg/coverity_config.xml" \
        --dir "$WORK/idir-$side" sh -c 'gcc -c src/strutil.c -o strutil.o && ar rcs libstrutil.a strutil.o') \
        > "$WORK/build-$side.log" 2>&1
    "$BIN/cov-analyze" --dir "$WORK/idir-$side" "${SF[@]}" > "$WORK/analyze-$side.log" 2>&1
done
check "base and head analyzed" test -f "$WORK/idir-base/output/summary.txt" -a -f "$WORK/idir-head/output/summary.txt"

# 3. Coverage of the head's tests, from a separate build of the same commit.
git -C "$WORK/repo" worktree add -q --detach "$WORK/cov" "$HEAD"
(cd "$WORK/cov" \
    && gcc-14 -O0 -g --coverage -fcondition-coverage -c src/strutil.c -o src/strutil.o \
    && gcc-14 -O0 -g --coverage -fcondition-coverage -c test/test_strutil.c -o test/test_strutil.o \
    && gcc-14 --coverage -o test_strutil src/strutil.o test/test_strutil.o \
    && ./test_strutil \
    && gcov-14 --json-format --branch-probabilities --conditions -o src src/strutil.c \
    && gcov-14 --json-format --branch-probabilities --conditions -o test test/test_strutil.c) \
    > "$WORK/coverage.log" 2>&1
mkdir -p "$WORK/gcov"
mv "$WORK/cov"/*.gcov.json.gz "$WORK/gcov/"
check "coverage written" test -f "$WORK/gcov/strutil.gcov.json.gz"

[ -n "${STOP_AFTER_BUILD:-}" ] && { echo "built in $WORK"; exit $FAILED; }

ta() {   # ta <out> [analyze arguments...]: run Test Advisor's analyze, print its exit code
    local out="$1"; shift
    set +e
    PYTHONPATH="$TOOLS" "$PY" -m ta.run analyze --repo "$WORK/repo" --cov-bin "$BIN" \
        --coverage "$WORK/gcov" --coverage-format gcov --out "$out" "$@" > "$out.log" 2>&1
    echo $?
    set -e
}

# 4. The pair, as it should be run.
rc=$(ta "$WORK/out" --base-idir "$WORK/idir-base" --base-commit "$BASE" \
    --head-idir "$WORK/idir-head" --head-commit "$HEAD")
check "analyze exits 0 (ok)" [ "$rc" = 0 ]
check "analyze ends with its status line" grep -q '^TA-STATUS: ok ' "$WORK/out.log"
"$PY" "$HERE/check_gap.py" analyze "$WORK/out" || FAILED=1

set +e
PYTHONPATH="$TOOLS" "$PY" -m ta.run finish --out "$WORK/out" --cov-bin "$BIN" > "$WORK/finish.log" 2>&1
rc=$?
set -e
check "finish without verdicts exits 0" [ "$rc" = 0 ]
"$PY" "$HERE/check_gap.py" finish "$WORK/out" || FAILED=1

# 5. Refusals: the head analyzed with other options, and a head commit the
#    head idir was not built from.
cp -a "$WORK/idir-head" "$WORK/idir-head-all"
"$BIN/cov-analyze" --dir "$WORK/idir-head-all" --all "${SF[@]}" > "$WORK/analyze-head-all.log" 2>&1
rc=$(ta "$WORK/out-options" --base-idir "$WORK/idir-base" --base-commit "$BASE" \
    --head-idir "$WORK/idir-head-all" --head-commit "$HEAD")
check "different cov-analyze options: exit 3 (refused)" [ "$rc" = 3 ]
rc=$(ta "$WORK/out-commit" --base-idir "$WORK/idir-base" --base-commit "$BASE" \
    --head-idir "$WORK/idir-head" --head-commit "$BASE")
check "head idir not from the head commit: exit 3 (refused)" [ "$rc" = 3 ]

echo
[ "$FAILED" = 0 ] && echo "all cases as expected ($WORK)" || echo "SOME CASES FAILED ($WORK)"
exit $FAILED
