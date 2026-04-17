#!/bin/bash
# SessionEnd hook: persist git state summary for future session pickup.
set -euo pipefail

INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || echo "")
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")

[ -z "$SESSION_ID" ] || [ -z "$CWD" ] && exit 0

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SUMMARY=$("$SCRIPT_DIR/session-summary.sh" "$CWD" 2>/dev/null || echo "")
[ -z "$SUMMARY" ] && exit 0

PERSIST_DIR="$HOME/.claude/sessions"
mkdir -p "$PERSIST_DIR"

{
  echo "timestamp: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "cwd: $CWD"
  echo "$SUMMARY"
} > "$PERSIST_DIR/${SESSION_ID}.offload.txt"

exit 0
