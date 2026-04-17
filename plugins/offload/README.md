# offload

Session memory persistence, prompt logging, and context analysis for Claude Code.

## Features

- **PreCompact hook**: Injects git state + reminder before compaction so Claude preserves unsaved learnings
- **SessionEnd hook**: Persists git state snapshot for future session pickup
- **Prompt logging**: Opt-in JSONL log of all user prompts for trend analysis
- **Manual skills**: `/offload:context`, `/offload:export`, `/offload:summarize`

All hooks activate automatically when the plugin is enabled.

## Requirements

- `git` and `jq` on PATH
- Claude Code auto-memory enabled (default)

No dependency on oh-my-claudecode or any other plugin.

## Installation

```
/plugin install offload@jdidion-plugins
```

## Skills

### /offload:context

Save session learnings to auto-memory and compact context.

```
/offload:context                  # save learnings + compact
/offload:context --no-compact     # save learnings only
/offload:context --enable-prompts # turn on prompt logging
```

### /offload:export

Export the prompt log for external analysis.

```
/offload:export                          # export all (jsonl)
/offload:export --format csv             # csv format
/offload:export --format markdown        # table format
/offload:export --project myapp          # filter by project
/offload:export --since 2026-04-01       # filter by date
/offload:export --session abc123         # filter by session
```

### /offload:summarize

Summarize offloaded context and auto-memory.

```
/offload:summarize                       # global summary
/offload:summarize --session abc123      # specific session
/offload:summarize --project myapp       # specific project
/offload:summarize --prompts             # include prompt analysis
```

## Prompt logging

Prompt logging is **opt-in**. Enable it with `/offload:context --enable-prompts` or manually:

```bash
mkdir -p ~/.claude/plugins/data/offload
echo '{"prompt_logging": true}' > ~/.claude/plugins/data/offload/config.json
```

When enabled, the UserPromptSubmit hook appends each prompt as a JSONL record to `~/.claude/plugins/data/offload/prompts.jsonl`:

```json
{"ts":"2026-04-17T12:00:00Z","sid":"abc123","cwd":"/path/to/project","project":"myproject","prompt":"fix the failing test"}
```

To disable: delete or edit the config file, or set `prompt_logging` to `false`.

## Scripts

| Script | Purpose | Hook |
|--------|---------|------|
| `session-summary.sh` | Gather git state (branch, dirty, commits, stashes) | All |
| `precompact-hook.sh` | Inject state + reminder before compaction | PreCompact |
| `session-end-hook.sh` | Persist state snapshot for session resume | SessionEnd |
| `log-prompt.sh` | Append user prompt to JSONL log | UserPromptSubmit |
| `export-prompts.sh` | Export/filter prompt log | `/offload:export` |
