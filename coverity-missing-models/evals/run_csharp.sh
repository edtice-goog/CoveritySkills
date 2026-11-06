#!/bin/bash
# The C# fixtures end to end, like run.sh: capture the project once, analyze
# it without models, then a copy per case, checked with tools/models.py compare.
#
#   source        a model making MemoryStream(byte[]) a taint source: the file
#                 bytes' taint no longer reaches the stream
#   source-alias  the same, with Reference.Alias(this, buffer): still lost
#   entry-point   a simple_entry_point directive instead: the request handler
#                 is reported and the file case is kept
#   ctor-tainted  method_returns_tainted_data on a constructor: dropped
#   throw         a throw added to ResourceManager.GetString: the model
#                 applies (its null return is reported), the handler stays
#                 unreachable
#
#   usage: run_csharp.sh <coverity-install>/bin [workdir]
#
# Needs the .NET SDK (dotnet) on PATH. C# is configured into a config file in
# the workdir, not the installation's. Python 3: $PYTHON, default python3.
set -euo pipefail
BIN="${1:?usage: run_csharp.sh <install>/bin [workdir]}"
WORK="${2:-$(mktemp -d)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FX="$HERE/fixtures/csharp"
TOOL="$HERE/../tools/models.py"
PY="${PYTHON:-python3}"
CFG="$WORK/config/coverity_config.xml"
OPTS=(--enable UNSAFE_DESERIALIZATION --distrust-filesystem --trust-network)
FAILED=0

echo "== capture"
rm -rf "$WORK/app" "$WORK/before" && mkdir -p "$WORK/app"
cp "$FX/app/"* "$WORK/app/"
"$BIN/cov-configure" --config "$CFG" --cs > "$WORK/configure.log" 2>&1
"$BIN/cov-build" --config "$CFG" --dir "$WORK/before" dotnet build "$WORK/app/Probe.csproj" -c Debug \
    --no-incremental -p:UseSharedCompilation=false > "$WORK/build.log" 2>&1
grep -h "C# compilation units" "$WORK/build.log" | sed 's/^/   /'
"$BIN/cov-analyze" --dir "$WORK/before" "${OPTS[@]}" > "$WORK/before.log" 2>&1
"$BIN/cov-format-errors" --dir "$WORK/before" --json-output-v10 "$WORK/before.json" > /dev/null 2>&1

case_() {    # case_ <tag> model|directive <file> -- <expect>...
    local tag="$1" kind="$2" file="$3"; shift 4
    local exps=() extra=() src=()
    for e in "$@"; do exps+=(--expect "$e"); done
    echo "== $tag"
    if [ "$kind" = model ]; then
        "$BIN/cov-make-library" --config "$CFG" --output-file "$WORK/$tag.lib" "$file" > "$WORK/$tag.make.log" 2>&1
        grep -h "models successfully merged" "$WORK/$tag.make.log" | sed 's/^/   cov-make-library: /'
        extra=(--model-file "$WORK/$tag.lib"); src=(--model-source "$file")
    else
        extra=(--directive-file "$file")
    fi
    rm -rf "$WORK/$tag" && cp -a "$WORK/before" "$WORK/$tag"
    "$BIN/cov-analyze" --dir "$WORK/$tag" "${OPTS[@]}" "${extra[@]}" > "$WORK/$tag.log" 2>&1
    grep -h "^\[ERROR\]\|^\[WARNING\]" "$WORK/$tag.log" | sed 's/^/   console: /' || true
    "$BIN/cov-format-errors" --dir "$WORK/$tag" --json-output-v10 "$WORK/$tag.json" > /dev/null 2>&1
    set +e
    "$PY" "$TOOL" compare --before "$WORK/before" --after "$WORK/$tag" \
        --before-findings "$WORK/before.json" --after-findings "$WORK/$tag.json" \
        "${src[@]}" "${exps[@]}" > "$WORK/$tag.compare.txt"
    local got=$?
    set -e
    grep -E "^  [+-] |^  (ok|FAIL)|^  .*user[0-9]" "$WORK/$tag.compare.txt" | sed 's/^/ /'
    if [ "$got" = 0 ]; then echo "   as expected"
    else echo "   UNEXPECTED: see $WORK/$tag.compare.txt"; FAILED=1; fi
}

case_ source model "$FX/models/source.cs" -- \
    gone=Passthrough.cs:15:UNSAFE_DESERIALIZATION kept=Handlers.cs:33:FORWARD_NULL
case_ source-alias model "$FX/models/source-alias.cs" -- \
    gone=Passthrough.cs:15:UNSAFE_DESERIALIZATION
case_ entry-point directive "$FX/models/entry-point.json" -- \
    new=Passthrough.cs:23:UNSAFE_DESERIALIZATION kept=Passthrough.cs:15:UNSAFE_DESERIALIZATION
case_ ctor-tainted directive "$FX/models/ctor-returns-tainted.json" -- \
    silent=Passthrough.cs:23 kept=Passthrough.cs:15:UNSAFE_DESERIALIZATION
if grep -q "doesn't have a return" "$WORK/ctor-tainted/output/directives.log"; then
    echo "   directives.log: $(grep -o "matches method .* which doesn't have a return" "$WORK/ctor-tainted/output/directives.log")"
else
    echo "   UNEXPECTED: directives.log does not say the constructor has no return"; FAILED=1
fi
case_ throw model "$FX/models/throw.cs" -- \
    new=Handlers.cs:14:NULL_RETURNS silent=Handlers.cs:19 kept=Handlers.cs:33:FORWARD_NULL

echo
[ "$FAILED" = 0 ] && echo "ALL AS EXPECTED ($WORK)" || { echo "SOME CASES UNEXPECTED ($WORK)"; exit 1; }
