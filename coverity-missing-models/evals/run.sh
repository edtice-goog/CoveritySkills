#!/bin/bash
# The fixtures end to end: capture, analyze without models, build each model
# library, analyze a copy of the idir with it, and check the difference with
# tools/models.py compare. Every case states what must change and what must not.
#
#   killpath   a false positive: fail_hard() ends the path through a hook
#   collision  an escape: the project's error() returns, Coverity's built-in
#              error() does not, and the built-in model wins
#   arena-*    an escape: a doc is used after doc_close() destroyed its arena;
#              which function to model, and what a bare model leaves out
#   pitfall-*  a model that matches nothing, and a type primitives.h declares
#
#   usage: run.sh <coverity-install>/bin [workdir]
#
# Captures with bare cov-emit --c (the fixtures include no system headers), so
# no compiler configuration is needed. Python 3: $PYTHON, default python3.
set -euo pipefail
BIN="${1:?usage: run.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FX="$HERE/fixtures"
TOOL="$HERE/../tools/models.py"
PY="${PYTHON:-python3}"
FAILED=0

before() {   # before <name> <source>: capture and analyze without models
    local d="$WORK/$1/before"
    rm -rf "$WORK/$1" && mkdir -p "$WORK/$1"
    "$BIN/cov-emit" --dir "$d" --c "$2" > "$WORK/$1/emit.log" 2>&1
    "$BIN/cov-analyze" --dir "$d" > "$WORK/$1/before.log" 2>&1
    "$BIN/cov-format-errors" --dir "$d" --json-output-v10 "$WORK/$1/before.json" > /dev/null 2>&1
}

after() {    # after <name> <tag> <expected exit> <model source>... -- <expect>...
    local name="$1" base="$WORK/$1" tag="$2" want="$3"; shift 3
    local srcs=() exps=() a=(); while [ "$1" != "--" ]; do srcs+=("$1"); shift; done; shift
    for e in "$@"; do exps+=(--expect "$e"); done
    for s in "${srcs[@]}"; do a+=(--model-source "$s"); done
    echo "== $name: $tag"
    "$BIN/cov-make-library" --output-file "$base/$tag.lib" "${srcs[@]}" > "$base/$tag.make.log" 2>&1
    grep -h "models successfully merged" "$base/$tag.make.log" | sed 's/^/   cov-make-library: /'
    rm -rf "$base/$tag" && cp -a "$base/before" "$base/$tag"          # a copy, timestamps kept
    "$BIN/cov-analyze" --dir "$base/$tag" --model-file "$base/$tag.lib" > "$base/$tag.log" 2>&1
    "$BIN/cov-format-errors" --dir "$base/$tag" --json-output-v10 "$base/$tag.json" > /dev/null 2>&1
    set +e
    "$PY" "$TOOL" compare --before "$base/before" --after "$base/$tag" \
        --before-findings "$base/before.json" --after-findings "$base/$tag.json" \
        "${a[@]}" "${exps[@]}" > "$base/$tag.compare.txt"
    local got=$?
    set -e
    grep -E "^  [+-] |^  (ok|FAIL)|^  .*user[0-9]" "$base/$tag.compare.txt" | sed 's/^/ /'
    if [ "$got" = "$want" ]; then echo "   as expected (compare exit $got)"
    else echo "   UNEXPECTED: compare exit $got, wanted $want; see $base/$tag.compare.txt"; FAILED=1; fi
}

before killpath "$FX/killpath/fail_hard.c"
after killpath m 0 "$FX/killpath/models.c" -- \
    gone=fail_hard.c:22:FORWARD_NULL kept=fail_hard.c:29:FORWARD_NULL

before collision "$FX/collision/report.c"
echo "== collision: the inventory before any model"
"$PY" "$TOOL" inventory --idir "$WORK/collision/before" | grep -A1 "same name"
after collision m 0 "$FX/collision/models.c" -- new=report.c:19:FORWARD_NULL

before arena "$FX/arena/arena.c"
after arena owner 0 "$FX/arena/models-owner.c" -- \
    new=arena.c:164:USE_AFTER_FREE silent=arena.c:177 silent=arena.c:104
after arena destroy 0 "$FX/arena/models-destroy.c" -- \
    silent=arena.c:164 new=arena.c:104:USE_AFTER_FREE
after arena unlink+owner 0 "$FX/arena/models-unlink.c" "$FX/arena/models-owner.c" -- \
    new=arena.c:164:USE_AFTER_FREE silent=arena.c:104 silent=arena.c:177

before pitfall "$FX/killpath/fail_hard.c"
after pitfall misspelled 1 "$FX/pitfalls/misspelled.c" -- gone=fail_hard.c:22:FORWARD_NULL

echo "== pitfall: a model that declares size_t"
if "$BIN/cov-make-library" --output-file "$WORK/pitfall/size_t.lib" "$FX/pitfalls/size_t.c" > "$WORK/pitfall/size_t.log" 2>&1; then
    echo "   UNEXPECTED: cov-make-library accepted it"; FAILED=1
else
    grep -A2 "error #" "$WORK/pitfall/size_t.log" | sed 's/^/   /'
    echo "   as expected (cov-make-library failed)"
fi

echo
[ "$FAILED" = 0 ] && echo "ALL AS EXPECTED ($WORK)" || { echo "SOME CASES UNEXPECTED ($WORK)"; exit 1; }
