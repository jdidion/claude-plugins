# /offload-context — Save session context and compact

Review the current session, preserve important learnings to auto-memory, and compact context.

## Arguments

$ARGUMENTS — Optional: `--no-compact` to skip compaction after saving.

## Workflow

### 1. Gather session state

Run the session summary script to get current git state without spending tokens on tool calls:

```bash
bash <plugin_root>/scripts/session-summary.sh
```

Review the output alongside your conversation history.

### 2. Save learnings to auto-memory

Review what was accomplished in this session. Save anything that would be useful in future conversations using auto-memory (Write to the project memory directory).

What to save, by memory type:

- **feedback**: corrections the user made to your approach, confirmed non-obvious approaches, preferences expressed
- **project**: key decisions, architectural choices, trade-offs made, approaches rejected and why, current state of ongoing work
- **user**: role, expertise, responsibilities learned during the session
- **reference**: external resources, URLs, tool locations discovered

What to skip:

- Anything derivable from the code or git history
- Anything already in CLAUDE.md or existing memory files
- Ephemeral task details specific to this conversation only

### 3. Extract reusable workflows

If any reusable workflows emerged during the session:
- Extract them as new `.claude/commands/*.md` files
- Or update existing commands if behavior changed

### 4. Compact context

Unless `--no-compact` was specified, invoke `/compact` to compress the conversation.
