# /offload:context — Save session context and compact

Review the current session, preserve important learnings to auto-memory, and compact context.

## Arguments

$ARGUMENTS — Optional: `--no-compact` to skip compaction after saving, `--enable-prompts` to turn on prompt logging.

## Workflow

### 0. Configure prompt logging (if requested)

If `--enable-prompts` is passed, create or update the config file:

```bash
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/offload}"
mkdir -p "$DATA_DIR"
echo '{"prompt_logging": true}' > "$DATA_DIR/config.json"
```

### 1. Gather session state

Run the session summary script:

```bash
bash <plugin_root>/scripts/session-summary.sh
```

### 2. Save learnings to auto-memory

Review what was accomplished. Save anything useful for future conversations using auto-memory (Write to the project memory directory).

What to save, by memory type:

- **feedback**: corrections the user made, confirmed non-obvious approaches, preferences
- **project**: key decisions, architectural choices, trade-offs, rejected approaches and why
- **user**: role, expertise, responsibilities learned
- **reference**: external resources, URLs, tool locations discovered

What to skip:

- Anything derivable from the code or git history
- Anything already in CLAUDE.md or existing memory files
- Ephemeral task details specific to this conversation only

### 3. Extract reusable workflows

If reusable workflows emerged during the session:
- Extract them as new `.claude/commands/*.md` files
- Or update existing commands if behavior changed

### 4. Compact context

Unless `--no-compact` was specified, invoke `/compact` to compress the conversation.
