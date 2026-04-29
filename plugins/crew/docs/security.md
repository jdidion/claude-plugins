# Security notes

## Data flow

When you invoke `/crew:review` (optionally with `--local` / `--mr N` / `--pr N`), the plugin sends:

- The diff being reviewed
- A review prompt with instructions
- Any `CLAUDE.md`/`AGENTS.md` project conventions that exist

To these destinations:

| Reviewer | Destination | Transport |
|---|---|---|
| Claude (via Bedrock) | AWS Bedrock, configured region | Already inside your AWS boundary — no new egress |
| Cursor models (GPT, Gemini, Grok, Claude-via-Cursor) | Cursor's routing layer, then the upstream provider (OpenAI for GPT, Google for Gemini, xAI for Grok, Anthropic for Claude) | Egresses to Cursor. Uses your Cursor Enterprise account. |

When OpenAI models become available on AWS Bedrock, GPT will route natively (same "already inside your AWS boundary" treatment as Claude). Until then, all non-Claude reviewers go through Cursor.

## Vendor clearance is your responsibility

Before running this plugin on a given repository, confirm that the vendors in the path (Cursor Enterprise for non-Claude reviewers; your Bedrock provider for Claude) are cleared under your employer's enterprise agreements or your personal usage policy for that code. If you're unsure, ask whoever owns procurement / InfoSec / legal before running it on sensitive code.

## Not covered

- **Regulated or sensitive data.** Enterprise zero-data-retention (ZDR) reduces model-training risk; it does not grant regulatory coverage (e.g. BAA for health data, export-control clearance for ITAR, etc.). Do not run this plugin on diffs that could contain regulated data unless you have verified coverage with each vendor in the path.
- **Trade secrets, unpublished IP, confidential designs.** ZDR isn't the same as a vendor NDA. Treat the prompt + diff as egressing to the vendor's infrastructure even if they don't retain it.

## What the plugin does not do

- It does not store or transmit credentials. Auth is handled by `cursor-agent login`, which uses the OS keychain.
- It does not log prompts or replies anywhere outside the ephemeral `mktemp` workdirs, which are not cleaned up on purpose (so you can audit them if a review looks off). Clean them up manually with `rm -rf /tmp/cursor-run.* /tmp/review-prompt.*` when you want to.
- It does not post to GitLab/GitHub unless you explicitly asked for post-and-monitor mode.
- It does not modify the repo you're reviewing. The Claude reviewer agent has Write and Edit disabled.

## Audit trail

Every reviewer run produces a workdir under `/tmp`:

- `cursor-run.XXXX/` — cursor-agent's raw output, stderr, and extracted reply
- `review-prompt.XXXX/` — the assembled prompt package (instructions, diff, context)
- Merge output is wherever the calling skill wrote it (usually another `mktemp`)

If you need to explain what was sent to a vendor, the prompt package and the raw output are both preserved.
