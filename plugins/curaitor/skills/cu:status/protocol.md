# Protocol: /cu:status

Execution protocol for the curaitor status dashboard. The SKILL.md is the public entry point; this file is the operational detail — read this when running the skill.

## Environment

**Inputs:**
- Obsidian vault (discovered by `scripts/prefetch-review.py` / `scripts/accuracy-metrics.py`)
- `config/accuracy-stats.yaml` — lifetime + rolling-window signals, autonomy level
- `~/curaitor-triage.log`, `~/curaitor-discover.log` — cron output

**Outputs:**
- Human-readable dashboard on stdout. Nothing written to disk. No external calls.

**Tools used:**
- `python3 scripts/prefetch-review.py {review|inbox|ignored}` — zero-token queue counts
- `python3 scripts/accuracy-metrics.py` — precision/recall/graduation
- `python3 scripts/summarize-inbox.py --list` — cache inventory (one line per cached URL)
- `python3 scripts/summarize-inbox.py --stats` — cumulative generation counters
- `tail -1 ~/curaitor-{triage,discover}.log` — last cron timestamp

## Workflow

### Step 1: Gather data

Run the following; capture the output in working memory. Prefer scripts over reading notes directly to keep token usage near-zero.

```bash
# Queue counts (JSON stdout)
python3 scripts/prefetch-review.py review 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Review: {d[\"count\"]}')"
python3 scripts/prefetch-review.py inbox 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Inbox: {d[\"count\"]}')"
python3 scripts/prefetch-review.py ignored 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Ignored: {d[\"count\"]}')"

# Accuracy + autonomy level
python3 scripts/accuracy-metrics.py

# Summary cache coverage (count of cached entries + cumulative stats)
python3 scripts/summarize-inbox.py --list 2>/dev/null | python3 -c "import json,sys; print(f'Cache entries: {len(json.load(sys.stdin))}')"
python3 scripts/summarize-inbox.py --stats 2>/dev/null

# Cron log tails
tail -1 ~/curaitor-triage.log 2>/dev/null
tail -1 ~/curaitor-discover.log 2>/dev/null
```

### Step 2: Print the dashboard

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  CurAItor Status
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Queues:
  Inbox:    356 articles
  Review:    29 articles
  Ignored:   16 articles
  Recycled: 236 entries

Autonomy: Level 1 (Normal)
  Rolling precision: --  (0/50 entries)
  Rolling recall:    --
  Max FP rate: 5%  |  Max FN rate: 5%

Lifetime: 463 signals
  TP: 130  FP: 0  TN: 321  FN: 12

Summary cache:
  Cached: 9 entries (of 10 Inbox articles)
  Avg generation latency: 6.3s
  Last generated: 2026-04-24 14:37 via huihui_ai/gemma-4-abliterated:e4b

Cron:
  Triage:   last ran 2026-04-16 18:00 (every 6h) ✓
  Discover: last ran 2026-04-16 06:00 (daily 6am) ✓

Review-ignored: 1 pass, last 2026-04-13
```

If `--verbose`, also show the last 10 rolling window entries below the dashboard.

### Step 3: Actionable suggestions

Based on the numbers, suggest the next action the user should take. Rules:

| Condition | Suggestion |
|---|---|
| Review > 20 | "Run `/cu:review` — N articles waiting" |
| Review-ignored not run in ≥14 days | "Run `/cu:review-ignored` to check for false negatives" |
| Rolling window < 20 | "Review more articles to build accuracy data" |
| Cron log timestamp outside expected window | "Check cron health — triage/discover may have failed" |
| Cache entries < Inbox count (any) | "`/cu:read` will pre-generate N missing summaries on start" |
| Cache entries > Inbox count + Review count (accumulated cruft) | "Run `scripts/summarize-inbox.py --gc --apply` to reap stale entries" |
| Ignored > 100 with no recent review-ignored | "Run `/cu:review-ignored` — N articles to scan" |

Print at most 2-3 suggestions, in priority order.

## Conventions

- **One screen, no scrolling.** Trim aggressively; hide rolling-window detail behind `--verbose`.
- **Scripts, not notes.** `prefetch-review.py` reads the vault; do not open individual notes via `mcp__obsidian__read_note`.
- **No side effects.** Never write to config or the vault from this skill.
- **Cron timestamps** come from log tails — don't parse crontab directly; the user's crontab may differ from defaults.

## Common Pitfalls

- **Stale precision/recall when rolling window is empty.** Show `--` not `0.0%`. Graduation logic already handles the `< 20` case; don't duplicate that logic here.
- **Empty log files.** A single empty `tail -1` is not diagnostic of cron failure — the log may have just been rotated or a run may be in progress. Only flag cron as unhealthy if the log is genuinely stale (>1 expected interval).
- **Missing vault.** `prefetch-review.py` exits nonzero if it can't find a curaitor-flavored vault. Surface that to the user with a hint to run `/cu:seed-preferences` or point the Obsidian MCP at the right vault.
- **`accuracy-metrics.py --json` vs plain.** Plain output prints a human dashboard; `--json` is for the webapp. This skill uses the plain form — don't switch to `--json` and then format the JSON.
