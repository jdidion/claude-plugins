---
name: open
description: Open a file in the OS default application (Preview, Finder, etc.) rather than a terminal viewer. Use when the user asks to open, reveal, launch, or "show me" a file in its native app — especially for formats that don't viewer-render well in a terminal (images, PDFs, PowerPoints, videos). No cmux surface is created. Optional --app <name> overrides the default app. Optional --reveal highlights the file in Finder instead of opening it.
---

# /ed:open — Open a file in the OS default application

Shells out to macOS `open` (or `xdg-open` on Linux) to launch the file in whatever GUI app the OS has registered for that file type. No cmux surface, no terminal pane — the external app does the work. Use when the user wants to *see* the file the way a human normally would, not when they want to tail/render it in a terminal.

When to reach for this vs `/ed:view`:

- **`/ed:open`** — Preview.app for a PDF, Keynote for a .key, Finder Quick Look for a whatever, a video in QuickTime.
- **`/ed:view`** — `glow` a markdown file, `csvlens` a CSV, `bat` source code. Stays in the terminal.

## Arguments

`$ARGUMENTS` — `[path] [--app <name>] [--reveal] [<passthrough-flags>]`

- `path` — file to open. If omitted, resolve to the most recently mentioned local file path in the conversation.
- `--app <name>` — macOS only. Force a specific app (e.g. `--app Preview`, `--app "Google Chrome"`). Maps to `open -a`.
- `--reveal` — macOS only. Highlight the file in Finder instead of opening it. Maps to `open -R`.
- Other tokens — passed through verbatim to the OS open command.

## Step 1: Parse arguments and resolve path

1. Tokenize `$ARGUMENTS`.
2. If `--app <name>` is present, capture the value as `$APP_OVERRIDE`. Both `--app=Preview` and `--app Preview` forms accepted.
3. If `--reveal` is present, set `REVEAL=1`.
4. Remaining non-flag tokens are path candidates or passthrough args. The first existing path wins; the rest become `$EXTRA_ARGS`.
5. If no path was given, scan the conversation (most recent first) for a local file that exists on disk and isn't a URL.
6. If nothing resolves, stop and ask the user. Do not guess.

## Step 2: Pick the platform command

```bash
case "$(uname -s)" in
    Darwin) OPENER=open ;;
    Linux)
        if command -v xdg-open >/dev/null; then
            OPENER=xdg-open
        else
            echo "No opener found. Install xdg-utils (apt/dnf install xdg-utils)." >&2
            exit 1
        fi
        ;;
    *)
        echo "Unsupported platform: $(uname -s)" >&2
        exit 1
        ;;
esac
```

`--app` and `--reveal` are macOS-only. If either is set on Linux, warn and drop them — `xdg-open` has no equivalent.

## Step 3: Build the command

```bash
CMD="$OPENER"

if [ "$OPENER" = "open" ]; then
    [ -n "$APP_OVERRIDE" ] && CMD="$CMD -a $(printf %q "$APP_OVERRIDE")"
    [ -n "$REVEAL" ]       && CMD="$CMD -R"
fi

CMD="$CMD $(printf %q "$RESOLVED_PATH")"
[ -n "$EXTRA_ARGS" ] && CMD="$CMD $EXTRA_ARGS"
```

Note: `printf %q` instead of raw quoting — filenames may contain spaces, quotes, or backslashes.

## Step 4: Launch

Run the command directly. No cmux surface, no `send-keys`. `open` returns instantly once the external app is launched:

```bash
eval "$CMD"
RC=$?
if [ $RC -ne 0 ]; then
    echo "failed: $CMD (exit $RC)" >&2
    exit $RC
fi
```

`eval` is necessary because `$APP_OVERRIDE` may contain spaces (e.g. `"Google Chrome"`) that were shell-escaped in Step 3.

## Step 5: Report

One line:

```
Opened <basename> in <app or default app> (<reveal|launch>)
```

Keep it short — the GUI app is now on screen; the user doesn't need a stack trace.

## Rules

- **No surface.** This skill never creates a cmux pane. If you want a terminal viewer, that's `/ed:view`.
- **macOS-only flags.** `--app` and `--reveal` are dropped with a warning on Linux.
- **No hot reload.** `open` hands off to an external app; the plugin has no control over it after launch. If the user wants reload-on-change, recommend `/ed:view --live` instead.
- **Don't block.** The command runs synchronously but the external app exits after launching its target, so you should return control to the user within a second or two. If `open` hangs, there's something wrong with the resolved path or the app itself — bubble the error up rather than retrying.
- **Security.** Don't `eval` raw `$ARGUMENTS`. Quote the path via `printf %q` so filenames with metacharacters don't become command injection.
