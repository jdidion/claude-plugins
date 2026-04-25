---
name: open
description: Open a file in Helix (hx) in a cmux terminal surface adjacent to the Claude Code conversation. Use when the user asks to open something in hx, edit a file in helix, or view a file in the editor. Reuses an existing alternate surface or creates a new one with orientation-aware direction.
---

# /hx:open — Open a file in Helix (adjacent surface)

Opens a document in `hx` (Helix) in a cmux terminal surface that is not the current Claude Code surface. If an alternate terminal surface already exists, reuse it. Otherwise create one in a monitor-orientation-appropriate direction so the new pane sits next to Claude rather than on top of it.

## Arguments

`$ARGUMENTS` — Optional path to open. If omitted, resolve to the most recently mentioned local file path from the current conversation (see Step 1).

## Step 1: Resolve the target path

1. If `$ARGUMENTS` is a non-empty string, treat it as the path. Expand `~` and make absolute.
2. Otherwise, scan the current conversation (most recent messages first) for a candidate and pick the most recent one that:
   - Is an absolute path, or a path clearly rooted in the current working directory
   - Exists on disk (verify with `test -e`)
   - Is **not** a URL (a `https://docs.google.com/...` link is not openable in Helix — in that case stop and ask the user for a local path)
3. If no candidate resolves, stop and ask the user for a path. Do not guess.

Report the resolved path to the user in one line before launching.

## Step 2: Find or create an alternate terminal surface

First, list surfaces in the current workspace:

```bash
cmux list-pane-surfaces
```

**Pick a reuse candidate** in this order:
1. First terminal surface whose `$CMUX_SURFACE_ID` is different from the current session's `CMUX_SURFACE_ID`.
2. Ignore browser surfaces — Helix needs a terminal.

If a candidate exists, use it as `TARGET` and skip to Step 3.

**Otherwise, create one.** Direction is chosen from the monitor orientation hint:

```bash
# Resolve direction (default horizontal → right; vertical → down)
ORIENT="${HX_MONITOR:-${CURAITOR_MONITOR:-horizontal}}"
if [ "$ORIENT" = "vertical" ]; then
    DIR=down
else
    DIR=right
fi

# Create a new terminal pane in that direction
cmux new-pane --type terminal --direction "$DIR"
```

Capture the returned surface ref from the `new-pane` output (format `OK surface:N pane:N workspace:N`). Store as `TARGET`.

## Step 3: Launch Helix

Check `hx` is installed first:

```bash
command -v hx >/dev/null || { echo "hx not on PATH — install with 'brew install helix'"; exit 1; }
```

Send the command. Quote the path to handle spaces. Send Enter as a separate key event so it executes reliably (sending with an embedded newline is flaky):

```bash
cmux send --surface "$TARGET" "hx '$RESOLVED_PATH'"
cmux send-key --surface "$TARGET" Enter
```

Rename the tab so it's easy to spot:

```bash
cmux rename-tab --surface "$TARGET" "hx: $(basename "$RESOLVED_PATH")"
```

## Step 4: Report

Tell the user which file was opened and in which surface (e.g. `Opened sop-change-list.md in surface:81`). Do not auto-focus the target surface.

## Notes

- Operates on the current cmux workspace; `CMUX_WORKSPACE_ID` is inherited automatically.
- If the resolved path is a directory, that's fine — `hx` opens directories as a file picker.
- If the reused surface already has Helix running, the new `hx <path>` text gets sent to Helix as normal-mode keystrokes (unhelpful). The user should close the prior Helix session first, or pass `--new-surface` intent by first running a no-op cmux surface close. This v1 doesn't detect that state.
