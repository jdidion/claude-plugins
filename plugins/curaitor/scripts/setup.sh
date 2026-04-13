#!/usr/bin/env bash
# Setup script for curaitor workspaces
# Usage: bash scripts/setup.sh [review|triage|both]

set -e

CURAITOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="${1:-both}"

echo "curaitor setup (mode: $MODE)"
echo "  repo: $CURAITOR_DIR"

# Install Python dependencies
if ! python3 -c "import requests_oauthlib" 2>/dev/null; then
    echo "  Installing requests-oauthlib..."
    pip install requests-oauthlib
fi

if ! python3 -c "import yaml" 2>/dev/null; then
    echo "  Installing pyyaml..."
    pip install pyyaml
fi

# Check for .env
if [ ! -f "$CURAITOR_DIR/.env" ]; then
    if [ -f "$HOME/.instapaper-credentials" ]; then
        echo "  Copying ~/.instapaper-credentials to .env"
        cp "$HOME/.instapaper-credentials" "$CURAITOR_DIR/.env"
    else
        echo "  WARNING: No .env found. Copy .env.example to .env and fill in credentials."
    fi
fi

setup_workspace() {
    local name="$1"
    local dir="$HOME/projects/curaitor-$name"

    echo ""
    echo "  Setting up curaitor-$name..."
    mkdir -p "$dir/.claude/commands"

    # Symlink all commands
    for f in "$CURAITOR_DIR/.claude/commands"/cu:*.md; do
        local base=$(basename "$f")
        local target="$dir/.claude/commands/$base"
        if [ -L "$target" ]; then
            rm "$target"
        fi
        ln -s "$f" "$target"
    done

    # Copy .env if not present
    if [ ! -f "$dir/local-credentials.env" ] && [ -f "$CURAITOR_DIR/.env" ]; then
        cp "$CURAITOR_DIR/.env" "$dir/local-credentials.env"
        chmod 600 "$dir/local-credentials.env"
    fi

    # Create CLAUDE.md if not present
    if [ ! -f "$dir/CLAUDE.md" ]; then
        echo "  Creating default CLAUDE.md for $name mode"
        if [ "$name" = "triage" ]; then
            cat > "$dir/CLAUDE.md" << 'TRIAGE_EOF'
# curaitor-triage — Unattended Article Processing

You are running in unattended mode via cron. Do NOT prompt for user input — route uncertain articles to Review/ instead.

See $CURAITOR_DIR/CLAUDE.md for full documentation.
Run commands from $CURAITOR_DIR/ directory.
TRIAGE_EOF
        else
            cat > "$dir/CLAUDE.md" << 'REVIEW_EOF'
# curaitor-review — Interactive Article Review

See $CURAITOR_DIR/CLAUDE.md for full documentation.
Run commands from $CURAITOR_DIR/ directory.
REVIEW_EOF
        fi
    fi

    local count=$(ls "$dir/.claude/commands"/cu:*.md 2>/dev/null | wc -l | tr -d ' ')
    echo "  $count commands linked"
}

if [ "$MODE" = "review" ] || [ "$MODE" = "both" ]; then
    setup_workspace "review"
fi

if [ "$MODE" = "triage" ] || [ "$MODE" = "both" ]; then
    setup_workspace "triage"
fi

echo ""
echo "Done. To use:"
echo "  cd $CURAITOR_DIR && claude          # direct (recommended)"
echo "  cd $CURAITOR_DIR-review && claude    # interactive workspace"
echo "  cd $CURAITOR_DIR-triage && claude -p '/cu:triage' --permission-mode bypassPermissions"
