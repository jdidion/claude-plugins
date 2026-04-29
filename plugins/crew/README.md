# crew

Multi-provider code review for Claude Code. Runs Claude alongside external model families (GPT, Gemini, Grok — all via Cursor's CLI) in parallel, then merges findings with attribution so you can see which model caught what.

## Why multi-provider?

Same-context self-review suffers from choice-supportive bias — once a model sees its own output, it inflates confidence and defends the original answer (Kumaran et al., *Nature Machine Intelligence* 2026). Different model families trained on different data catch different issues. Three reviewers with attribution beats one reviewer with more thinking.

This plugin is not a replacement for deterministic checks — it runs `lsp_diagnostics` and `ast_grep` pre-gates before any LLM review, and encourages project-specific review templates in `.ci/ai-review/`.

## Skill

| Skill | Trigger | What it does |
|---|---|---|
| `/crew:review` | User asks for review, with optional `--local` / `--mr N` / `--pr N` scope | One command; defaults to incremental review of commits since last run on this branch. With explicit post-and-monitor intent on an MR/PR, posts attributed comments and watches for author responses. Never posts in default mode. |

Three scopes, one command:

- `/crew:review` — incremental (commits since last run; whole repo on first run)
- `/crew:review --local` — staged + unstaged changes only
- `/crew:review --mr 123` or `/crew:review --pr 123` — a specific GitLab MR / GitHub PR

## Agent

- **`crew:code-reviewer`** — Claude's leg of the review. Runs in an isolated context so it can't condition on external reviewers' output. Two-stage review (spec compliance, then code quality), severity-rated findings, clear verdict.

## Default model roster

Three reviewers by default:

1. **Claude** via Bedrock (through the `code-reviewer` agent — no external CLI)
2. **`gpt-5`** via Cursor
3. **`gemini-3.1-pro`** via Cursor

All non-Claude models route through Cursor's enterprise subscription. When OpenAI models land on AWS Bedrock, `gpt-*` will route natively (no Cursor hop); until then, Cursor is the sanctioned path.

Override per-invocation:

```
/crew:review with gpt-5 and grok-4-20-thinking
/crew:review --local with only gemini-3.1-pro
/crew:review --mr 123 with claude-opus-4-7-thinking-high and gpt-5
```

Deep mode reports every finding instead of capping at 10:

```
/crew:review --deep
/crew:review --mr 123 --deep post and monitor
```

## Requirements

- `cursor-agent` CLI on PATH, authenticated (`cursor-agent login`)
- `glab` CLI for MR reviews / `gh` CLI for PR reviews
- `jq` and `git`
- A Claude Code session with access to `lsp_diagnostics` and `ast_grep_search` tools (most standard installations)

See `docs/security.md` for the data-egress story.

## Installation

From a Claude Code session:

```
/plugin marketplace add jdidion/claude-plugins
/plugin install crew@jdidion-plugins
```

## Attribution tags

Findings in the merged report are tagged by which reviewers flagged them:

- `[All]` — every reviewer
- `[<A>+<B>]` — two-of-three overlap
- `[<reviewer>]` — single-source
- `[<reviewer> — likely false positive: <reason>]` — single-source findings that, on reading the source, the orchestrator judged wrong. Tagged rather than silently dropped.

Overlap detection is heuristic (same file + shared non-stopword keywords). Not perfect — prefer to read the full `merged.md` when attribution matters.

## Tools

| Tool | Purpose |
|---|---|
| `tools/assemble-review-prompt` | Build a shared review prompt package (instructions + context + diff). Supports `--deep`. |
| `tools/cursor-run` | Invoke `cursor-agent` in batch mode. |
| `tools/cursor-adapt` | Create/cleanup Cursor scaffolding (AGENTS.md symlink, `.cursor/mcp.json` translation). |
| `tools/merge-findings` | Parse per-reviewer replies, detect overlap clusters, emit a unified report. |
| `tools/snapshot-diff` | First-run incremental mode helper: emit a whole-tree "all files as new" diff so reviewers see current state. |

## Credits

The two-stage review structure and severity-rated findings pattern are adapted from [oh-my-claudecode's code-reviewer agent](https://github.com/nicobailon/oh-my-claudecode). Deterministic pre-gates borrow from [Semgrep's security skills](https://github.com/semgrep/skills). Aspect-based review aspects and the numbered finding format are inspired by Claude's official `pr-review-toolkit` plugin and [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills).
