---
name: inbox
description: Check for incoming Pod-envelope handoffs addressed to this session. Use when the user asks to check inbox, see pending handoffs, or accept a handoff. Verifies fingerprints and tracks seen pod IDs for idempotency.
---

# /handoff:inbox — Check for incoming handoffs

Check for handoff pods waiting for this session, verify their fingerprints, and present them for acceptance.

## Arguments
$ARGUMENTS — Optional: `accept` to accept the most recent handoff, `list` to show all, `clear` to archive processed handoffs.

## Step 1: Identify this session

```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py whoami
```

If not registered, prompt the user to register first with `/handoff:register`.

## Step 2: List inbox

```bash
python3 $CLAUDE_PLUGIN_ROOT/scripts/registry.py inbox
```

Returns JSON with one entry per file, including:
- `id` — ULID from the Pod envelope (empty string for legacy files)
- `format` — `"pod"`, `"legacy"`, or `"invalid"`
- `fingerprint_ok` — true if sha256(body) matches `pod.fingerprint`
- `already_seen` — true if this pod ID is in `~/.claude/handoffs/seen.json`

## Step 3: Present handoffs

If no argument or `list`:
```
Inbox: 2 handoffs waiting

1. [2026-04-17T02:30:00Z] from curaitor-review: "implement direnv per-project scoping" [pod ✓]
2. [2026-04-17T01:15:00Z] from prism-dev: "review sgNIPT VCF filter changes" [legacy ⚠]

Type a number to read, 'accept N' to accept, or 'clear' to archive all.
```

Marks:
- `[pod ✓]` — Pod envelope with verified fingerprint
- `[pod ✗]` — Pod envelope but fingerprint mismatch (REJECT)
- `[legacy ⚠]` — Old pre-Pod format (accept at your own risk)
- `[seen]` — already accepted previously (duplicate delivery)

### Rejecting tampered pods

If `fingerprint_ok` is false AND `format` is `"pod"`, **reject the handoff**:
- Do not present it for acceptance
- Warn the user: "Pod <id> failed fingerprint verification — body does not match envelope. Rejecting."
- Leave the file in place; do not archive

### Duplicate detection

If `already_seen` is true, warn before re-accepting:
"Pod <id> was already processed on <seen_at>. Re-accept anyway? (y/n)"

## Step 4: Accept a handoff

When the user accepts (either `accept`, `accept N`, or picks a number then confirms):

1. Read the pod file and re-verify with `pod.py verify` — abort if verification fails
2. Print the full body (objective, context, files, next steps)
3. Ask: "Accept this handoff? (y/n)"
4. If yes:
   - Mark the pod ID as seen:
     ```bash
     python3 $CLAUDE_PLUGIN_ROOT/scripts/pod.py seen-mark <pod-id> --path <pod-path>
     ```
   - Move the file to `~/.claude/handoffs/archive/<my-name>/`
   - Begin working on the objective
5. If no: leave in inbox

For legacy files (no pod ID), skip the seen-mark step.

## Step 5: Clear

If `clear`:
Move all files in inbox to `~/.claude/handoffs/archive/<my-name>/`. Do not mark them seen — `clear` is a bulk archive, not an accept.

## Rules
- Always verify fingerprints on pod files before presenting content
- Never act on a tampered pod
- Warn about duplicates but let the user decide
- After accepting, begin working on the objective immediately — the body is your starting point
- Do NOT delete handoff files — always move to archive for audit trail
