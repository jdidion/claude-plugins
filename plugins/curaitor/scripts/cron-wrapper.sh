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
#   - Pre-flight probes `/opt/homebrew/bin/node --version` (since Claude
#     Code is a Node app and cron's PATH picks up Homebrew node). If the
#     probe fails with a known `libllhttp.9.3.dylib` dyld mismatch and the
#     9.3.1 keg is still on disk, repoint `/opt/homebrew/opt/llhttp` to
#     the 9.3.1 Cellar directory and re-probe. Probe failures that aren't
#     auto-heal-able get a "## Cron pre-flight failed" block and exit 0.
#   - Logs `node --version` + the llhttp dylib `node` is linked against
#     at run start, so future dyld mismatches are diagnosable in one grep.
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
#   - If curaitor's local-triage backend is `omlx` AND no oMLX server is
#     reachable at /health, start `omlx serve` in the background before
#     calling Claude and stop it afterward. Interactive sessions that
#     already have oMLX running are left untouched. This keeps the 14+GB
#     Gemma model out of memory except during the cron window.
#   - Otherwise passes through output and exit code.

set -o pipefail

LOG="${1:?missing log path}"
SLASH="${2:?missing slash command}"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

mkdir -p "$(dirname "$LOG")"

# Capture output to a temp file so we can inspect before appending.
TMP="$(mktemp -t curaitor-cron.XXXXXX)"

# Signal cron context so the skills' pre-Claude enqueue step (Step 3.6
# in cu:discover, Step 3.7 in cu:triage) writes escalations to the
# level-2 pending queue BEFORE calling Claude. Without this, a hosted
# classifier refusal (or any mid-run failure) silently drops the day's
# articles — they never reach Obsidian and never reach the queue.
export CURAITOR_CRON=1

# --- node pre-flight (self-heal llhttp dylib mismatch) ---
#
# Claude Code is a Node app; cron's PATH puts `/opt/homebrew/bin` before
# anything pixi-managed, so cron actually invokes Homebrew node. When
# Homebrew upgrades llhttp past the major version node was compiled
# against (observed 2026-05-04: node 25.8.1_1 wants libllhttp.9.3.dylib,
# /opt/homebrew/opt/llhttp → 9.4.1 which doesn't ship the 9.3 symlink),
# node dies on startup with a dyld error and cron silently fails.
#
# Symptoms look identical to a successful-but-empty run: empty log
# output, exit 0, no "API Error" for the refusal/token-expired
# fingerprint matcher to catch. This block probes + self-heals.
NODE_BIN="/opt/homebrew/bin/node"

_node_works() {
    # Discard stderr because the dyld error is long and we log it
    # separately only when the probe fails.
    "$NODE_BIN" --version >/dev/null 2>&1
}

_try_heal_llhttp() {
    # If node's error mentions a specific libllhttp.X.Y.dylib and that
    # keg still exists in Cellar, repoint /opt/homebrew/opt/llhttp to
    # that version. Only runs when probe has already failed — safe to
    # do nothing if the shapes don't match.
    local err needed target keg
    err="$("$NODE_BIN" --version 2>&1 || true)"
    # Expected line: 'Library not loaded: /opt/homebrew/opt/llhttp/lib/libllhttp.9.3.dylib'
    needed=$(printf '%s' "$err" | sed -nE 's|.*/libllhttp\.([0-9]+\.[0-9]+)\.dylib.*|\1|p' | head -1)
    [ -n "$needed" ] || return 1
    # Cellar dirs are named with patch versions (e.g., 9.3.1), but the
    # dylib compat version is major.minor — pick any matching keg.
    keg=$(ls -d "/opt/homebrew/Cellar/llhttp/${needed}."* 2>/dev/null | sort -V | tail -1)
    [ -n "$keg" ] && [ -d "$keg" ] || return 1
    target="../Cellar/llhttp/$(basename "$keg")"
    # Sanity: the dylib file itself must exist in the keg.
    [ -f "$keg/lib/libllhttp.${needed}.dylib" ] || return 1
    ln -sfn "$target" /opt/homebrew/opt/llhttp 2>/dev/null || return 1
    return 0
}

if ! _node_works; then
    if _try_heal_llhttp && _node_works; then
        # Self-heal succeeded; record it so the user sees the fix in the log.
        {
            printf '\n## Cron node self-heal at %s (skill=%s)\n' "$TS" "$SLASH"
            printf 'Repointed /opt/homebrew/opt/llhttp to a compatible keg so\n'
            printf 'node --version succeeds. This is a durable fix until the\n'
            printf 'next `brew upgrade llhttp` — consider `brew reinstall node`\n'
            printf 'to relink node against the current llhttp major.\n'
        } >> "$LOG"
    else
        # Can't heal — log the error and exit 0 so cron doesn't mark this
        # as a transient failure. The next interactive session can look
        # at the log, run `brew reinstall node` or the `ln -sfn` pin, and
        # the next cron cycle will pick up the fix.
        {
            printf '\n## Cron pre-flight failed at %s (skill=%s)\n' "$TS" "$SLASH"
            printf 'Homebrew node is broken — Claude Code will not run.\n'
            printf 'Common cause: llhttp dylib mismatch after a brew upgrade.\n'
            printf 'Diagnose with:\n'
            printf '  %s --version\n' "$NODE_BIN"
            printf '  otool -L %s | grep llhttp\n' "$NODE_BIN"
            printf '  ls -l /opt/homebrew/opt/llhttp\n'
            printf 'Fix with either:\n'
            printf '  brew reinstall node  # durable\n'
            printf '  ln -sfn ../Cellar/llhttp/<matching-keg> /opt/homebrew/opt/llhttp\n'
            printf '\n--- node --version output ---\n'
            "$NODE_BIN" --version 2>&1 || true
            printf '\n'
        } >> "$LOG"
        exit 0
    fi
