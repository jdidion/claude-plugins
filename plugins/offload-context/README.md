# offload-context

Save session learnings to auto-memory before context compaction or session end. Works as both a manual skill (`/offload-context`) and automated hooks that fire on PreCompact and SessionEnd.

## How it works

**Manual** (`/offload-context`): Reviews the session, saves learnings to auto-memory, extracts reusable workflows, and compacts context.

**Automated** (hooks):
- **PreCompact**: Injects git state and a reminder into context before compaction, so Claude preserves unsaved learnings during the compact summary.
- **SessionEnd**: Writes a git state snapshot to `~/.claude/sessions/<session_id>.offload.txt` for future session pickup.

Both hooks call `session-summary.sh`, which gathers branch, dirty files, recent commits, and stash count in a single fast shell invocation (no token cost).

## Requirements

- `git` and `jq` on PATH
- Claude Code auto-memory enabled (default)

No dependency on oh-my-claudecode or any other plugin.

## Installation

```
/plugin install offload-context@jdidion-plugins
```

Hooks activate automatically when the plugin is enabled — no manual `settings.json` editing required.

## Usage

### Manual

```
/offload-context              # save learnings + compact
/offload-context --no-compact  # save learnings only
```

### Automated

Offloading happens automatically via bundled hooks:
- Before every context compaction (manual or auto)
- When a session ends

## What gets saved

The skill guides Claude to save:
- **feedback**: corrections, confirmed approaches, preferences
- **project**: decisions, trade-offs, rejected approaches, ongoing work state
- **user**: role, expertise, responsibilities
- **reference**: external resources, URLs, tool locations

It skips anything derivable from code/git, already in CLAUDE.md, or ephemeral to the current conversation.

## Scripts

| Script | Purpose | Used by |
|--------|---------|---------|
| `session-summary.sh` | Gather git state (branch, dirty, commits, stashes) | All hooks + skill |
| `precompact-hook.sh` | Inject state + reminder before compaction | PreCompact hook |
| `session-end-hook.sh` | Persist state snapshot for session resume | SessionEnd hook |
