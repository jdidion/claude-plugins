# /offload:summarize — Summarize offloaded context

Summarize session offload snapshots and auto-memory, either globally or for a specific session/project.

## Arguments

$ARGUMENTS — Optional scope:
- `--session SID` — summarize a specific session's offload snapshot
- `--project NAME` — summarize all sessions for a project
- `--prompts` — include prompt log analysis in the summary
- (no args) — global summary across all projects

## Workflow

### 1. Gather offload snapshots

```bash
ls ~/.claude/sessions/*.offload.txt 2>/dev/null
```

If `--session` is specified, read just that file. If `--project` is specified, filter by matching `cwd:` lines. Otherwise read all.

### 2. Gather auto-memory

Read the project memory index and relevant memory files:

```bash
cat <memory_dir>/MEMORY.md
```

Where `<memory_dir>` is the project-specific memory directory under `~/.claude/projects/`.

### 3. Analyze prompt log (if --prompts)

```bash
bash <plugin_root>/scripts/export-prompts.sh --format jsonl [--project NAME] [--session SID]
```

Look for:
- Total prompt count and timespan
- Repeated/rephrased prompts (retries)
- Correction patterns ("no", "not that", "undo", "actually")
- Average prompts per session

### 4. Synthesize summary

Produce a concise summary covering:
- **Sessions**: count, date range, projects touched
- **Key decisions**: from memory files (feedback + project types)
- **Active work**: ongoing tasks and their state
- **Prompt patterns** (if `--prompts`): retry rate, correction frequency, common themes
