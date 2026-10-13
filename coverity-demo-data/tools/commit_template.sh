#!/bin/bash
# Commit this archived demo dataset into a Coverity Connect instance.
#
# This dataset was validated exhaustively when it was published. That work is
# not repeated here: the checks below are the quick ones, because whoever runs
# this wants data in Connect promptly and could not fix a structural problem
# anyway. The in-flight checks that DO matter -- that --strip-path took effect,
# and that no earlier first-detected date shifts -- are cheap and are performed
# per commit by tools/commit_sweep.py.
#
# Everything resolves relative to this script, so running it in place on the
# archive host and running it after copying the directory elsewhere are the
# same code path.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="" URL="" KEY="" PLATFORM_BIN="" PROJECT="" DRY=""

usage() {
  sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//;$d'
  cat <<EOF

usage: commit.sh --install <coverity-analysis-root> --url <http://host:port>
                 --auth-key-file <key.json>
                 [--platform-bin <connect>/bin] [--project NAME] [--dry-run]

  --install        Coverity Analysis root (its bin/ holds cov-commit-defects)
  --url            the Connect URL you were given. NOT the host recorded in
                   the auth key's comments block -- that is a comment, and a
                   mismatch is normal and harmless (rule 28)
  --platform-bin   Connect's bin/, if reachable; enables the post-commit
                   verification. Strongly recommended
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install)       INSTALL="$2"; shift 2 ;;
    --url)           URL="$2"; shift 2 ;;
    --auth-key-file) KEY="$2"; shift 2 ;;
    --platform-bin)  PLATFORM_BIN="$2"; shift 2 ;;
    --project)       PROJECT="$2"; shift 2 ;;
    --dry-run)       DRY="--dry-run"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done
[ -n "$INSTALL" ] && [ -n "$URL" ] && [ -n "$KEY" ] || { usage >&2; exit 1; }

MANIFEST="$HERE/MANIFEST.json"
[ -f "$MANIFEST" ] || { echo "no MANIFEST.json beside this script" >&2; exit 1; }

# Find a working python. Not just "python3 exists": on Windows shells that name
# is often a Microsoft Store stub that resolves but does not run.
PY=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c "import json" >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || { echo "no working python found (need python3 or python with json)" >&2; exit 1; }

read_json() { "$PY" -c "
import json,sys
m=json.load(open(sys.argv[1]))
print(eval(sys.argv[2],{'m':m}))" "$MANIFEST" "$1"; }

WANT_VERSION=$(read_json "m['analysis']['version']")
STRIP=$(read_json "m['commit']['strip_path'] or ''")
NVERS=$(read_json "len(m['streams'])")
[ -z "$PROJECT" ] && PROJECT=$(read_json "m['commit']['suggested_project']")

# Quick check 1: every idir the manifest names is actually here. Catches a
# truncated copy, which is the realistic failure mode after an scp.
MISSING=0
for t in $(read_json "' '.join(s['tag'] for s in m['streams'])"); do
  [ -d "$HERE/idirs/$t" ] || { echo "missing idir: $t" >&2; MISSING=1; }
done
[ "$MISSING" -eq 0 ] || { echo "dataset is incomplete -- re-copy it" >&2; exit 1; }

# Quick check 2: version compatibility. An idir is version-bound, so a wildly
# different install can simply refuse it.
HAVE_VERSION=$("$INSTALL/bin/cov-commit-defects" --ver 2>/dev/null \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
if [ -n "$HAVE_VERSION" ] && [ "$HAVE_VERSION" != "$WANT_VERSION" ]; then
  echo "[warn] dataset analyzed with $WANT_VERSION, committing with $HAVE_VERSION"
  echo "       if the commit is refused, use a matching install"
fi

cat <<EOF
dataset : $(read_json "m['project']") / $(read_json "m['dataset']")
versions: $NVERS   streams: $(read_json "','.join(m['counts']['streams'])")
analyzed: $WANT_VERSION
target  : $URL   project: $PROJECT

Take a database backup of the target BEFORE committing. First detected is
global per merge key and write-once; a mistake is corrected by restoring the
database and re-running this script, which is cheap only if the backup exists.

EOF

# The stream map lives only in MANIFEST.json -- a second copy on disk is the
# drift that silently flattens branches (rule 29). Derive it at run time.
TAGS="$(mktemp)"; trap 'rm -f "$TAGS"' EXIT
"$PY" -c "
import json,sys
m=json.load(open(sys.argv[1]))
for s in m['streams']:
    print(s['tag'], s['date'], s['stream'])" "$MANIFEST" > "$TAGS"

ARGS=(--idirs-root "$HERE/idirs" --tags "$TAGS" --url "$URL"
      --auth-key-file "$KEY" --cov-bin "$INSTALL/bin")
[ -n "$STRIP" ] && ARGS+=(--strip-path "$STRIP")
[ -n "$PLATFORM_BIN" ] && ARGS+=(--platform-bin "$PLATFORM_BIN")
[ -n "$DRY" ] && ARGS+=("$DRY")

exec "$PY" "$HERE/tools/commit_sweep.py" "${ARGS[@]}"
