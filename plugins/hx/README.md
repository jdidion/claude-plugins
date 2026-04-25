# hx

Open a file in Helix (`hx`) in a cmux terminal surface adjacent to the Claude Code conversation. For file types that have a registered viewer (markdown by default), also spawn a viewer pane. For browser-viewable file types (PDFs, images, HTML, etc.), fall back to cmux's built-in browser as the viewer.

## Usage

```
/hx [--edit] [<path>]
```

- `<path>` — file to open; if omitted, resolves to the most recently mentioned local file in the conversation.
- `--edit` — start Helix in insert mode (`hx --edit`). Also enables live-reload for viewers that have a configured watch variant (`HX_VIEWER_<EXT>_WATCH`).

## Layout

Monitor-orientation-aware splits.

**Horizontal monitor (default):** Claude on the left, editor + viewer on the right.
```
+---------------+-------------------+
|               |      hx (top)     |
|  Claude Code  |-------------------|
|               |  viewer (bottom)  |
+---------------+-------------------+
```

**Vertical monitor (`HX_MONITOR=vertical`):** Claude on top, editor + viewer below.
```
+------------------------------------+
|           Claude Code              |
+-----------------+------------------+
|   hx (left)     |  viewer (right)  |
+-----------------+------------------+
```

When no viewer applies (no registered extension, not browser-viewable), only Helix opens.

## Viewer resolution

For a file with extension `.ext`:

1. **`--edit` set AND `HX_VIEWER_<EXT>_WATCH` defined** → use the watch variant (live reload)
2. **`HX_VIEWER_<EXT>` defined** → use it
3. **Built-in default for `.ext`** → use it (see table below)
4. **Extension is browser-viewable** → `cmux browser open file://<path>`
5. **Otherwise** → no viewer pane, just Helix

### Built-in defaults

| Extension | Command |
|---|---|
| `.md`, `.markdown`, `.mdown` | `glow -p` |

### Browser-viewable fallback

If nothing else matches, and the extension is in this list, the cmux browser opens the file as the viewer:

```
pdf html htm svg png jpg jpeg gif webp bmp ico
mp4 webm mov m4v ogg ogv mp3 wav flac
txt log json xml yaml yml toml csv tsv
```

For anything else, no viewer opens — just Helix.

## Configuration

All optional. Set in your shell config (`~/.zshrc`, `~/.bashrc`, etc.).

| Env var | Purpose |
|---|---|
| `HX_MONITOR` | `horizontal` (default) or `vertical`; flips the Claude↔editor split direction. |
| `CURAITOR_MONITOR` | Fallback for `HX_MONITOR` (honored for users already on the curaitor convention). |
| `HX_VIEWER_<EXT>` | Viewer command for files with extension `<EXT>` (uppercase). Example: `HX_VIEWER_PDF="zathura"`, `HX_VIEWER_CSV="csvlens"`. First token must be the binary. |
| `HX_VIEWER_<EXT>_WATCH` | Live-reload variant, used only when `--edit` is passed. Example: `HX_VIEWER_MD_WATCH='bash -c "while :; do clear; glow \"$1\"; sleep 1; done" --'`. |

## Requirements

- macOS with cmux running
- Claude Code session inside cmux (`CMUX_SURFACE_ID`, `CMUX_WORKSPACE_ID` auto-populated)
- `hx` on PATH (`brew install helix`)
- For the default markdown viewer: `glow` (`brew install glow`)
- Any other `HX_VIEWER_<EXT>` command you configure needs to be on PATH

## Known limitations

- **Reused editor surface with Helix already running:** the new `hx <path>` is typed into the active Helix buffer as normal-mode keys. Close the prior Helix first.
- **Most TUI viewers don't auto-refresh.** `glow -p` is a pager. Set `HX_VIEWER_<EXT>_WATCH` for a file-watching variant, or accept that you need to `:q` and rerun to see edits.
- **Browser viewer doesn't live-reload either** — cmux would need a file-watcher hooked to `cmux browser reload`. Out of scope for v1.
- **No close command.** Remove extra surfaces via cmux directly.

## Replaces

Supersedes the global `~/.claude/commands/hx.md` slash command. Delete that file after installing the plugin to avoid shadowing.
