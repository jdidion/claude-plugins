# /cu:status — CurAItor status dashboard

Quick overview of queue counts, cron health, accuracy metrics, and recent activity.

## Arguments
$ARGUMENTS — Optional: `--verbose` for full detail including rolling window entries.

## Step 1: Gather data

Collect all status information using scripts and vault reads (minimize token usage):

```bash
# Queue counts (zero tokens)
python3 scripts/prefetch-review.py review 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Review: {d[\"count\"]}')"
python3 scripts/prefetch-review.py inbox 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Inbox: {d[\"count\"]}')"
python3 scripts/prefetch-review.py ignored 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Ignored: {d[\"count\"]}')"

# Accuracy metrics
python3 scripts/accuracy-metrics.py

# Cron logs — last run timestamps
tail -1 ~/curaitor-triage.log 2>/dev/null
tail -1 ~/curaitor-discover.log 2>/dev/null
```

## Step 2: Present status

Print a compact dashboard:

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

Cron:
  Triage:   last ran 2026-04-16 18:00 (every 6h) ✓
  Discover: last ran 2026-04-16 06:00 (daily 6am) ✓

Review-ignored: 1 pass, last 2026-04-13
```

If `--verbose`, also show the last 10 rolling window entries.

## Step 3: Actionable suggestions

Based on the status, suggest next actions:

- Review queue > 20: "Run `/cu:review` — 29 articles waiting"
- Review-ignored not run in 14+ days: "Run `/cu:review-ignored` to check for false negatives"
- Rolling window < 20: "Review more articles to build accuracy data"
- Cron not run in expected window: "Check cron health — triage may have failed"
- Ignored > 100 with no recent review-ignored: "Run `/cu:review-ignored` — 16 articles to scan"

## Rules
- Keep output compact — one screen, no scrolling
- Use scripts for data gathering where possible (save tokens)
- Don't read individual articles — just counts and metadata
