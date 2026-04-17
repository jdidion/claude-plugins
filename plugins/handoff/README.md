# handoff

AirDrop-style context handoff between Claude Code sessions running in cmux.

## Skills

| Skill | Description |
|-------|-------------|
| `/handoff:send` | Compile context and deliver to another session |
| `/handoff:inbox` | Check for incoming handoffs |
| `/handoff:register` | Register this session for discovery |

## How it works

1. **Register** each session on startup (or auto-register via hook)
2. **Send** a handoff: writes a structured markdown payload + types a prompt into the target session via cmux
3. **Receive** a handoff: the target gets an OS notification + typed prompt, reads the payload, and accepts

### Transport

- **Payload**: Structured markdown files in `~/.claude/handoffs/inbox/<target>/`
- **Doorbell**: `cmux send` types directly into the target session's input buffer
- **Alert**: `cmux notify` sends an OS notification
- **Discovery**: `~/.claude/handoffs/registry.json` maps friendly names to cmux surface refs

### Handoff file format

```markdown
---
from: curaitor-review
to: prism-dev
timestamp: 2026-04-17T02:30:00Z
slug: implement-direnv-scoping
---

## Objective
What needs to be done

## Context
Key decisions, findings, or state the receiver needs

## Files
- path/to/file — description

## Verification
Tests run, results, known issues

## Next Steps
Specific instructions for the receiver

## Open Questions
Anything unresolved
```

## Setup

### Install the plugin

Add to `~/.claude/settings.json`:
```json
{
  "enabledPlugins": {
    "handoff@jdidion-plugins": true
  }
}
```

### Auto-register sessions (optional)

Add a SessionStart hook to `~/.claude/settings.json`:
```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{
        "type": "command",
        "command": "python3 ~/projects/claude-plugins/plugins/handoff/scripts/registry.py auto-register",
        "timeout": 5
      }]
    }]
  }
}
```

## Usage

```
# Register this session
/handoff:register prism-dev

# Send context to another session
/handoff:send "implement direnv per-project scoping" --to curaitor-review

# Check for incoming handoffs
/handoff:inbox

# Accept a handoff
/handoff:inbox accept
```

## Requirements

- cmux (for cross-session delivery)
- Python 3 (for registry script)
- Works without cmux in file-only mode (write payload, print path)

## Future

- Auto-registration via SessionStart hook
- Team checkpoint/resume integration
- Cross-machine handoffs via git or MCP inbox server
