---
name: edit
description: Open a markdown file in Helix with a live preview pane next to it. Use when the user asks to edit a markdown file with preview, open md with glow, or set up the markdown editing layout. For non-markdown files, falls back to /hx:open behavior.
---

# /hx:edit — Edit a markdown file with live preview

Opens a markdown file in `hx` in a separate surface, then splits that surface to add a preview pane running a markdown renderer (default: `glow -p`).

Layout (horizontal monitor):
```
+---------------+-----------+
|               |  hx (top) |
|  Claude Code  |-----------|
|               | preview   |
+---------------+-----------+
```

Layout (vertical monitor, `HX_MONITOR=vertical`):
```
+---------------------------+
|      Claude Code          |
+------------+--------------+
|  hx (L)    |  preview (R) |
+------------+--------------+
```

## Arguments

`$ARGUMENTS` — Path to open. Same resolution rules as `/hx:open` (argument, else most recent local file in conversation, else prompt).

## Step 1: Resolve the target path

Same as `/hx:open` Step 1. Reject URLs.

If the resolved path is **not** a markdown file (doesn't end in `.md`, `.markdown`, or `.mdown`), fall back to `/hx:open` semantics — just open it in Helix without a preview pane. Tell the user why.

## Step 2: Check dependencies

```bash
command -v hx >/dev/null || { echo "hx not on PATH — install with 'brew install helix'"; exit 1; }
```

Resolve the preview command, falling back to `glow -p` if not set:

```bash
PREVIEW_CMD="${HX_PREVIEW_CMD:-glow -p}"
# First token is the binary
PREVIEW_BIN=$(echo "$PREVIEW_CMD" | awk '{print $1}')
command -v "$PREVIEW_BIN" >/dev/null || {
    echo "preview tool '$PREVIEW_BIN' not on PATH — install ('brew install glow') or set HX_PREVIEW_CMD"
    exit 1
}
```

## Step 3: Find or create the editor surface (Claude↔editor split)

Same reuse-then-create flow as `/hx:open` Step 2. The create-new direction is based on `HX_MONITOR`:

```bash
ORIENT="${HX_MONITOR:-${CURAITOR_MONITOR:-horizontal}}"
if [ "$ORIENT" = "vertical" ]; then
    EDITOR_DIR=down
else
    EDITOR_DIR=right
fi
# If creating a new surface:
cmux new-pane --type terminal --direction "$EDITOR_DIR"
```

Capture the editor surface ref as `EDITOR`.

## Step 4: Create the preview surface (editor↔preview split)

The preview split runs **perpendicular** to the Claude↔editor split so editor and preview end up side-by-side within the allotted region:

| Monitor | Claude↔editor | Editor↔preview |
|---|---|---|
| horizontal | right | down |
| vertical | down | right |

```bash
if [ "$ORIENT" = "vertical" ]; then
    PREVIEW_DIR=right
else
    PREVIEW_DIR=down
fi

cmux new-pane --type terminal --direction "$PREVIEW_DIR" --surface "$EDITOR"
```

Capture the preview surface ref as `PREVIEW`.

## Step 5: Launch Helix and preview

Helix in the editor surface:
```bash
cmux send --surface "$EDITOR" "hx '$RESOLVED_PATH'"
cmux send-key --surface "$EDITOR" Enter
cmux rename-tab --surface "$EDITOR" "hx: $(basename "$RESOLVED_PATH")"
```

Preview in the preview surface:
```bash
cmux send --surface "$PREVIEW" "$PREVIEW_CMD '$RESOLVED_PATH'"
cmux send-key --surface "$PREVIEW" Enter
cmux rename-tab --surface "$PREVIEW" "preview: $(basename "$RESOLVED_PATH")"
```

## Step 6: Report

Tell the user:
- Which file was opened
- Editor surface ref
- Preview surface ref
- Preview command used (so they know what to `:q` out of when closing)

Example: `Editing notes.md — editor surface:42, preview surface:43 (glow -p)`.

## Notes

- **Preview is not hot-reloaded.** `glow -p` is a pager — you need to `:q` and re-run to see edits. To get file-watching behaviour, set `HX_PREVIEW_CMD` to something like `bash -c 'while true; do clear; glow "$1"; sleep 2; done' --` (hacky) or install a tool that watches (`entr`, `watchexec`).
- **Non-markdown fallback.** The skill refuses to create a preview pane for non-markdown files and opens Helix alone.
- **Reuse rules match `/hx:open`.** If an alternate terminal surface already exists, it's reused as the editor surface; the preview pane is then split off it.
- **`HX_PREVIEW_CMD` format.** Space-separated; first token must be the binary. Example alternatives: `mdcat`, `bat --language=md --paging=always`, a custom script.
