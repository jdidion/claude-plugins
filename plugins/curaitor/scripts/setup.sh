#!/usr/bin/env bash
# Setup script for curaitor workspaces
# Usage:
#   bash scripts/setup.sh [review|triage|both] [--local-triage[=MODEL]]
#
# Positional first arg selects which workspace(s) to set up (default: both).
# --local-triage installs Ollama + the default model (huihui_ai/gemma-4-abliterated:e4b)
# and enables the local_triage block in user-settings.yaml. Safe to re-run.

set -e

CURAITOR_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODE="both"
ENABLE_LOCAL_TRIAGE=0
LOCAL_TRIAGE_MODEL="huihui_ai/gemma-4-abliterated:e4b"

for arg in "$@"; do
    case "$arg" in
        review|triage|both) MODE="$arg" ;;
        --local-triage) ENABLE_LOCAL_TRIAGE=1 ;;
        --local-triage=*) ENABLE_LOCAL_TRIAGE=1; LOCAL_TRIAGE_MODEL="${arg#*=}" ;;
        -h|--help)
            sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

echo "curaitor setup (mode: $MODE, local_triage=$ENABLE_LOCAL_TRIAGE)"
echo "  repo: $CURAITOR_DIR"

# Install Python dependencies
if [ -f "$CURAITOR_DIR/requirements.txt" ]; then
    echo "  Installing Python dependencies from requirements.txt..."
    pip install -r "$CURAITOR_DIR/requirements.txt"
else
    # Fallback for older checkouts without requirements.txt
    if ! python3 -c "import requests_oauthlib" 2>/dev/null; then
        echo "  Installing requests-oauthlib..."
        pip install requests-oauthlib
    fi
    if ! python3 -c "import yaml" 2>/dev/null; then
        echo "  Installing pyyaml..."
        pip install pyyaml
    fi
    if ! python3 -c "import certifi" 2>/dev/null; then
        echo "  Installing certifi..."
        pip install certifi
    fi
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

# Optional: install Ollama + local-triage model, enable in user-settings.yaml
if [ "$ENABLE_LOCAL_TRIAGE" -eq 1 ]; then
    echo ""
    echo "  Setting up local triage (model: $LOCAL_TRIAGE_MODEL)..."

    if ! command -v ollama >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            echo "  Installing Ollama via Homebrew..."
            brew install ollama
        else
            echo "  ERROR: ollama not found and brew unavailable." >&2
            echo "  Install from https://ollama.com/download and re-run." >&2
            exit 1
        fi
    fi

    # Start ollama in the background if not already listening
    if ! curl -sfo /dev/null --max-time 1 http://localhost:11434/ 2>/dev/null; then
        echo "  Starting ollama daemon..."
        (ollama serve >/tmp/ollama-setup.log 2>&1 &)
        for i in 1 2 3 4 5 6 7 8 9 10; do
            sleep 1
            if curl -sfo /dev/null --max-time 1 http://localhost:11434/ 2>/dev/null; then break; fi
        done
    fi

    # Pull the model (idempotent — ollama skips if already local)
    echo "  Pulling $LOCAL_TRIAGE_MODEL (this may take a while on first install)..."
    ollama pull "$LOCAL_TRIAGE_MODEL"

    # Enable in user-settings.yaml
    settings="$CURAITOR_DIR/config/user-settings.yaml"
    if [ ! -f "$settings" ]; then
        cp "$CURAITOR_DIR/config/user-settings.yaml.example" "$settings"
        echo "  Created $settings from example"
    fi
    if grep -q "^local_triage:" "$settings"; then
        # Toggle enabled to true, update model
        python3 - <<PY
import yaml, pathlib
p = pathlib.Path("$settings")
data = yaml.safe_load(p.read_text()) or {}
data.setdefault('local_triage', {})
data['local_triage']['enabled'] = True
data['local_triage']['model'] = "$LOCAL_TRIAGE_MODEL"
data['local_triage'].setdefault('ollama_host', 'http://localhost:11434')
data['local_triage'].setdefault('escalation_mode', 'strict')
p.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True))
print(f'  Enabled local_triage in {p}')
PY
    else
        cat >> "$settings" <<YAML

local_triage:
  enabled: true
  model: $LOCAL_TRIAGE_MODEL
  ollama_host: http://localhost:11434
  escalation_mode: strict
YAML
        echo "  Appended local_triage block to $settings"
    fi

    echo "  Local triage enabled. Smoke-test with:"
    echo "    echo '[{\"title\":\"A plant genome paper\",\"url\":\"x\",\"source\":\"rss\",\"summary\":\"Arabidopsis...\"}]' | python3 $CURAITOR_DIR/scripts/local-triage.py"
fi

echo ""
echo "Done. To use:"
echo "  cd $CURAITOR_DIR && claude          # direct (recommended)"
echo "  cd $CURAITOR_DIR-review && claude    # interactive workspace"
echo "  cd $CURAITOR_DIR-triage && claude -p '/cu:triage' --permission-mode bypassPermissions"
if [ "$ENABLE_LOCAL_TRIAGE" -eq 0 ]; then
    echo ""
    echo "  Optional: enable local-model first-round triage with:"
    echo "    bash scripts/setup.sh --local-triage"
fi
