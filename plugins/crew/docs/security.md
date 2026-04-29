# Security notes

## Data flow

When you invoke `/crew:review` (optionally with `--local` / `--mr N` / `--pr N`), the plugin sends:

- The diff being reviewed
- A review prompt with instructions
- Any `CLAUDE.md`/`AGENTS.md` project conventions that exist

Destinations depend on which backends are configured. Each non-Claude model is routed to a backend via `tools/resolve-backend`:

| Backend | Transport | Egresses to |
|---|---|---|
| (Claude, via the `code-reviewer` agent) | Whatever Claude Code is configured to use (Bedrock, Anthropic API, etc.) | Inside your configured Claude path |
| `cursor` | `cursor-agent` CLI → Cursor's gateway | Cursor's infrastructure, then upstream providers |
| `codex` | `codex` CLI → OpenAI API | OpenAI |
| `gemini` (planned) | `gemini` CLI → Google | Google |
| `ollama` (planned) | local `ollama` daemon | Nothing — runs entirely locally |
| `anthropic-api` (planned) | direct `curl` against `api.anthropic.com` | Anthropic |

Run `tools/resolve-backend --list-available` to see which backends are active on your system, and `tools/resolve-backend <model>` to see where a specific model would route.

## Vendor clearance is your responsibility

Before running this plugin on a repository, confirm that every vendor in the backend chain (Cursor, OpenAI, Google, Anthropic, etc. — whichever backends you have enabled) is cleared under your employer's enterprise agreements or your personal usage policy for that code. If you're unsure, ask whoever owns procurement / InfoSec / legal before running it on sensitive code.

## Not covered

- **Regulated or sensitive data.** Enterprise zero-data-retention (ZDR) reduces model-training risk; it does not grant regulatory coverage (e.g. BAA for health data, export-control clearance for ITAR, etc.). Do not run this plugin on diffs that could contain regulated data unless you have verified coverage with each vendor in the path.
- **Trade secrets, unpublished IP, confidential designs.** ZDR isn't the same as a vendor NDA. Treat the prompt + diff as egressing to the vendor's infrastructure even if they don't retain it.

## What the plugin does not do

- It does not store or transmit credentials. Auth is handled by the backend CLIs themselves (`cursor-agent login`, `codex login`, etc.), which use the OS keychain or dedicated config files.
- It does not log prompts or replies anywhere outside the ephemeral `mktemp` workdirs, which are not cleaned up on purpose (so you can audit them if a review looks off). Clean them up manually with `rm -rf /tmp/cursor-run.* /tmp/codex-run.* /tmp/review-prompt.*` when you want to.
- It does not post to GitLab/GitHub unless you explicitly asked for post-and-monitor mode.
- It does not modify the repo you're reviewing. The Claude reviewer agent has Write and Edit disabled.

## Audit trail

Every reviewer run produces a workdir under `/tmp`:

- `cursor-run.XXXX/` / `codex-run.XXXX/` / etc. — per-backend raw output, stderr, and extracted reply
- `review-prompt.XXXX/` — the assembled prompt package (instructions, diff, context)
- Merge output is wherever the calling skill wrote it (usually another `mktemp`)

If you need to explain what was sent to a vendor, the prompt package and the raw output are both preserved.
