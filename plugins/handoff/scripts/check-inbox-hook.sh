#!/bin/bash
# Check for pending handoffs on each prompt submit.
# Lightweight — reads one JSON file, no network calls.

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(dirname "$(dirname "$0")")}"
REGISTRY="$PLUGIN_ROOT/scripts/registry.py"

# Get this session's name
SESSION_NAME=$(python3 "$REGISTRY" whoami 2>/dev/null)
if [ -z "$SESSION_NAME" ] || [ "$SESSION_NAME" = "unregistered" ]; then
    exit 0
fi

# Check inbox (ad-hoc handoffs)
INBOX_DIR="$HOME/.claude/handoffs/inbox/$SESSION_NAME"
if [ -d "$INBOX_DIR" ]; then
    HANDOFF_COUNT=$(find "$INBOX_DIR" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$HANDOFF_COUNT" -gt 0 ]; then
        echo "{\"systemMessage\": \"You have $HANDOFF_COUNT handoff(s) waiting. Run /handoff:inbox to check.\"}"
        exit 0
    fi
fi

# Check team inboxes
TEAMS_DIR="$HOME/.claude/teams"
if [ -d "$TEAMS_DIR" ]; then
    for inbox_file in "$TEAMS_DIR"/*/inboxes/"$SESSION_NAME".json; do
        [ -f "$inbox_file" ] || continue
        UNREAD=$(python3 -c "
import json, sys
try:
    msgs = json.load(open('$inbox_file'))
    unread = [m for m in msgs if not m.get('read')]
    if unread:
        print(len(unread))
except:
    pass
" 2>/dev/null)
        if [ -n "$UNREAD" ] && [ "$UNREAD" -gt 0 ]; then
            TEAM_NAME=$(basename "$(dirname "$(dirname "$inbox_file")")")
            echo "{\"systemMessage\": \"Team '$TEAM_NAME': $UNREAD unread message(s). Run /handoff:bridge $TEAM_NAME $SESSION_NAME to connect.\"}"
            exit 0
        fi
    done
fi
