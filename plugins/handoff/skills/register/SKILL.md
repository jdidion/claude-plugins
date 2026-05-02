---
name: register
description: Re-register the current Claude Code session or set/override its alias. This session is normally auto-registered on startup; use this skill to set an explicit alias when the automatic one from the cmux workspace title isn't what you want, or after modifying the registry manually. Canonical key is always the Claude session ID.
---

# /handoff:register — Register or re-register this session

Sessions are keyed by the Claude **session ID** (a UUID), not a friendly name. The `SessionStart` hook auto-registers every session on startup, resume, and `/clear`, so this skill is rarely needed directly — reach for it when:

- You want to set an explicit alias (override the workspace-title default).
- The auto-register hook didn't fire (you disabled hooks, or session_id wasn't in the hook payload).
- You want to force a refresh after manually editing `~/.claude/handoffs/registry.json`.

## Arguments
`$ARGUMENTS` — optional `--alias <name>` to override the workspace-title alias.

## Step 1: Determine the session ID

Claude Code exposes the session ID in hook payloads and via the internal session path. The simplest path is to pull it from the transcript filename that Claude is currently appending to:

```bash
# Find the most-recently-modified session jsonl file.
SESSION_JSONL=$(ls -1t ~/.claude/projects/*/*.jsonl 2>/dev/null | head -1)
SESSION_ID=$(basename "$SESSION_JSONL" .jsonl)
```

If that fails, ask the user — they can run `echo $CLAUDE_SESSION_ID` in a terminal started under the Claude hook environment, or paste the path from `/status`.

## Step 2: Determine the cmux refs

```bash
cmux identify --no-caller
```

Extract `surface_ref` and `workspace_ref` from the `focused` object in the JSON output.

## Step 3: Register

```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py register \
  "$SESSION_ID" \
  "<surface_ref>" \
  "<workspace_ref>" \
  ${ALIAS:+--alias "$ALIAS"}
```

- The session is stored under `sessions["<session-id>"]`.
- An alias is added automatically, derived from the cmux workspace title (slugified — "Plugins" → `plugins`, "Curaitor Review" → `curaitor-review`). An explicit `--alias <name>` wins over the auto-alias.
- Any alias with the same name pointing at a different (typically dead) session is overwritten silently.
- Dead sessions (whose PIDs no longer exist) are garbage-collected from the registry as a side effect.

Registry schema:

```json
{
  "sessions": {
    "<session-id>": {
      "alias": "plugins",
      "surface": "surface:1",
      "workspace": "workspace:1",
      "cwd": "/path/to/project",
      "registered_at": "ISO-8601",
      "pid": 12345
    }
  },
  "aliases": {
    "plugins": "<session-id>"
  }
}
```

## Step 4: Create inbox directory

```bash
mkdir -p ~/.claude/handoffs/inbox/$SESSION_ID
```

## Step 5: Confirm

```
Registered session <session-id>
  Alias: plugins  (from cmux workspace title)
  Surface: surface:1
  Workspace: workspace:1
  Inbox: ~/.claude/handoffs/inbox/<session-id>/

Other sessions can send handoffs with:
  /handoff:send --to plugins        (alias, preferred)
  /handoff:send --to <session-id>   (canonical)
```

## Auto-registration

The plugin's `SessionStart` hook (see `hooks/hooks.json`) runs on every session event — startup, resume, and `/clear`. It reads the session ID from the hook payload and re-registers automatically. That means a `/clear` repoints your alias at the new session ID without any user action.

The `SessionEnd` hook unregisters and cleans up bridge processes on exit.

## Rules
- Canonical key is always the Claude session ID (UUID).
- Aliases are free-form short names. The workspace-title slug is the default; `--alias <name>` overrides.
- Re-registration is idempotent. Running twice with the same session ID and different alias rewrites the alias entry.
- If cmux is unavailable, registration still succeeds with empty surface/workspace refs — file-based handoff still works via the inbox directory.
