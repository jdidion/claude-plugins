---
name: send
description: Send context to another Claude Code session as a Pod-envelope handoff. Use when the user asks to hand off to another session, send context across sessions, or ship current state to a teammate's Claude session.
---

# /handoff:send — Send context to another Claude Code session

Compile context from the current conversation and deliver it to a target session running in cmux. The payload is wrapped in a Pod v1 envelope (Shape A — markdown with YAML frontmatter), providing fingerprint integrity and ULID-based idempotency.

## Arguments
$ARGUMENTS — Required: description of what to hand off. Optional: `--to <session-name>` to specify target.

## Step 1: Identify target

If `--to` was specified, look up the session name in `~/.claude/handoffs/registry.json`.

If not specified, list available sessions:
```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py list
```
Print the list and ask the user to pick one.

If the target session is not registered, check cmux workspaces:
```bash
cmux list-workspaces
```
Offer to send to any cmux workspace by ref.

## Step 2: Compose the handoff body

Gather context from the current conversation. Ask the user what to include if unclear. Write the body (no frontmatter — pod.py adds the envelope) to a temp file:

```markdown
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

Save it to e.g. `/tmp/handoff-body-<slug>.md`.

## Step 3: Wrap in Pod envelope and drop in inbox

```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/pod.py compile \
  --from "$(python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py whoami)" \
  --to "<target-name>" \
  --slug "<kebab-case-slug>" \
  --body-file /tmp/handoff-body-<slug>.md
```

This writes the pod to `~/.claude/handoffs/inbox/<target>/<ulid>-<slug>.md` with:
- `pod.format: pod`, `pod.version: 1`, `pod.id: <ULID>`, `pod.createdAt`, `pod.from`, `pod.to`
- `pod.payload.kind: handoff`, `pod.payload.version: 1`
- `pod.fingerprint: sha256-<hex>` over the body bytes
- `handoff.slug: <slug>`

The script prints the pod ID and path — capture them for Step 4.

## Step 4: Deliver

Look up the target's cmux surface from the registry:
```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py get <target>
```

Send an OS notification:
```bash
cmux notify --title "Handoff from $(python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py whoami)" --body "<slug>"
```

Then type the handoff prompt into the target session:
```bash
cmux send --surface <target-surface> "You have a handoff waiting. Read and act on <pod-path> — type 'accept' to proceed or 'defer' to skip.\n"
```

## Step 5: Confirm

Print:
```
Handoff sent to <target>:
  Pod ID: <ulid>
  File:   <pod-path>
  Fingerprint: sha256-<hex>
  Notification: sent
  Input: typed into surface:<NN>

The target session has been prompted to accept.
```

## Rules
- Always ask the user to confirm the body before compiling the pod
- Never send without a target — prompt if missing
- If cmux is unavailable, compile the pod and print the path (manual mode)
- Include enough context that the receiver can act without asking follow-up questions
- The ULID in the filename provides natural sort order and uniqueness
