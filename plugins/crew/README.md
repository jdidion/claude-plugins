# crew

Multi-provider code review for Claude Code. Runs Claude alongside external model families (GPT, Gemini, Grok, local models, etc.) in parallel through pluggable backends, then merges findings with attribution so you can see which model caught what.

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

1. **Claude** — via the `code-reviewer` agent (no external CLI; uses whatever backend Claude Code is configured for — Bedrock, Anthropic API, etc.)
2. **`gpt-5.2`** — routed to the best available backend
3. **`gemini-3.1-pro`** — routed to the best available backend

Override per-invocation:

```
/crew:review with gpt-5.2 and grok-4-20-thinking
/crew:review --local with only gemini-3.1-pro
/crew:review --mr 123 with claude-opus-4-7-thinking-high and gpt-5.2
```

Override defaults via `~/.config/crew/config.toml`:

```toml
[defaults]
roster = ["claude", "gpt-5.1", "gemini-3.2-pro"]
```

Deep mode reports every finding instead of capping at 10:

```
/crew:review --deep
/crew:review --mr 123 --deep post and monitor
```

## Backends

Non-Claude models run through pluggable backend scripts at `tools/backends/<name>`. Each has the same interface:

```
backends/<name> --prompt-file <path> [--model <id>] [--workspace <path>]
```

Prints `WORKDIR=<path>` on stdout and writes `reply.txt` inside the workdir.

**Shipped:**

| Backend | Status | Required binary | Notes |
|---|---|---|---|
| `cursor` | Full | `cursor-agent` | Hosts GPT, Gemini, Grok, Claude under one enterprise subscription |
| `codex` | Stub (experimental) | `codex` | OpenAI Codex CLI. CLI shape unverified — help wanted |

**Planned** (help wanted — see the repo's issues): `gemini`, `ollama`, `anthropic-api`.

### Routing

Per-model routing is decided by `tools/resolve-backend <model-id>`. Resolution order:

1. User config at `~/.config/crew/config.toml` under `[model_routing]` (glob patterns, first match wins)
2. Built-in prefix table (see `tools/resolve-backend` header for the current list)
3. Fallback to `cursor` if installed — Cursor's gateway handles most model families

The resolver picks the first backend in each list whose CLI is on PATH. Users with `cursor-agent` installed get correct behavior for GPT, Gemini, Grok, and Claude without any configuration.

Run `tools/resolve-backend --list-available` to see detected backends.

### Configuration

All optional. `~/.config/crew/config.toml`:

```toml
[defaults]
roster = ["claude", "gpt-5.2", "gemini-3.1-pro"]

[model_routing]
"gpt-*" = "codex"              # explicit — codex only
"gemini-*" = ["gemini", "cursor"]  # try gemini first, fall back to cursor
"claude-*" = "anthropic-api"

[backends.codex]
# command = "/opt/homebrew/bin/codex"   # PATH override if needed
```

## Requirements

- At least one backend CLI on PATH (see above). `cursor-agent` is the broadest; install whichever you have access to.
- `glab` CLI for MR reviews / `gh` CLI for PR reviews
- `jq` and `git`
- Python 3.10+ (3.11+ reads TOML natively; older: `pip install tomli`)
- A Claude Code session with access to `lsp_diagnostics` and `ast_grep_search` tools

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
| `tools/resolve-backend` | Pick the backend script for a given model ID |
| `tools/assemble-review-prompt` | Build a shared review prompt package (instructions + context + diff). Supports `--deep`. |
| `tools/backends/<name>` | Invoke a specific CLI in batch mode. Same interface across all backends. |
| `tools/cursor-adapt` | Create/cleanup Cursor scaffolding (AGENTS.md symlink, `.cursor/mcp.json` translation). Only used when the cursor backend is in the roster. |
| `tools/merge-findings` | Parse per-reviewer replies, detect overlap clusters, emit a unified report. |
| `tools/snapshot-diff` | First-run incremental mode helper: emit a whole-tree "all files as new" diff. |
| `tools/validate-roster` | Parse-time check that each roster model is still offered by its resolved backend. Shared between `/crew:review` §4a and `/crew:market` §2. |

## Credits

The two-stage review structure and severity-rated findings pattern are adapted from [oh-my-claudecode's code-reviewer agent](https://github.com/nicobailon/oh-my-claudecode). Deterministic pre-gates borrow from [Semgrep's security skills](https://github.com/semgrep/skills). Aspect-based review aspects and the numbered finding format are inspired by Claude's official `pr-review-toolkit` plugin and [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills).
