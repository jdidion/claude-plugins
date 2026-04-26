---
name: edit
description: Open a file in an editor in an adjacent cmux surface. Default editor comes from config/env (ladder below); pass an explicit editor as the first arg to override. Use when the user asks to edit a file, open something in an editor, or open a file for editing. Any trailing flags are passed through to the editor.
---

# /ed:edit — Open a file in an editor in an adjacent cmux surface

Opens a file in a cmux terminal surface adjacent to the Claude Code conversation using your configured editor for that file's extension. Orientation-aware splits.

## Arguments

`$ARGUMENTS` — `[<editor>] [path] [--watch] [--live] [<other editor flags>]`

- **`<editor>`** — optional. If the first non-flag token is a bareword that is NOT an existing path, treat it as the editor command (e.g. `/ed:edit nano notes.md`). First token of this string is the binary; trailing tokens are args.
- **`path`** — file to open. If omitted, resolve to the most recently mentioned local file path from the current conversation.
- **`--watch`, `--live`**, and any other extra flags/tokens — passed through verbatim to the editor command (after the path). The skill does not interpret them.

## Step 1: Parse arguments and resolve path

1. Split `$ARGUMENTS` into tokens. Classify each:
   - `--foo` or `--foo=bar` → passthrough flag
   - any other token: if it names an existing path on disk, it's the **path**; otherwise (and there's no path yet), it's the **editor override**.
2. If after classification there is no path, scan the conversation (most recent first) for a local file path that exists on disk and isn't a URL.
3. If no path resolves, stop and ask the user for a path. Do not guess.

Keep the passthrough flags in a single string `$EXTRA_ARGS`.

Report the resolved path, the editor that will run, and any extra args, in one line before launching.

## Step 2: Resolve the editor command

Use the resolver, passing `--override` if the user supplied an editor:

```bash
if [ -n "$EDITOR_OVERRIDE" ]; then
    EDITOR_CMD=$("$CLAUDE_PLUGIN_ROOT/scripts/resolve.py" edit "$RESOLVED_PATH" --override "$EDITOR_OVERRIDE")
else
    EDITOR_CMD=$("$CLAUDE_PLUGIN_ROOT/scripts/resolve.py" edit "$RESOLVED_PATH")
fi
```

Resolution ladder (inside `resolve.py`): override → `extensions.<ext>.editor` in config → `defaults.editor` in config → `$VISUAL` → `$EDITOR` → `vi`. See the "Configuration" section of the README.

Validate the binary is on PATH:

```bash
BIN=$(echo "$EDITOR_CMD" | awk '{print $1}')
command -v "$BIN" >/dev/null || { echo "editor not on PATH: $BIN"; exit 1; }
```

## Step 3: Find or create the editor surface

Helper to list `surface:N` refs in the current workspace (sorted):

```bash
ws_surfaces() {
    cmux tree --workspace "$CMUX_WORKSPACE_ID" \
        | grep -oE 'surface:[0-9]+' \
        | sort -u
}
```

Reuse the first terminal surface whose ref is NOT `$CMUX_SURFACE_ID`. If none exists, create one. The direction is monitor-orientation-aware:

```bash
ORIENT="${ED_MONITOR:-${CURAITOR_MONITOR:-horizontal}}"
if [ "$ORIENT" = "vertical" ]; then
    EDITOR_DIR=down
else
    EDITOR_DIR=right
fi

BEFORE=$(ws_surfaces)
cmux new-split "$EDITOR_DIR" --surface "$CMUX_SURFACE_ID"
AFTER=$(ws_surfaces)
EDITOR_SURFACE=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)
```

**Critical**: use `cmux new-split <dir> --surface <ref>`, not `cmux new-pane` — `new-pane` ignores `--surface` and always splits the focused pane.

## Step 4: Launch the editor

```bash
CMD="$EDITOR_CMD '$RESOLVED_PATH'"
[ -n "$EXTRA_ARGS" ] && CMD="$CMD $EXTRA_ARGS"

cmux send --surface "$EDITOR_SURFACE" "$CMD"
cmux send-key --surface "$EDITOR_SURFACE" Enter
cmux rename-tab --surface "$EDITOR_SURFACE" "edit: $(basename "$RESOLVED_PATH")"
```

## Step 5: Report

One line:

```
Opened <basename> in <editor-bin> (<extra-args if any>) on <surface-ref>
```

## Rules

- Do not auto-focus the editor surface; the user switches manually.
- If the reused surface already has a long-running TUI, the new command is typed as keys into that TUI (unhelpful). Close it first.
- The skill does not interpret `--watch` / `--live` — they're pure passthroughs. Only some editors (helix --edit, watchexec wrappers, etc.) actually do anything with them.
- For the viewer counterpart, use `/ed:view`.
