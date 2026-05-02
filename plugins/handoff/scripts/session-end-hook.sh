#!/bin/bash
# SessionEnd: unregister the current session and clean up any bridge
# processes keyed on its name. Reads session_id from hook stdin JSON.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
REGISTRY="$PLUGIN_ROOT/scripts/registry.py"
BRIDGE_PID_DIR="$HOME/.claude/handoffs/bridges"

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
    exit 0
fi

# Kill any bridge processes whose pid file mentions this session.
if [ -d "$BRIDGE_PID_DIR" ]; then
    for pid_file in "$BRIDGE_PID_DIR"/*-"$SESSION_ID".pid; do
        [ -f "$pid_file" ] || continue
        PID=$(cat "$pid_file")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
        fi
        rm -f "$pid_file"
    done
fi

# Remove the session and any aliases pointing at it.
python3 "$REGISTRY" unregister "$SESSION_ID" 2>/dev/null
