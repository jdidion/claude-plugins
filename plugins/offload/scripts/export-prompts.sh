#!/bin/bash
# Export prompt log with optional filters.
# Usage: export-prompts.sh [--project NAME] [--since DATE] [--session SID] [--format jsonl|csv|markdown]
set -euo pipefail

DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/offload}"
LOG="$DATA_DIR/prompts.jsonl"

if [ ! -f "$LOG" ]; then
  echo "No prompt log found at $LOG"
  exit 0
fi

PROJECT=""
SINCE=""
SESSION=""
FORMAT="jsonl"

while [ $# -gt 0 ]; do
  case "$1" in
    --project)  PROJECT="$2"; shift 2 ;;
    --since)    SINCE="$2"; shift 2 ;;
    --session)  SESSION="$2"; shift 2 ;;
    --format)   FORMAT="$2"; shift 2 ;;
    *)          shift ;;
  esac
done

FILTER="."
[ -n "$PROJECT" ] && FILTER="$FILTER | select(.project == \"$PROJECT\")"
[ -n "$SESSION" ] && FILTER="$FILTER | select(.sid == \"$SESSION\")"
[ -n "$SINCE" ] && FILTER="$FILTER | select(.ts >= \"$SINCE\")"

case "$FORMAT" in
  jsonl)
    jq -c "$FILTER" "$LOG"
    ;;
  csv)
    echo "timestamp,session_id,project,prompt"
    jq -r "$FILTER | [.ts, .sid, .project, (.prompt | gsub(\"[\\n\\r]\"; \" \") | gsub(\"\\\"\"; \"\\\\\\\"\"  ))] | @csv" "$LOG"
    ;;
  markdown)
    jq -r "$FILTER | \"| \\(.ts) | \\(.project) | \\(.prompt | gsub(\"[\\n\\r]\"; \" \") | .[0:120]) |\"" "$LOG" | \
      { echo "| Timestamp | Project | Prompt |"; echo "|-----------|---------|--------|"; cat; }
    ;;
  *)
    echo "Unknown format: $FORMAT (use jsonl, csv, or markdown)"
    exit 1
    ;;
esac
