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
SKIP_PATH_SETUP=0

for arg in "$@"; do
    case "$arg" in
        review|triage|both) MODE="$arg" ;;
        --local-triage) ENABLE_LOCAL_TRIAGE=1 ;;
        --local-triage=*) ENABLE_LOCAL_TRIAGE=1; LOCAL_TRIAGE_MODEL="${arg#*=}" ;;
        --no-path-setup) SKIP_PATH_SETUP=1 ;;
        -h|--help)
            sed -n '2,8p' "$0"; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

echo "curaitor setup (mode: $MODE, local_triage=$ENABLE_LOCAL_TRIAGE)"
echo "  repo: $CURAITOR_DIR"

# Discover a python3 with pip that we can use for installs and for the
# ~/.curaitor/bin/python3 symlink (so `#!/usr/bin/env python3` scripts resolve
# to an interpreter that has the curaitor deps). Prefers homebrew over pixi,
# which often ships without pip.
discover_python() {
    for py in /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3 python3; do
        if command -v "$py" >/dev/null 2>&1 && "$py" -m pip --version >/dev/null 2>&1; then
            echo "$py"
            return 0
        fi
    done
    return 1
}

INSTALL_PY="$(discover_python || true)"
if [ -z "$INSTALL_PY" ]; then
    echo "  ERROR: no python3 with pip found. Install Python 3 (brew install python) and re-run." >&2
    exit 1
fi
echo "  Using $INSTALL_PY for dependency install"

# Symlink the discovered python into ~/.curaitor/bin/python3 so scripts with
# `#!/usr/bin/env python3` shebangs resolve to the right interpreter without
# per-invocation `eval` wrappers. User can override by replacing the symlink,
# or disable shell-rc edits with --no-path-setup.
setup_python_path() {
    local py="$INSTALL_PY"
    local bindir="$HOME/.curaitor/bin"
    mkdir -p "$bindir"
    local link="$bindir/python3"
    if [ -L "$link" ] && [ "$(readlink "$link")" = "$py" ]; then
        echo "  Python symlink already points at $py"
    else
        ln -sfn "$py" "$link"
        echo "  Linked $link → $py"
    fi

    # Pick the user's interactive shell rc
    local rc=""
    case "$(basename "${SHELL:-}")" in
        zsh)  rc="$HOME/.zshrc" ;;
        bash) [ -f "$HOME/.bash_profile" ] && rc="$HOME/.bash_profile" || rc="$HOME/.bashrc" ;;
        *)    echo "  Unknown shell $SHELL — add '$bindir' to PATH manually."; return ;;
    esac

    # Idempotent: skip if already on PATH or already in rc
    case ":$PATH:" in *":$bindir:"*) echo "  $bindir already on PATH"; return ;; esac
    if [ -f "$rc" ] && grep -Fq ".curaitor/bin" "$rc"; then
        echo "  $rc already references .curaitor/bin (new shells will pick it up)"
        return
    fi

    if [ "$SKIP_PATH_SETUP" -eq 1 ]; then
        echo "  --no-path-setup given; add this to $rc manually:"
        echo "    export PATH=\"\$HOME/.curaitor/bin:\$PATH\""
        return
    fi

    if [ ! -t 0 ]; then
        echo "  Non-interactive run; skipping $rc edit. Add this line manually:"
        echo "    export PATH=\"\$HOME/.curaitor/bin:\$PATH\""
        return
    fi

    printf "  Append 'export PATH=\"\$HOME/.curaitor/bin:\$PATH\"' to %s? [y/N] " "$rc"
    read -r reply
    case "$reply" in
        y|Y|yes|YES)
            printf '\n# curaitor: prefer discovered python3 (added by plugins/curaitor/scripts/setup.sh)\nexport PATH="$HOME/.curaitor/bin:$PATH"\n' >> "$rc"
            echo "  Appended PATH export to $rc — restart your shell or run: source $rc"
            ;;
        *)
            echo "  Skipped. Add this to $rc manually when ready:"
            echo "    export PATH=\"\$HOME/.curaitor/bin:\$PATH\""
            ;;
    esac
}

# Install Python dependencies against the discovered interpreter.
# Homebrew's python3 is PEP-668 "externally managed" — pass --break-system-packages
# when we actually need to install. Skip pip entirely if deps are already satisfied.
pip_install() {
    # Adds --break-system-packages on homebrew pythons; harmless on others via pip ≥23.0.1
    "$INSTALL_PY" -m pip install --break-system-packages "$@" 2>/dev/null \
        || "$INSTALL_PY" -m pip install "$@"
}

if "$INSTALL_PY" -c "import requests_oauthlib, yaml, certifi" 2>/dev/null; then
    echo "  Python dependencies already satisfied"
elif [ -f "$CURAITOR_DIR/requirements.txt" ]; then
    echo "  Installing Python dependencies from requirements.txt..."
    pip_install -r "$CURAITOR_DIR/requirements.txt"
else
    # Fallback for older checkouts without requirements.txt
    "$INSTALL_PY" -c "import requests_oauthlib" 2>/dev/null || { echo "  Installing requests-oauthlib..."; pip_install requests-oauthlib; }
    "$INSTALL_PY" -c "import yaml" 2>/dev/null || { echo "  Installing pyyaml..."; pip_install pyyaml; }
    "$INSTALL_PY" -c "import certifi" 2>/dev/null || { echo "  Installing certifi..."; pip_install certifi; }
fi

setup_python_path

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
    mkdir -p "$dir/.claude/skills"

    # Clean up legacy layouts:
    #   - older setup.sh versions linked $CURAITOR_DIR/.claude/commands/cu:*.md
    #     into $dir/.claude/commands/; that source dir is gone.
    #   - the cu:NAME skill layout was renamed to bare NAME (PR for plugin
    #     v0.5.0). Drop any surviving cu:* symlinks under .claude/skills/.
    if [ -d "$dir/.claude/commands" ]; then
        find "$dir/.claude/commands" -maxdepth 1 -name 'cu:*' -type l -delete 2>/dev/null || true
        rmdir "$dir/.claude/commands" 2>/dev/null || true
    fi
    find "$dir/.claude/skills" -maxdepth 1 -name 'cu:*' -type l -delete 2>/dev/null || true

    # Symlink each skill directory (plugin layout: skills/NAME/SKILL.md)
    for skill_dir in "$CURAITOR_DIR/skills"/*; do
        [ -d "$skill_dir" ] || continue
        local base=$(basename "$skill_dir")
        local target="$dir/.claude/skills/$base"
        if [ -L "$target" ]; then
            rm "$target"
        elif [ -e "$target" ]; then
            echo "  WARNING: $target exists and is not a symlink; skipping"
            continue
        fi
        ln -s "$skill_dir" "$target"
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

    local count=$(find "$dir/.claude/skills" -maxdepth 1 -type l 2>/dev/null | wc -l | tr -d ' ')
    echo "  $count skills linked"
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
        "$INSTALL_PY" - <<PY
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
echo "  cd $CURAITOR_DIR-triage && claude -p '/curaitor:triage' --permission-mode bypassPermissions"
if [ "$ENABLE_LOCAL_TRIAGE" -eq 0 ]; then
    echo ""
    echo "  Optional: enable local-model first-round triage with:"
    echo "    bash scripts/setup.sh --local-triage"
fi
