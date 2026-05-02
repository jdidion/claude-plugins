#!/bin/bash
# Auto-register this session on SessionStart (startup, resume, clear all
# trigger this). Uses the Claude session ID as the registry key; the
# workspace-title slug is attached as an alias. Running on every
# SessionStart means `/clear` re-points the alias at the new session ID.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
REGISTRY="$PLUGIN_ROOT/scripts/registry.py"

INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("session_id", ""), end="")
except Exception:
    pass
' 2>/dev/null)

if [ -z "$SESSION_ID" ]; then
    echo "{\"systemMessage\": \"Handoff: session_id not in hook payload; skipping auto-register\"}"
    exit 0
fi

python3 "$REGISTRY" register "$SESSION_ID" 2>/dev/null

REPORT=$(python3 "$REGISTRY" whoami 2>/dev/null)
if [ -n "$REPORT" ] && [ "$REPORT" != "unregistered" ]; then
    ESCAPED=$(printf '%s' "$REPORT" | sed 's/"/\\"/g')
    echo "{\"systemMessage\": \"Handoff: registered as $ESCAPED\"}"
fi
