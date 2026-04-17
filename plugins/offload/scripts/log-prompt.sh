#!/bin/bash
# UserPromptSubmit hook: append user prompt to JSONL log.
# Only runs when prompt logging is enabled in config.
set -euo pipefail

INPUT=$(cat)

# Resolve data dir: plugin var > default
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/offload}"
CONFIG="$DATA_DIR/config.json"

# Check opt-in
[ -f "$CONFIG" ] || exit 0
ENABLED=$(jq -r '.prompt_logging // false' "$CONFIG" 2>/dev/null || echo "false")
[ "$ENABLED" = "true" ] || exit 0

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null)
CWD=$(echo "$INPUT" | jq -r '.cwd // ""' 2>/dev/null)
PROJECT=$(basename "$CWD" 2>/dev/null || echo "unknown")

# Extract prompt text — handle both string and object shapes
PROMPT=$(echo "$INPUT" | jq -r '
  if .prompt | type == "string" then .prompt
  elif .prompt.content | type == "string" then .prompt.content
  elif .prompt.content | type == "array" then [.prompt.content[] | .text // empty] | join("\n")
  else .prompt | tostring
  end // ""' 2>/dev/null || echo "")

[ -z "$PROMPT" ] && exit 0

mkdir -p "$DATA_DIR"
LOG="$DATA_DIR/prompts.jsonl"

jq -nc \
  --arg ts "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  --arg sid "$SESSION_ID" \
  --arg cwd "$CWD" \
  --arg project "$PROJECT" \
  --arg prompt "$PROMPT" \
  '{ts: $ts, sid: $sid, cwd: $cwd, project: $project, prompt: $prompt}' \
  >> "$LOG"

exit 0
