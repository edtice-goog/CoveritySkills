#!/usr/bin/env bash
#
# SessionStart hook for coverity-recreate-from-emit.
#
# Purpose, deliberately minimal: notice that a project uses Coverity, tell the
# session the skill exists, and have it OFFER. It computes nothing and decides
# nothing -- the option space is not settled yet, and for a small project the
# right answer may simply be to run a full analysis.
#
# The silence guarantee: no Coverity config, no output, exit 0. Installed
# globally, it has zero effect on every non-Coverity repository.
#
# Install (once, in ~/.claude/settings.json):
#   "hooks": { "SessionStart": [ { "hooks": [
#       { "type": "command", "command": "<path-to-this-file>" } ] } ] }
set -u

# The Coverity CLI's own documented config names. Presence of one of these is
# the signal that this repository has Coverity enabled.
cfg=""
for f in coverity.yaml coverity.yml coverity.json; do
  if [ -f "$f" ]; then cfg="$f"; break; fi
done

# --- the silence guarantee -------------------------------------------------
[ -n "$cfg" ] || exit 0

# Emit context for the model. No calculation, no network, no state inspection:
# just enough for the session to make an informed offer and then stop.
cat <<JSON
{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"This project has a Coverity configuration ($cfg), so Coverity is enabled here. The 'coverity-recreate-from-emit' skill is available; it can prepare this checkout for local Coverity analysis, including reusing an intermediate directory produced elsewhere so a full capture is not needed. EARLY IN THE CONVERSATION, ask the user once whether they would like to prepare for local Coverity analysis. If they say yes, DO NOT start any capture, download, or analysis: recommend a path and let them choose. The right path depends on the project -- for a small codebase a plain full cov-build plus cov-analyze is simpler and better than importing a baseline, and the tradeoffs are still being worked out. If they say no, or do not engage, drop the subject and do not raise it again."}}
JSON
