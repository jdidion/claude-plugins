---
name: hx
description: Open a file in Helix in an adjacent cmux surface. Use when the user asks to open something in hx or helix, view a file alongside Claude, or edit a file. For file types with a registered viewer (markdown by default) and any browser-viewable type, also spawns a viewer pane. Pass --edit to start Helix in insert mode and enable live reload where viewers support it.
---

# /hx — Open a file in Helix with an optional viewer pane

Opens a file in `hx` (Helix) in a cmux terminal surface adjacent to the Claude Code conversation. For file types with a registered viewer, also opens a viewer pane (perpendicular split). Without a registered viewer, falls back to cmux's built-in browser for browser-viewable file types.

## Arguments

`$ARGUMENTS` — `[--edit] [path]`

- `--edit` — Start Helix in insert mode (`hx --edit <path>`). Also enables live-reload for viewers that have a configured watch variant (`HX_VIEWER_<EXT>_WATCH`).
- `path` — Path to open. If omitted, resolve to the most recently mentioned local file path from the current conversation.

## Step 1: Parse arguments and resolve path

Split `$ARGUMENTS` into flags and the path:

- If `--edit` appears, set `EDIT=1`; otherwise `EDIT=0`. Strip it from the arg list.
- The remaining non-flag token (if any) is the path.

Path resolution:
1. If a path was provided, treat it as the target. Expand `~`, make absolute.
2. Otherwise, scan the current conversation (most recent first) for a local file path that:
   - Is absolute or rooted in the current working directory
   - Exists on disk (`test -e`)
   - Is **not** a URL (a `https://…` link is not openable in Helix; stop and ask for a local path)
3. If nothing resolves, stop and ask the user for a path. Do not guess.

Report the resolved path in one line before launching.

## Step 2: Resolve the viewer for the file's extension

Extract the extension (lowercased, without the dot):

```bash
EXT=$(python3 -c "import sys, os; print(os.path.splitext(sys.argv[1])[1].lstrip('.').lower())" "$RESOLVED_PATH")
```

Determine `VIEWER_CMD`:

1. If `$EDIT` is set **and** `HX_VIEWER_<EXT>_WATCH` is set, use that (live-reload variant).
2. Else if `HX_VIEWER_<EXT>` is set, use that.
3. Else if `$EDIT` is NOT set and the default for this extension is defined (see below), use it.
4. Else if the extension is browser-viewable (see below), the browser fallback in Step 5 is used (it splits the editor pane and opens a browser surface there).
5. Else: no viewer. Skip the viewer pane.

### Built-in defaults

Only one extension has a default viewer command:

| Extension | Default `HX_VIEWER_<EXT>` |
|---|---|
| `md` / `markdown` / `mdown` | `glow -p` |

All other extensions require an explicit env var or the browser fallback.

### Browser-viewable extensions

If no explicit viewer is set, these fall back to the cmux browser:

`pdf, html, htm, svg, png, jpg, jpeg, gif, webp, bmp, ico, mp4, webm, mov, m4v, ogg, ogv, mp3, wav, flac, txt, log, json, xml, yaml, yml, toml, csv, tsv`

All other extensions without an explicit viewer get no viewer pane.

## Step 3: Find or create the editor surface

Helper to list all `surface:N` refs in the current workspace (sorted):

```bash
ws_surfaces() {
    cmux tree --workspace "$CMUX_WORKSPACE_ID" \
        | grep -oE 'surface:[0-9]+' \
        | sort -u
}
```

List existing surfaces and reuse the first terminal surface whose ref is NOT `$CMUX_SURFACE_ID`. If none exists, create one:

```bash
ORIENT="${HX_MONITOR:-${CURAITOR_MONITOR:-horizontal}}"
if [ "$ORIENT" = "vertical" ]; then
    EDITOR_DIR=down
else
    EDITOR_DIR=right
fi

BEFORE=$(ws_surfaces)
cmux new-split "$EDITOR_DIR" --surface "$CMUX_SURFACE_ID"
AFTER=$(ws_surfaces)
EDITOR=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)
```

`EDITOR` now holds the new surface ref (e.g. `surface:6`).

## Step 4: Launch Helix

```bash
command -v hx >/dev/null || { echo "hx not on PATH — install with 'brew install helix'"; exit 1; }

if [ "$EDIT" = "1" ]; then
    HX_CMD="hx --edit '$RESOLVED_PATH'"
else
    HX_CMD="hx '$RESOLVED_PATH'"
fi

cmux send --surface "$EDITOR" "$HX_CMD"
cmux send-key --surface "$EDITOR" Enter
cmux rename-tab --surface "$EDITOR" "hx: $(basename "$RESOLVED_PATH")"
```

