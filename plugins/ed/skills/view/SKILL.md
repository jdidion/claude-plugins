---
name: view
description: Open a file in a viewer in an adjacent cmux surface. Uses the viewer configured for the file's extension, or the default viewer, or falls back to the editor in read-only mode. Use when the user asks to view, preview, or read a file. --live picks the live-reload viewer variant when one is configured. Other trailing flags are passed through to the viewer.
---

# /ed:view — View a file in an adjacent cmux surface

Opens a file in a single cmux terminal surface using the configured viewer. When no viewer is configured anywhere, falls back to the editor in read-only mode (if the editor has one).

## Arguments

`$ARGUMENTS` — `[path] [--live] [<passthrough-flags>]`

- `path` — file to view. If omitted, resolve to the most recently mentioned local file path in the conversation.
- `--live` — prefer the `viewer_live` variant from config for this extension. Always passed through to the resolved command too (harmless if the viewer doesn't recognize it).
- Other tokens — passed through verbatim after the path.

## Step 1: Parse arguments and resolve path

1. Tokenize `$ARGUMENTS`. Classify as flag or path.
2. Set `LIVE=1` if `--live` is present. Keep it in `$EXTRA_ARGS`.
3. If no path given, scan the conversation (most recent first) for a local file that exists on disk and isn't a URL.
4. If nothing resolves, ask the user. Do not guess.

## Step 2: Resolve the viewer command (or fall back to editor in read-only mode)

```bash
RESOLVE="$CLAUDE_PLUGIN_ROOT/scripts/resolve.py"

VIEWER_CMD=$(python3 "$RESOLVE" view "$RESOLVED_PATH" ${LIVE:+--live} --provenance 2>/tmp/ed-view-prov.$$)
PROVENANCE=$(cat /tmp/ed-view-prov.$$ 2>/dev/null); rm -f /tmp/ed-view-prov.$$
```

Ladder inside `resolve.py`: `extensions.<ext>.viewer_live` (if `--live`) → `extensions.<ext>.viewer` → `defaults.viewer` → `$VIEWER` → `$ED_DEFAULT_VIEWER` → `less`.

If the resolver fell all the way through to the `less` fallback AND no explicit viewer is configured for this file type, use the editor in read-only mode instead — so `/ed:view script.py` opens your editor in view-only mode rather than paging Python source through `less`:

```bash
if [ "$PROVENANCE" = "fallback (less)" ]; then
    EDITOR_CMD=$(python3 "$RESOLVE" edit "$RESOLVED_PATH")
    RO_FLAG=$(python3 "$RESOLVE" readonly-flag "$EDITOR_CMD")
    if [ -n "$RO_FLAG" ]; then
        VIEWER_CMD="$EDITOR_CMD $RO_FLAG"
        PROVENANCE="editor read-only fallback"
    else
        # Editor has no read-only flag — open it normally and warn the user.
        VIEWER_CMD="$EDITOR_CMD"
        PROVENANCE="editor fallback (no read-only mode — file is writable)"
        echo "warning: editor has no known read-only flag; opened in normal edit mode"
    fi
fi
```

Validate the binary is on PATH:

```bash
BIN=$(echo "$VIEWER_CMD" | awk '{print $1}')
command -v "$BIN" >/dev/null || { echo "not on PATH: $BIN"; exit 1; }
```

## Step 3: Create the viewer surface

Single pane; splits off Claude directly (no editor pane in `/ed:view`).

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

**Critical**: `cmux new-split <dir> --surface <ref>`, not `cmux new-pane`.

## Step 4: Launch

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
Viewing <basename> via <bin> (<provenance>, <extras if any>) on <surface-ref>
```

## Rules

- Single pane only. If you want editor + viewer side-by-side, use `/ed:edit`.
- The read-only fallback kicks in only when the resolver hit the `less` end of the ladder. If `defaults.viewer`, `$VIEWER`, `$ED_DEFAULT_VIEWER`, or an extension-specific viewer is set, those are used as-is (no read-only-ifying).
- If the resolved editor has no known read-only flag (`readonly-flag` returned empty), the file opens writable and the skill prints a warning.
- `--live` affects resolution only when a `viewer_live` entry exists; otherwise it's just a passthrough flag.
