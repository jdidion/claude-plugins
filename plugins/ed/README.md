# ed

Open a file in your editor or viewer in a cmux terminal surface adjacent to the Claude Code conversation. Two commands, per-extension config, orientation-aware splits.

## Commands

```
/ed:edit [<editor>] [<path>] [<passthrough-flags>]
/ed:view [<path>] [--live] [<passthrough-flags>]
```

- `<path>` is optional; if omitted, the skill resolves to the most recently mentioned local file path in the conversation.
- For `/ed:edit`, the first non-flag non-path token is treated as an editor command (e.g. `/ed:edit nano notes.md`). Shell word-splitting works, so `/ed:edit "emacs -nw" notes.md` is fine.
- Remaining tokens are passed through verbatim to the editor / viewer.

## Behavior

### `/ed:edit`

Opens the editor in edit mode (if the editor has a separate edit flag — most don't). If the file's extension has an **explicitly configured viewer**, also opens a viewer pane beside the editor using the `viewer_live` variant when available (hot reload).

- No viewer is opened for extensions without a configured viewer, even if a default viewer or `$VIEWER` is set — those are for `/ed:view`.
- Editor + viewer sit in the non-Claude half of the screen, split perpendicular to the Claude↔editor split.

### `/ed:view`

Opens a single viewer pane. Resolution ladder:

1. `extensions.<ext>.viewer_live` (if `--live` is passed)
2. `extensions.<ext>.viewer`
3. `defaults.viewer`
4. `$VIEWER`
5. `$ED_DEFAULT_VIEWER`
6. `less`

If every step above fell through to `less` (i.e. nothing viewer-shaped is configured), `/ed:view` falls back to the editor in **read-only mode** using the editor's known read-only flag (e.g. `vi -R`, `micro -readonly true`). If the editor has no known read-only flag, it opens normally and prints a warning.

## Layout

**Horizontal monitor (default):**
```
+---------------+------------------+
|               |      editor      |
|  Claude Code  |------------------|
|               |   viewer (hot    |
|               |    reload)       |
+---------------+------------------+
```

**Vertical monitor (`ED_MONITOR=vertical`):**
```
+------------------------------------+
|           Claude Code              |
+------------------+-----------------+
|    editor        |  viewer (hot    |
|                  |    reload)      |
+------------------+-----------------+
```

`/ed:view` opens a single pane instead of the editor+viewer pair.

## Configuration

Two TOML sources are merged (repo-local wins on conflict):

1. **User:** `${XDG_CONFIG_HOME:-~/.config}/ed/config.toml`
2. **Repo-local:** `<repo-root>/.ed.toml`

### Example

```toml
[defaults]
editor = "micro"
viewer = "micro"

[extensions.md]
viewer = "glow -p"
# No viewer_live needed: when `entr` is installed, the plugin auto-wraps
# `glow -p` with `entr -r` for hot-reload. See "Hot reload" below.

[extensions.pdf]
viewer = "cmux browser open"

[extensions.csv]
viewer = "csvlens"

# Optional per-editor flags. Built-in defaults cover hx, vi, vim, nvim,
# nano, emacs, micro, code, subl, kakoune. Override here to disable or
# change them per user.
[editors.vi]
readonly_flag = "-R"

[editors.micro]
readonly_flag = "-readonly true"
```

### Hot reload (`--live`, `/ed:edit` viewer pane)

The live/hot-reload path is driven by a single question: is an explicit `viewer_live` set for the extension?

1. **If yes** → run that command as-is. Use this for viewers that require a bespoke reload recipe or a command other than the one `viewer` resolves to.
2. **If no** and `entr` is installed on PATH → the plugin auto-wraps the regular `viewer` as:
   ```
   bash -c 'echo "$1" | entr -r <viewer-cmd> "$1"' --
   ```
   `entr -r` restarts the viewer whenever the file changes. `entr` is BSD-licensed; `brew install entr` on macOS, `apt install entr` on Debian/Ubuntu, `yum install entr` on Fedora/RHEL.
3. **If `entr` isn't installed** → the regular `viewer` runs once, and the skill prints a one-line stderr hint: `tip: install entr for hot-reload (brew install entr)`.
4. **Self-watching viewers are never wrapped.** Built-in no-wrap list: `code`, `subl`, `cmux`, `open`, `xdg-open` — they handle reload themselves or hand off to an external app.

Pass `--no-autowrap` to the resolver to skip auto-wrap even when `entr` is installed (useful for debugging).

#### Manual `viewer_live` recipes

Still useful when the auto-wrap isn't what you want (e.g. `entr -c` instead of `-r`, or piping through a renderer):

```toml
[extensions.tex]
viewer_live = "bash -c 'echo \"$1\" | entr -r tectonic --preview \"$1\"' --"

[extensions.puml]
viewer_live = "bash -c 'echo \"$1\" | entr -r plantuml -pipe \"$1\"' --"

# Polling fallback for systems without entr:
[extensions.md]
viewer_live = "bash -c 'while :; do clear; glow \"$1\"; sleep 1; done' --"
```

### Resolution ladders

**`/ed:edit` editor:**

1. `<editor>` arg (explicit inline override)
2. `config.extensions.<ext>.editor`
3. `config.defaults.editor`
4. `$VISUAL`
5. `$EDITOR`
6. `vi`

**`/ed:edit` viewer pane** — opens only if `config.extensions.<ext>.viewer[_live]` is set. No defaults/env fallback.

**`/ed:view`:** see "Behavior" above.

### Built-in per-editor flags

| Editor | `edit_flag` | `readonly_flag` |
|---|---|---|
| hx, helix | (none) | (none — hx has no read-only mode) |
| vi, vim, nvim | (none) | `-R` |
| nano | (none) | `-v` |
| emacs | (none) | `--eval '(setq buffer-read-only t)'` |
| micro | (none) | `-readonly true` |
| code, subl | (none) | (none) |
| kak, kakoune | `-i` | (none) |

Override any of these in `[editors.<bin>]` in your config.

### Orientation auto-detection

On macOS, when neither `ED_MONITOR` nor `CURAITOR_MONITOR` is set, the plugin runs `system_profiler -json SPDisplaysDataType` and picks `vertical` if any external display is attached, otherwise `horizontal`. The assumption: when you're docked at a desk you want the panes stacked; when you're on the laptop alone you want them side-by-side.

Known limitation: `system_profiler` doesn't say *which* display cmux is on. If you dock but keep the built-in panel as primary and park cmux there, detection still returns `vertical`. Set `ED_MONITOR=horizontal` to override.

Fails open to `horizontal` on non-Darwin or any detection error. Takes ~300–400 ms cold; run once per skill invocation.

### Env vars

| Var | Effect |
|---|---|
| `ED_MONITOR` | `horizontal` or `vertical`. When set, wins over auto-detection. |
| `CURAITOR_MONITOR` | Fallback for `ED_MONITOR` (auto-detection still runs if neither is set). |
| `VISUAL`, `EDITOR` | Standard Unix editor fallbacks. |
| `VIEWER`, `ED_DEFAULT_VIEWER` | Viewer fallbacks for `/ed:view`. |

## Requirements

- macOS with cmux running
- Claude Code session inside cmux (so `CMUX_SURFACE_ID` / `CMUX_WORKSPACE_ID` are set)
- Python 3.10+ (3.11+ reads TOML natively; older: `pip install tomli`)
- Whatever binary your resolution ladder lands on must be on `PATH`

## Replaces

Supersedes the `hx` plugin.

## Known limitations

- Reusing a surface with an active TUI types the new command as keystrokes into it. Close the previous process first.
- The skill doesn't parse editor/viewer flags; quoting bugs are the user's responsibility.
- No explicit close command. Close surfaces via cmux directly.
