# ed

Open a file in your editor or viewer in a cmux terminal surface adjacent to the Claude Code conversation. Two commands, per-extension config, orientation-aware splits.

## Commands

```
/ed:edit [<editor>] [<path>] [<passthrough-flags>]
/ed:view [<path>] [--live] [<passthrough-flags>]
```

- `<path>` is optional; if omitted, the skill resolves to the most recently mentioned local file path in the conversation.
- For `/ed:edit`, the first non-flag non-path token is treated as an editor command (e.g. `/ed:edit nano notes.md`). The skill uses shell word-splitting, so `/ed:edit "emacs -nw" notes.md` works too.
- Any remaining tokens (`--watch`, `--live`, editor-specific flags) are passed through verbatim. `/ed:view --live` additionally picks up the `viewer_live` variant from config if one is defined for that extension.

## Layout

Monitor-orientation-aware splits. The skill creates the new surface perpendicular to the long axis.

**Horizontal monitor (default):** Claude on the left, ed pane on the right.
```
+---------------+------------------+
|               |                  |
|  Claude Code  |   ed (editor     |
|               |    or viewer)    |
+---------------+------------------+
```

**Vertical monitor (`ED_MONITOR=vertical`):** Claude on top, ed pane below.
```
+-----------------------------------+
|           Claude Code             |
+-----------------------------------+
|   ed (editor or viewer)           |
+-----------------------------------+
```

Run both `/ed:edit` and `/ed:view` back-to-back to get an editor + viewer pair side by side; each command splits its own surface off Claude's.

## Configuration

All optional. Two config sources are merged (repo-local wins over user):

1. **User:** `${XDG_CONFIG_HOME:-~/.config}/ed/config.toml`
2. **Repo-local:** `<repo-root>/.ed.toml`

### TOML shape

```toml
[defaults]
editor = "hx"
viewer = "micro"

[extensions.md]
editor = "hx"
viewer = "glow -p"
viewer_live = "bash -c 'while :; do clear; glow \"$1\"; sleep 1; done' --"

[extensions.pdf]
viewer = "zathura"

[extensions.csv]
viewer = "csvlens"
```

### Resolution ladder

**`/ed:edit`:**

1. `<editor>` arg (explicit inline override)
2. `config.extensions.<ext>.editor`
3. `config.defaults.editor`
4. `$VISUAL`
5. `$EDITOR`
6. `vi`

**`/ed:view`:**

1. `config.extensions.<ext>.viewer_live` (only when `--live` is passed)
2. `config.extensions.<ext>.viewer`
3. `config.defaults.viewer`
4. `$VIEWER`
5. `$ED_DEFAULT_VIEWER`
6. If everything above fell through → the editor ladder (so `/ed:view script.py` runs your editor instead of paging source through `less`).
7. `less` (last resort).

### Env vars

| Var | Effect |
|---|---|
| `ED_MONITOR` | `horizontal` (default) or `vertical`; flips the Claude↔ed split direction. |
| `CURAITOR_MONITOR` | Fallback for `ED_MONITOR` (honored for users already on the curaitor convention). |
| `VISUAL`, `EDITOR` | Standard Unix editor fallbacks for `/ed:edit`. |
| `VIEWER`, `ED_DEFAULT_VIEWER` | Viewer fallbacks for `/ed:view`. |

## Requirements

- macOS with cmux running
- Claude Code session inside cmux (so `CMUX_SURFACE_ID` / `CMUX_WORKSPACE_ID` are set)
- Python 3.10+ (Python 3.11+ reads TOML natively; older versions need `pip install tomli`)
- Whatever binary your resolution ladder lands on must be on `PATH`

## Replaces

Supersedes the `hx` plugin. Uninstall `hx` after installing `ed`:

```
/plugin uninstall hx@jdidion-plugins
```

## Known limitations

- Reusing a surface that already has a long-running TUI open types the new command as keystrokes into that TUI. Close the previous process first.
- The skill doesn't parse editor/viewer flags; it shells them in as-is. Quoting bugs are the user's responsibility.
- No explicit close command. Close surfaces via cmux directly.
