# /handoff:send — Send context to another Claude Code session

Compile context from the current conversation and deliver it to a target session running in cmux.

## Arguments
$ARGUMENTS — Required: description of what to hand off. Optional: `--to <session-name>` to specify target.

## Step 1: Identify target

If `--to` was specified, look up the session name in `~/.claude/handoffs/registry.json`.

If not specified, list available sessions:
```bash
python3 $PLUGIN_ROOT/scripts/registry.py list
```
Print the list and ask the user to pick one.

If the target session is not registered, check cmux workspaces:
```bash
cmux list-workspaces
```
Offer to send to any cmux workspace by ref.

## Step 2: Compile handoff payload

Gather context from the current conversation. Ask the user what to include if unclear. The payload should contain:

```markdown
---
from: <current session name or workspace ref>
to: <target session name>
timestamp: <ISO-8601>
slug: <kebab-case summary>
---

## Objective
What needs to be done (from user's description or conversation context)

## Context
Key decisions, findings, or state from this session that the receiver needs

## Files
- List of relevant files modified or referenced
- Include paths and brief descriptions

## Verification
- Tests run, results, known issues

## Next Steps
Specific instructions for the receiver

## Open Questions
Anything unresolved that the receiver should be aware of
```

Write the payload to: `~/.claude/handoffs/inbox/<target>/<timestamp>-<slug>.md`

## Step 3: Deliver

Look up the target's cmux surface from the registry:
```bash
python3 $PLUGIN_ROOT/scripts/registry.py get <target>
```

Send an OS notification:
```bash
cmux notify --title "Handoff from $(python3 $PLUGIN_ROOT/scripts/registry.py whoami)" --body "$SLUG"
```

Then type the handoff prompt into the target session:
```bash
cmux send --surface <target-surface> "You have a handoff waiting. Read and act on ~/.claude/handoffs/inbox/<target>/<file>.md — type 'accept' to proceed or 'defer' to skip.\n"
```

## Step 4: Confirm

Print:
```
Handoff sent to <target>:
  File: ~/.claude/handoffs/inbox/<target>/<file>.md
  Notification: sent
  Input: typed into surface:<NN>

The target session has been prompted to accept.
```

## Rules
- Always ask the user to confirm the payload before sending
- Never send without a target — prompt if missing
- If cmux is unavailable, write the file and print the path (manual mode)
- Include enough context that the receiver can act without asking follow-up questions
