#!/usr/bin/env bash
# cron-wrapper.sh — wrap `claude -p /cu:<skill>` for cron so a classifier
# refusal (stop_reason=refusal, emitted as "API Error: ...Usage Policy...")
# is logged and acknowledged rather than left as a silent-tail failure.
#
# Usage:
#   cron-wrapper.sh <log-path> <slash-command>
# Example:
#   cron-wrapper.sh ~/curaitor-discover.log /cu:discover
#
# Behavior:
#   - Runs `claude -p "<slash-command>" --permission-mode bypassPermissions`.
#   - Captures combined stdout+stderr.
#   - If the output matches the safety-refusal fingerprint, writes a compact
#     "## Cron refusal" block to the log with timestamp + hint and exits 0
#     so the cron line doesn't mark the run as failed.
#   - Otherwise passes through the output and exit code.

set -o pipefail

LOG="${1:?missing log path}"
SLASH="${2:?missing slash command}"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$(dirname "$LOG")"

# Capture output to a temp file so we can inspect before appending.
TMP="$(mktemp -t curaitor-cron.XXXXXX)"
trap 'rm -f "$TMP"' EXIT

# Signal cron context so the skills' pre-Claude enqueue step (Step 3.6
# in cu:discover, Step 3.7 in cu:triage) writes escalations to the
# level-2 pending queue BEFORE calling Claude. Without this, a hosted
# classifier refusal (or any mid-run failure) silently drops the day's
# articles — they never reach Obsidian and never reach the queue.
export CURAITOR_CRON=1

claude -p "$SLASH" --permission-mode bypassPermissions > "$TMP" 2>&1
CLAUDE_EXIT=$?

# Classifier-refusal fingerprint: "API Error" + "Usage Policy" in output.
if grep -qiE 'API Error.*Usage Policy' "$TMP"; then
    # Check the level-2 queue depth so we can report whether the
    # pre-Claude enqueue step captured the run's articles or not.
    PENDING=$(python3 "$(dirname "$0")/level2-queue.py" status 2>/dev/null | \
        python3 -c 'import json,sys; print(json.load(sys.stdin).get("pending","?"))' 2>/dev/null || echo '?')
    {
        printf '\n'
        printf '## Cron refusal at %s (skill=%s)\n' "$TS" "$SLASH"
        printf 'The hosted-model safety classifier refused to respond.\n'
        printf 'Level-2 pending queue depth after run: %s\n' "$PENDING"
        printf 'Drain in the next interactive session with:\n'
        printf '  python3 scripts/level2-queue.py peek   # inspect\n'
        printf '  python3 scripts/level2-queue.py drain  # consume + clear\n'
        printf 'Output:\n\n'
        cat "$TMP"
        printf '\n'
    } >> "$LOG"
    # Intentionally exit 0 — this is an expected-failure mode, not a bug
    # in the cron invocation. The run is logged; next cycle will retry.
    exit 0
fi

# Normal path — append output and preserve exit code.
cat "$TMP" >> "$LOG"
exit "$CLAUDE_EXIT"
