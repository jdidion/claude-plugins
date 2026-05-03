#!/usr/bin/env bash
# cron-wrapper.sh — wrap `claude -p /cu:<skill>` for cron so failure modes
# that would otherwise look like silent-tail "successful" runs are logged
# and acknowledged instead.
#
# Usage:
#   cron-wrapper.sh <log-path> <slash-command>
# Example:
#   cron-wrapper.sh ~/curaitor-discover.log /cu:discover
#
# Behavior:
#   - Runs `claude -p "<slash-command>" --permission-mode bypassPermissions`.
#   - Captures combined stdout+stderr.
#   - Two fingerprint-matched failure modes get an annotated log block and
#     exit 0 so cron doesn't surface them as run failures:
#       * "API Error ... Usage Policy"  → "## Cron refusal" block (hosted
#         classifier refused; the pre-Claude enqueue in the skills'
#         Step 3.6/3.7 protects the articles).
#       * "API Error ... Token is expired" (with optional preceding
#         "AWS auth refresh timed out" lines) → "## Cron auth-expired" block
#         (SSO session died and cron can't do interactive refresh).
#   - Otherwise passes through output and exit code.

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

# SSO token expiry fingerprint: "API Error" + "Token is expired" in output.
# Cron has no TTY for the interactive device-code refresh flow, so when the
# SSO session dies the skill produces this error and exits 0. Without this
# branch it looks like a healthy cron run that did zero work.
if grep -qiE 'API Error.*Token is expired' "$TMP"; then
    {
        printf '\n'
        printf '## Cron auth-expired at %s (skill=%s)\n' "$TS" "$SLASH"
        printf 'The SSO session expired and cron cannot run the interactive\n'
        printf 'refresh flow. Refresh the token in an interactive terminal:\n'
        printf '  aws sso login --profile <profile>\n'
        printf 'Then the next cron cycle will pick up where this one left off.\n'
        printf 'Output:\n\n'
        cat "$TMP"
        printf '\n'
    } >> "$LOG"
    # Exit 0 — same rationale as the refusal branch above. This is an
    # operational condition the user has to resolve manually; cron-level
    # retry won't help.
    exit 0
fi

# Normal path — append output and preserve exit code.
cat "$TMP" >> "$LOG"
exit "$CLAUDE_EXIT"