## Step 5: Create and launch the viewer pane (if applicable)

Skip if `VIEWER_CMD` is empty (Step 2 returned "no viewer").

**Perpendicular split direction** — so editor and viewer sit side-by-side within the allotted half:

| Monitor | Editor split | Viewer split |
|---|---|---|
| horizontal | right | down |
| vertical | down | right |

```bash
if [ "$ORIENT" = "vertical" ]; then
    VIEWER_DIR=right
else
    VIEWER_DIR=down
fi
```

**CRITICAL**: The viewer must split from `$EDITOR`, not from the Claude pane. Use `cmux new-split <dir> --surface <ref>` — `cmux new-pane` does NOT accept `--surface` and will silently split the focused pane instead, producing a broken layout (viewer below Claude, editor alone in the other column).

**Terminal viewer** (e.g. `glow`, `csvlens`, a watch-wrapper): split the editor pane, diff the surface list to capture the new ref, then send the command.

```bash
BEFORE=$(ws_surfaces)
cmux new-split "$VIEWER_DIR" --surface "$EDITOR"
AFTER=$(ws_surfaces)
VIEWER=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)

cmux send --surface "$VIEWER" "$VIEWER_CMD '$RESOLVED_PATH'"
cmux send-key --surface "$VIEWER" Enter
cmux rename-tab --surface "$VIEWER" "view: $(basename "$RESOLVED_PATH")"
```

**Browser viewer fallback** (cmux builtin): split the editor to create a new terminal pane, then add a browser tab in that pane and close the terminal placeholder.

```bash
BEFORE=$(ws_surfaces)
cmux new-split "$VIEWER_DIR" --surface "$EDITOR"
AFTER=$(ws_surfaces)
TERM_VIEWER=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)

# Find the pane the new terminal surface lives in.
NEW_PANE=$(cmux tree --workspace "$CMUX_WORKSPACE_ID" \
    | awk -v s="$TERM_VIEWER" '
        /pane pane:[0-9]+/ { match($0, /pane:[0-9]+/); p = substr($0, RSTART, RLENGTH) }
        index($0, s) { print p; exit }
    ')

# Add a browser surface to that pane, then close the terminal placeholder.
BEFORE=$(ws_surfaces)
cmux new-surface --type browser --pane "$NEW_PANE" --url "file://$RESOLVED_PATH"
AFTER=$(ws_surfaces)
VIEWER=$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") | head -1)
cmux close-surface --surface "$TERM_VIEWER"

cmux rename-tab --surface "$VIEWER" "view: $(basename "$RESOLVED_PATH")"
```

If the viewer command's first token isn't on PATH, warn and skip the viewer pane rather than failing the whole skill.

## Step 6: Report

Tell the user in one line:
- Resolved path
- Editor surface ref (always)
- Viewer surface ref (if any) and which command was used
- Whether `--edit` was passed
- Whether live-reload was enabled (only if `--edit` AND a `*_WATCH` env var fired)

Example:
```
Opened notes.md (editor=surface:42, viewer=surface:43 via 'glow -p', --edit on, live-reload off — set HX_VIEWER_MD_WATCH to enable)
```

## Configuration reference

All optional.

| Env var | Purpose |
|---|---|
| `HX_MONITOR` | `horizontal` (default) or `vertical` — flips the Claude↔editor split direction. |
| `CURAITOR_MONITOR` | Honored as a fallback for `HX_MONITOR`. |
| `HX_VIEWER_<EXT>` | Viewer command for files with extension `<EXT>` (uppercase). First token must be the binary. Example: `HX_VIEWER_PDF="zathura"`, `HX_VIEWER_CSV="csvlens"`. |
| `HX_VIEWER_<EXT>_WATCH` | Live-reload variant used only when `--edit` is passed. Example: `HX_VIEWER_MD_WATCH='bash -c "while :; do clear; glow \"$1\"; sleep 1; done" --'`. |

## Notes

- The skill does NOT auto-focus the editor or viewer surface. User switches manually.
- If the reused editor surface already has Helix running, the new invocation types `hx <path>` into the existing buffer as normal-mode keys (unhelpful). Close the prior Helix first.
- The cmux browser fallback renders via the app's WebKit — fine for PDFs, images, HTML, etc. Text files render as source (no syntax highlighting); set an explicit `HX_VIEWER_<EXT>` if that matters.
