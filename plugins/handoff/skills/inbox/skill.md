# /handoff:inbox — Check for incoming handoffs

Check for handoff files waiting for this session and present them for acceptance.

## Arguments
$ARGUMENTS — Optional: `accept` to accept the most recent handoff, `list` to show all, `clear` to archive processed handoffs.

## Step 1: Identify this session

```bash
python3 $PLUGIN_ROOT/scripts/registry.py whoami
```

If not registered, prompt the user to register first with `/handoff:register`.

## Step 2: Check inbox

```bash
python3 $PLUGIN_ROOT/scripts/registry.py inbox
```

This lists all `.md` files in `~/.claude/handoffs/inbox/<my-name>/`, sorted by timestamp (newest first).

## Step 3: Present handoffs

If no argument or `list`:
```
Inbox: 2 handoffs waiting

1. [2026-04-17T02:30:00] from curaitor-review: "implement direnv per-project scoping"
2. [2026-04-17T01:15:00] from prism-dev: "review sgNIPT VCF filter changes"

Type a number to read, 'accept N' to accept, or 'clear' to archive all.
```

If `accept` or a number:
1. Read the handoff file
2. Print the full payload (objective, context, files, next steps)
3. Ask: "Accept this handoff? (y/n)"
4. If yes: move the file to `~/.claude/handoffs/archive/` and begin working on the objective
5. If no: leave in inbox

If `clear`:
Move all files in inbox to `~/.claude/handoffs/archive/<my-name>/`.

## Rules
- Print the full handoff content before asking for acceptance
- After accepting, begin working on the objective immediately — the context is your starting point
- Do NOT delete handoff files — always move to archive for audit trail
