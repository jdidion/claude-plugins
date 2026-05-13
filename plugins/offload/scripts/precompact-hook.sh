#!/bin/bash
# PreCompact hook: inject session state into context before compaction.
set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")
[ -z "$CWD" ] && exit 0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUMMARY=$("$SCRIPT_DIR/session-summary.sh" "$CWD" 2>/dev/null || echo "unable to gather session state")

MSG=$(cat <<'PROMPT'
Context compaction is about to start. Before /compact runs, invoke the /offload:context skill instead. It is provided by this plugin and will:

  1. Review what this session accomplished.
  2. Save learnings (feedback, project, user, reference) to auto-memory.
  3. Extract any reusable workflows as .claude/commands/*.md.
  4. Then chain to /compact.

Run /offload:context now. Do not skip this and do not invoke /compact directly — the skill ends with /compact, so compaction still happens, but session learnings are preserved first.

Session state at compaction:
PROMPT
)

FULL="${MSG}
${SUMMARY}"

ESCAPED=$(printf '%s' "$FULL" | jq -Rs '.')

echo "{\"systemMessage\": ${ESCAPED}}"
