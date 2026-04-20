# /handoff:register — Register this session for handoff discovery

Register the current Claude Code session with a friendly name so other sessions can find and send handoffs to it.

## Arguments
$ARGUMENTS — Optional: friendly name for this session. If omitted, derives from the current working directory basename.

## Step 1: Determine session identity

Get the cmux surface and workspace refs:
```bash
cmux identify --no-caller
```

Determine a friendly name:
- If the user provided one, use it
- Otherwise, use the basename of the current working directory (e.g., `curaitor-review`, `sgnipt-research`)

The `from` and `to` fields in Pod envelopes are free-form strings — whatever name you register here is what other sessions will address you by.

## Step 2: Register

```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py register "<name>" "<surface_ref>" "<workspace_ref>"
```

This writes to `~/.claude/handoffs/registry.json`:
```json
{
  "sessions": {
    "<name>": {
      "surface": "surface:NN",
      "workspace": "workspace:NN",
      "cwd": "/path/to/project",
      "registered_at": "ISO-8601",
      "pid": 12345
    }
  }
}
```

## Step 3: Create inbox directory

```bash
mkdir -p ~/.claude/handoffs/inbox/<name>
```

## Step 4: Confirm

```
Registered as "<name>"
  Surface: surface:NN
  Workspace: workspace:NN
  Inbox: ~/.claude/handoffs/inbox/<name>/

Other sessions can now send handoffs with:
  /handoff:send --to <name>

Pods will land as ~/.claude/handoffs/inbox/<name>/<ulid>-<slug>.md
```

## Auto-registration

This skill can also be triggered automatically via a SessionStart hook.
The plugin ships with this hook enabled by default (see `hooks/hooks.json`).

## Rules
- If the name is already registered, update it (session refs change between restarts)
- Validate that the cmux surface actually exists before registering
- If cmux is unavailable, register with name only (file-based handoff still works)
