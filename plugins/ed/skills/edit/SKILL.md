---
name: edit
description: Open a file for editing in an adjacent cmux surface. Also opens a viewer pane with hot reload when the file type has a viewer configured. Use when the user asks to edit a file, open something in an editor, or open a file for editing. First bareword argument can override the editor (e.g. /ed:edit nano notes.md).
---

# /ed:edit — Edit a file with an optional viewer pane

Opens a file in an editor in a new cmux terminal surface next to Claude. If the file's extension has an explicitly-configured viewer, also opens a viewer pane beside the editor with hot reload when available.

## Arguments

`$ARGUMENTS` — `[<editor>] [path] [<passthrough-flags>]`

- `<editor>` — optional. The first non-flag token that is NOT an existing path is treated as an inline editor override (binary + args, e.g. `"emacs -nw"`).
- `path` — file to open. If omitted, resolve to the most recently mentioned local file path in the conversation.
- Other tokens — passed through verbatim to the editor after the path.

## Step 1: Parse arguments and resolve path

1. Tokenize `$ARGUMENTS`. Classify each token as flag (`--foo`), existing path, or bareword.
2. If a bareword appears before any path, treat it as `$EDITOR_OVERRIDE`. Only one override is accepted; additional barewords are passthrough args.
3. If no path was given, scan the current conversation (most recent first) for a local file path that exists on disk and isn't a URL.
4. If no path resolves, stop and ask the user. Do not guess.

Collect remaining tokens into `$EXTRA_ARGS`.

Report the resolved path, editor, and extras in one line before launching.

## Step 2: Resolve the editor command and its edit flag

```bash
RESOLVE="$CLAUDE_PLUGIN_ROOT/scripts/resolve.py"

if [ -n "$EDITOR_OVERRIDE" ]; then
    EDITOR_CMD=$(python3 "$RESOLVE" edit "$RESOLVED_PATH" --override "$EDITOR_OVERRIDE")
else
    EDITOR_CMD=$(python3 "$RESOLVE" edit "$RESOLVED_PATH")
fi

EDIT_FLAG=$(python3 "$RESOLVE" edit-flag "$EDITOR_CMD")
```

`$EDIT_FLAG` is empty for editors that don't have a separate edit/insert mode flag (most of them — hx, vi, nano, micro, code, sublime). It's set to e.g. `-i` for kakoune. When empty, invoke the editor normally — it's edit-capable by default.

Validate the binary is on PATH:

```bash
BIN=$(echo "$EDITOR_CMD" | awk '{print $1}')
command -v "$BIN" >/dev/null || { echo "editor not on PATH: $BIN"; exit 1; }
```

## Step 3: Decide whether to open a viewer pane

Ask the resolver: does this file's extension have an **explicitly configured** viewer? Default viewers / env fallbacks don't count — we only open a viewer pane if one is configured for this file type.

```bash
VIEWER_CMD=$(python3 "$RESOLVE" viewer-configured "$RESOLVED_PATH" --live)
```

- If `$VIEWER_CMD` is empty → open only the editor (skip steps 5-6). Print `No viewer configured for .<ext>; opening editor only.`
- If non-empty → run `$VIEWER_CMD` in the viewer pane. Because of `--live`, it's the `viewer_live` variant if configured; otherwise the regular `viewer` entry.

Validate the viewer binary is on PATH:

```bash
if [ -n "$VIEWER_CMD" ]; then
    VBIN=$(echo "$VIEWER_CMD" | awk '{print $1}')
    if ! command -v "$VBIN" >/dev/null; then
        echo "warning: viewer not on PATH: $VBIN — skipping viewer pane"
        VIEWER_CMD=""
    fi
fi
```

## Step 4: Create the editor surface

```bash
ws_surfaces() {
    cmux tree --workspace "$CMUX_WORKSPACE_ID" \
        | grep -oE 'surface:[0-9]+' \
        | sort -u
}

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

**Critical**: `cmux new-split <dir> --surface <ref>`, not `cmux new-pane` — `new-pane` ignores `--surface` and splits the focused pane.

## Step 5: Launch the editor

```bash
CMD="$EDITOR_CMD"
[ -n "$EDIT_FLAG" ] && CMD="$CMD $EDIT_FLAG"
CMD="$CMD '$RESOLVED_PATH'"
[ -n "$EXTRA_ARGS" ] && CMD="$CMD $EXTRA_ARGS"

cmux send --surface "$EDITOR_SURFACE" "$CMD"
cmux send-key --surface "$EDITOR_SURFACE" Enter
cmux rename-tab --surface "$EDITOR_SURFACE" "edit: $(basename "$RESOLVED_PATH")"
```

## Step 6: Create and launch the viewer pane (if `$VIEWER_CMD` non-empty)

The viewer must split from `$EDITOR_SURFACE`, not from Claude, so editor + viewer sit together in the non-Claude half of the screen. Direction is perpendicular to the editor split:

```bash
if [ "$ORIENT" = "vertical" ]; then
    VIEWER_DIR=right
else
    VIEWER_DIR=down
fi

BEFORE=$(ws_surfaces)
cmux new-split "$VIEWER_DIR" --surface "$EDITOR_SURFACE"
AFTER=$(ws_surfaces)
VIEWER_SURFACE=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)

cmux send --surface "$VIEWER_SURFACE" "$VIEWER_CMD '$RESOLVED_PATH'"
cmux send-key --surface "$VIEWER_SURFACE" Enter
cmux rename-tab --surface "$VIEWER_SURFACE" "view: $(basename "$RESOLVED_PATH")"
```

## Step 7: Report

One line:

```
Editing <basename> in <editor-bin>[ <edit-flag>][ + viewer <viewer-bin>[ (live)]] on <surface-ref(s)>
```

## Rules

- Only open the viewer pane if the file's extension has an **explicit viewer** entry in config. Don't use defaults/env/less fallback here — that logic lives in `/ed:view`.
- Prefer the `viewer_live` variant when configured; that's the hot-reload path.
- Don't auto-focus either surface; the user switches manually.
- Reusing a surface with an active TUI types the new command as keys into it. Close the prior process first.
- The skill doesn't interpret `--watch` / `--live` in `$EXTRA_ARGS` — they're passthroughs to the editor.
