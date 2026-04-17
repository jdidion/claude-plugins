#!/bin/bash
# Clean up on session end: stop any bridge processes, deregister.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
REGISTRY="$PLUGIN_ROOT/scripts/registry.py"
BRIDGE_PID_DIR="$HOME/.claude/handoffs/bridges"

SESSION_NAME=$(python3 "$REGISTRY" whoami 2>/dev/null)
if [ -z "$SESSION_NAME" ] || [ "$SESSION_NAME" = "unregistered" ]; then
    exit 0
fi

# Kill any bridge processes for this session
if [ -d "$BRIDGE_PID_DIR" ]; then
    for pid_file in "$BRIDGE_PID_DIR"/*-"$SESSION_NAME".pid; do
        [ -f "$pid_file" ] || continue
        PID=$(cat "$pid_file")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null
        fi
        rm -f "$pid_file"
    done
fi
