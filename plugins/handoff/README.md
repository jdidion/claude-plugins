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

### Handoff file format (Pod v1, Shape A)

Handoffs are [Pod v1](https://github.com/jdidion/curaitor/blob/main/docs/SPEC-pod-envelope.md) envelopes (Shape A — single markdown file with YAML frontmatter):

```markdown
---
pod:
  format: pod
  version: 1
  id: 01KPK44NWKTTDHPNSC6SD2PQ59
  createdAt: 2026-04-17T02:30:00Z
  from: curaitor-review
  to: prism-dev
  payload:
    kind: handoff
    version: 1
  fingerprint: sha256-<hex-of-body>
handoff:
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

Integrity: the `pod.fingerprint` field is the sha256 of the payload body (everything after the closing `---`). Receivers verify it before acting on the handoff.

Idempotency: `pod.id` is a [ULID](https://github.com/ulid/spec). Receivers track seen IDs in `~/.claude/handoffs/seen.json` to avoid re-processing duplicates.

### Backward compatibility

The inbox command still reads old-format files (flat frontmatter with `from`/`to`/`timestamp`/`slug`). These are flagged `[legacy ⚠]` in listings — they can be accepted but cannot have their integrity verified.

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
