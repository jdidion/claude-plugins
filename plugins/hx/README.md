# hx

Open files in Helix (`hx`) in a cmux terminal surface adjacent to the Claude Code conversation. For markdown files, `/hx:edit` also spawns a live preview pane next to the editor.

## Skills

| Skill | Purpose |
|---|---|
| `/hx:open` | Open any file in Helix in a separate cmux surface |
| `/hx:edit` | Open a markdown file in Helix + live preview pane (falls back to `/hx:open` for non-markdown) |

## Layout

Both skills respect a monitor-orientation hint so splits land in a useful direction.

**Horizontal monitor (default):** Claude on the left, editor/preview on the right.
```
+---------------+-------------------+
|               |      hx (top)     |
|  Claude Code  |-------------------|
|               |  glow (bottom)    |
+---------------+-------------------+
```

**Vertical monitor (`HX_MONITOR=vertical`):** Claude on top, editor/preview on the bottom.
```
+------------------------------------+
|           Claude Code              |
+-----------------+------------------+
|   hx (left)     |  glow (right)    |
+-----------------+------------------+
```

## Configuration

All optional.

| Env var | Default | Purpose |
|---|---|---|
| `HX_MONITOR` | `horizontal` | `vertical` flips the Claude↔editor split direction |
| `HX_PREVIEW_CMD` | `glow -p` | Command to render markdown in the preview pane. Runs as `$HX_PREVIEW_CMD <file>`. Must be a TUI-friendly tool. |
| `CURAITOR_MONITOR` | — | Honored as a fallback when `HX_MONITOR` is unset (same values) |

## Requirements

- macOS with cmux running; Claude Code session inside cmux (`CMUX_SURFACE_ID` and `CMUX_WORKSPACE_ID` must be set)
- `hx` on PATH (`brew install helix`)
- For `/hx:edit`: a markdown renderer on PATH, `glow` by default (`brew install glow`)

## Known limitations

- **Target surface already running Helix:** if the reused surface has Helix open, the new invocation types `hx <path>` into the active buffer. Close the prior Helix session first, or open a fresh surface manually.
- **Preview pane is read-only and not hot-reloaded by default.** `glow -p` is a pager — you'll need to `:q` and re-run it to see edits. A file-watching alternative (e.g. `entr`) can be swapped in via `HX_PREVIEW_CMD` if desired.
- **No close command in v1.** Clean up extra surfaces via cmux directly.

## Replaces

This plugin supersedes the global `~/.claude/commands/hx.md` slash command. Delete that file after installing the plugin to avoid shadowing.
