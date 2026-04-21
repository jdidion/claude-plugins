#!/usr/bin/env bash
# Start the curaitor dashboard webapp and print its URL.
#
# Idempotent: if a server is already listening on the target port, reuses it.
# Otherwise launches `npm run dev` detached in CURAITOR_DIR and waits for readiness.
#
# No-op self-guard: if invoked from inside the curaitor webapp repo itself
# (e.g. a Claude session inside the dashboard's own container), just print the
# expected URL and exit — don't spawn a nested server inside a nested Claude
# inside the app that would own it.
#
# Usage:
#   bash scripts/dashboard.sh [--port N] [--dir PATH] [--no-open]
# Env:
#   CURAITOR_DIR — path to curaitor webapp repo (default: ~/projects/curaitor)
#   PORT         — dashboard port (default: 3141)

set -e

PORT="${PORT:-3141}"
CURAITOR_DIR="${CURAITOR_DIR:-$HOME/projects/curaitor}"
OPEN_BROWSER=1
READY_TIMEOUT=30
LOG="${CURAITOR_LOG:-$HOME/curaitor-dashboard.log}"
FORCE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --dir) CURAITOR_DIR="$2"; shift 2 ;;
        --no-open) OPEN_BROWSER=0; shift ;;
        --force) FORCE=1; shift ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
done

URL="http://localhost:$PORT"

# --- Self-guard: are we running inside the dashboard's own repo? ---
# Resolve both paths for comparison (follow symlinks, canonicalize).
canon() {
    if command -v realpath >/dev/null 2>&1; then
        realpath "$1" 2>/dev/null || echo "$1"
    else
        ( cd "$1" 2>/dev/null && pwd -P ) || echo "$1"
    fi
}
CANON_CWD="$(canon "$PWD")"
CANON_DIR="$(canon "$CURAITOR_DIR" 2>/dev/null || echo "$CURAITOR_DIR")"

is_inside_webapp() {
    # True if cwd is the webapp dir or any subdirectory of it.
    case "$CANON_CWD/" in
        "$CANON_DIR"/*|"$CANON_DIR"/) return 0 ;;
    esac
    # Also true if a parent marker file identifies this as the webapp repo.
    [ -f "./package.json" ] && grep -q '"name":[[:space:]]*"curaitor"' ./package.json 2>/dev/null && return 0
    return 1
}

if [ "$FORCE" -eq 0 ] && is_inside_webapp; then
    echo "inside curaitor webapp ($CANON_CWD) — not launching nested server" >&2
    echo "use --force to override, or run from outside the repo" >&2
    echo "$URL"
    exit 0
fi

is_listening() {
    # Prefer a cheap TCP probe; lsof fallback
    if command -v curl >/dev/null 2>&1; then
        curl -sfo /dev/null --max-time 1 "$URL/" 2>/dev/null
    else
        lsof -iTCP:"$PORT" -sTCP:LISTEN -P -n >/dev/null 2>&1
    fi
}

if is_listening; then
    echo "dashboard already running at $URL" >&2
else
    if [ ! -d "$CURAITOR_DIR" ]; then
        echo "CURAITOR_DIR not found: $CURAITOR_DIR" >&2
        echo "Set CURAITOR_DIR or clone https://github.com/jdidion/curaitor.git to ~/projects/curaitor" >&2
        exit 1
    fi
    if [ ! -f "$CURAITOR_DIR/package.json" ]; then
        echo "Not a node project (no package.json): $CURAITOR_DIR" >&2
        exit 1
    fi

    echo "starting dashboard in $CURAITOR_DIR (log: $LOG)" >&2
    ( cd "$CURAITOR_DIR" && PORT="$PORT" nohup npm run dev >> "$LOG" 2>&1 & )

    # Wait for readiness
    waited=0
    until is_listening; do
        if [ "$waited" -ge "$READY_TIMEOUT" ]; then
            echo "dashboard did not start within ${READY_TIMEOUT}s — check $LOG" >&2
            exit 1
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "dashboard ready at $URL (waited ${waited}s)" >&2
fi

if [ "$OPEN_BROWSER" -eq 1 ]; then
    # Prefer cmux browser when available; fall back to macOS `open`.
    if command -v cmux >/dev/null 2>&1; then
        cmux browser open "$URL" >/dev/null 2>&1 || open "$URL" 2>/dev/null || true
    else
        open "$URL" 2>/dev/null || xdg-open "$URL" 2>/dev/null || true
    fi
fi

echo "$URL"
