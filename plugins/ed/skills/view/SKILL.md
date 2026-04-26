---
name: view
description: Open a file in a viewer in an adjacent cmux surface. Default viewer comes from config/env (ladder below), falling back to the editor if no viewer is configured. Use when the user asks to view, preview, or read a file. --live picks the live-reload viewer variant when one is configured. Other trailing flags are passed through to the viewer.
---

# /ed:view — Open a file in a viewer in an adjacent cmux surface

Opens a file in a cmux terminal surface using the viewer configured for that file's extension. If no viewer applies, falls back to the editor. Orientation-aware splits.

## Arguments

`$ARGUMENTS` — `[path] [--live] [--watch] [<other viewer flags>]`

- **`path`** — file to view. If omitted, resolve to the most recently mentioned local file path from the current conversation.
- **`--live`** — use the `viewer_live` variant from config for this extension, if defined. Otherwise it's passed through as a regular flag to the viewer command.
- **`--watch`** and other flags — passed through verbatim to the viewer after the path.

## Step 1: Parse arguments and resolve path

1. Split `$ARGUMENTS`. Classify tokens as flags (`--foo`) or path.
2. Set `LIVE=1` if `--live` appears. Leave the flag in `$EXTRA_ARGS` anyway; passing `--live` through is harmless if the viewer doesn't recognize it, and lets users chain it into watch-mode viewers that expect it.
3. If no path provided, scan the conversation (most recent first) for a local file that exists.
4. If nothing resolves, ask the user. Do not guess.

Report the resolved path, viewer command, and extras in one line.

## Step 2: Resolve the viewer command

```bash
RESOLVED=$("$CLAUDE_PLUGIN_ROOT/scripts/resolve.py" view "$RESOLVED_PATH" ${LIVE:+--live} --provenance 2>/tmp/ed-view-prov.$$)
PROVENANCE=$(cat /tmp/ed-view-prov.$$ 2>/dev/null); rm -f /tmp/ed-view-prov.$$
```

`$RESOLVED` is the command; `$PROVENANCE` names where it came from (config key, env var, or `fallback (less)`).

Resolution ladder (inside `resolve.py`): `extensions.<ext>.viewer_live` (if `--live`) → `extensions.<ext>.viewer` → `defaults.viewer` → `$VIEWER` → `$ED_DEFAULT_VIEWER` → `less`.

**Editor fallback**: if the resolved viewer is the bare `less` fallback AND the file's extension doesn't have any viewer-shaped config/env set, prefer the user's editor instead (so `/ed:view script.py` opens `$EDITOR script.py` rather than paging Python source):

```bash
if [ "$PROVENANCE" = "fallback (less)" ]; then
    EDITOR_CMD=$("$CLAUDE_PLUGIN_ROOT/scripts/resolve.py" edit "$RESOLVED_PATH")
    VIEWER_CMD="$EDITOR_CMD"
    PROVENANCE="editor fallback"
else
    VIEWER_CMD="$RESOLVED"
fi

BIN=$(echo "$VIEWER_CMD" | awk '{print $1}')
command -v "$BIN" >/dev/null || { echo "viewer not on PATH: $BIN"; exit 1; }
```

## Step 3: Find or create the viewer surface

Use the same workspace-surface helper and orientation rule as `/ed:edit`:

```bash
ws_surfaces() {
    cmux tree --workspace "$CMUX_WORKSPACE_ID" \
        | grep -oE 'surface:[0-9]+' \
        | sort -u
}

ORIENT="${ED_MONITOR:-${CURAITOR_MONITOR:-horizontal}}"
if [ "$ORIENT" = "vertical" ]; then
    VIEWER_DIR=down
else
    VIEWER_DIR=right
fi

BEFORE=$(ws_surfaces)
cmux new-split "$VIEWER_DIR" --surface "$CMUX_SURFACE_ID"
AFTER=$(ws_surfaces)
VIEWER_SURFACE=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)
```

**Critical**: use `cmux new-split <dir> --surface <ref>`, not `cmux new-pane` — `new-pane` ignores `--surface` and splits the focused pane.

## Step 4: Launch the viewer

```bash
CMD="$VIEWER_CMD '$RESOLVED_PATH'"
[ -n "$EXTRA_ARGS" ] && CMD="$CMD $EXTRA_ARGS"

cmux send --surface "$VIEWER_SURFACE" "$CMD"
cmux send-key --surface "$VIEWER_SURFACE" Enter
cmux rename-tab --surface "$VIEWER_SURFACE" "view: $(basename "$RESOLVED_PATH")"
```

## Step 5: Report

One line:

```
Viewing <basename> via <viewer-bin> (<provenance>, <extras if any>) on <surface-ref>
```

## Rules

- Do not auto-focus the viewer surface.
- Use `/ed:edit` for editing. `/ed:view` is read-only by convention; whether the resolved binary is actually read-only is up to the user's config.
- `--live` only affects viewer resolution when a `viewer_live` entry exists; otherwise it's a passthrough flag to the viewer.