fi

# Telemetry: record node version + the llhttp dylib node is linked
# against so future dyld mismatches are visible in a single grep of the
# log. Cheap (~50ms) and runs on every successful cron fire.
{
    printf '\n## Cron run %s (skill=%s)\n' "$TS" "$SLASH"
    printf 'node: %s\n' "$("$NODE_BIN" --version 2>/dev/null)"
    printf 'llhttp link: %s\n' "$(otool -L "$NODE_BIN" 2>/dev/null | awk '/libllhttp/ {print $1; exit}')"
} >> "$LOG"

# --- oMLX lifecycle (if curaitor is configured to use it) ---
#
# We only care about oMLX for this run. If curaitor's local-triage
# backend is not oMLX, skip the whole block — cheap no-op for Ollama
# users. If oMLX is already serving (interactive session left it up),
# leave it alone. Only when WE started the process do we stop it in
# the exit trap.
OMLX_STARTED_BY_US=0
OMLX_PID=
OMLX_LOG=
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SETTINGS="$SCRIPT_DIR/../config/user-settings.yaml"

_backend_is_omlx() {
    # Env override wins; otherwise inspect user-settings.yaml. Emit the
    # resolved backend on stdout ("omlx" or anything else).
    if [ -n "$CURAITOR_LOCAL_BACKEND" ]; then
        printf '%s\n' "$CURAITOR_LOCAL_BACKEND"
        return
    fi
    # Use a minimal yaml parser to avoid a python dep on pyyaml here.
    # `local_triage.backend` lives under the top-level key; we grep it
    # out of a shallow scan, ignoring comments.
    awk '
        /^local_triage:/ {in_block=1; next}
        /^[^[:space:]]/ {in_block=0}
        in_block && /^[[:space:]]+backend:/ {
            sub(/^[[:space:]]+backend:[[:space:]]*/, "")
            sub(/#.*/, "")
            gsub(/[[:space:]"'"'"']/, "")
            print
            exit
        }
    ' "$SETTINGS" 2>/dev/null
}

_omlx_healthy() {
    # 2s connect timeout + 3s total — plenty for a local port check.
    curl -s --max-time 3 --connect-timeout 2 \
        -o /dev/null -w '%{http_code}' \
        http://127.0.0.1:8000/health 2>/dev/null | grep -q '^200$'
}

_start_omlx() {
    # Background the server, capture its PID, wait up to 60s for /health.
    OMLX_LOG="$(mktemp -t curaitor-omlx.XXXXXX).log"
    # nohup + disown keeps it alive even if this shell dies on SIGKILL.
    nohup omlx serve > "$OMLX_LOG" 2>&1 &
    OMLX_PID=$!
    disown "$OMLX_PID" 2>/dev/null || true
    # Poll health for up to 60s — first model load after a cold fork
    # is typically ~15-25s, leave headroom.
    for _ in $(seq 1 60); do
        if _omlx_healthy; then
            OMLX_STARTED_BY_US=1
            return 0
        fi
        sleep 1
    done
    # Didn't come up. Kill the zombie and give up on oMLX — the shared
    # client will hit a connection error and fall back to escalating
    # articles to Claude (same behavior as Ollama-down).
    if kill -0 "$OMLX_PID" 2>/dev/null; then
        kill "$OMLX_PID" 2>/dev/null || true
    fi
    return 1
}

_stop_omlx() {
    # Only stop if WE started it.
    [ "$OMLX_STARTED_BY_US" = "1" ] || return 0
    [ -n "$OMLX_PID" ] || return 0
    if kill -0 "$OMLX_PID" 2>/dev/null; then
        # Graceful TERM first, then KILL after 5s if it's stubborn.
        kill -TERM "$OMLX_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
            kill -0 "$OMLX_PID" 2>/dev/null || break
            sleep 1
        done
        kill -KILL "$OMLX_PID" 2>/dev/null || true
    fi
}

# Unified exit handler: always stop oMLX (if we started it) and clean up.
trap '_stop_omlx; rm -f "$TMP" "$OMLX_LOG"' EXIT

BACKEND="$(_backend_is_omlx)"
if [ "$BACKEND" = "omlx" ]; then
    if ! _omlx_healthy; then
        if ! _start_omlx; then
            {
                printf '\n## Cron oMLX-start-failed at %s (skill=%s)\n' "$TS" "$SLASH"
                printf 'oMLX was not running and `omlx serve` did not become healthy within 60s.\n'
                printf 'Articles will escalate to Claude without the local pre-pass.\n'
                if [ -n "$OMLX_LOG" ] && [ -s "$OMLX_LOG" ]; then
                    printf '\n--- omlx serve output (last 40 lines) ---\n'
                    tail -40 "$OMLX_LOG" 2>/dev/null || true
                fi
                printf '\n'
            } >> "$LOG"
            # Don't fail the whole run — the Claude fallback is still the
            # correct behavior. Continue to `claude -p`.
        fi
    fi
fi

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
