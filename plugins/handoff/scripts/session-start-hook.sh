#!/bin/bash
# Auto-register this session and optionally start the inbox bridge.
# Runs on SessionStart via plugin hooks.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
REGISTRY="$PLUGIN_ROOT/scripts/registry.py"

# Auto-register using cwd basename
python3 "$REGISTRY" auto-register 2>/dev/null

# Output a system message confirming registration
SESSION_NAME=$(python3 "$REGISTRY" whoami 2>/dev/null)
if [ -n "$SESSION_NAME" ] && [ "$SESSION_NAME" != "unregistered" ]; then
    echo "{\"systemMessage\": \"Handoff: registered as '$SESSION_NAME'\"}"
fi
