#!/bin/bash
# PreCompact hook: inject session state into context before compaction.
set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")
[ -z "$CWD" ] && exit 0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUMMARY=$("$SCRIPT_DIR/session-summary.sh" "$CWD" 2>/dev/null || echo "unable to gather session state")

MSG=$(cat <<'PROMPT'
Context compaction starting. If important decisions, conventions, or findings from this session have not been saved to auto-memory, save them now before context is lost.

Session state at compaction:
PROMPT
)

FULL="${MSG}
${SUMMARY}"

ESCAPED=$(printf '%s' "$FULL" | jq -Rs '.')

echo "{\"systemMessage\": ${ESCAPED}}"
