# Protocol: /curaitor:status

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

### Step 0: Drain the level-2 pending queue (if non-empty)

Cron `/curaitor:discover` (headless, via `scripts/discover-cron.py`) writes pending-Claude articles to `Curaitor/Ignored/` with frontmatter `triage_source: pending-claude-review` **and** enqueues them to `~/.curaitor/level2-pending.json`. The Ignored write guarantees the article is visible in the vault even if Claude never drains; the queue entry is the cue for Claude to revisit. Cron `/curaitor:triage` still enqueues through the Claude path (pre-Claude enqueue, ack on success).

Check the queue first:

```bash
python3 scripts/level2-queue.py status
```

If `pending > 0`, drain and process before anything else. Interactive `/curaitor:status`, `/curaitor:review`, `/curaitor:read`, and `/curaitor:review-ignored` sessions all run this step first because the user is already authed in their interactive Claude Code session.

**Safer pattern (peek + ack)** — preferred when any processing is non-trivial:

```bash
python3 scripts/level2-queue.py peek > /tmp/level2-peek.json
# ...process each article, record succeeded URLs to /tmp/processed-urls.txt...
python3 scripts/level2-queue.py ack --urls-file /tmp/processed-urls.txt
```

For each article in the queue:
1. The article has a `_local` object from Gemma 4 (may contain an `error` field if Gemma failed) and a `source` field (`rss` for `/curaitor:discover`, `instapaper` for `/curaitor:triage`).
2. **All cron-queued articles now pre-write to `Curaitor/Ignored/`** under one of these `triage_source` values:
   - `pending-claude-review` — Gemma was uncertain OR a Gemma error; Claude needs to decide.
   - `pending-claude-review-hard-route` — `/curaitor:triage` diverted this article pre-Gemma because its URL is LinkedIn, video, or podcast. Claude must do the URL-specific work (link-mining from post body AND comments for LinkedIn; transcript hunt for video/podcast) before classifying.
3. Locate the existing note via `mcp__obsidian__search_notes` or a frontmatter-URL scan of `Curaitor/Ignored/`:
   - **Hard-routed LinkedIn posts**: use cmux browser snapshot to render the page, extract links from both the post body and the comment thread (LinkedIn authors often drop the primary source link in the first reply to dodge the "external links suppress reach" algorithm). If a high-value source URL is found, re-classify against that URL's content rather than the LinkedIn post itself.
   - **Hard-routed video/podcast**: fetch transcript via YouTube Data API, `yt-dlp --skip-download --write-auto-sub`, or show-notes from the feed. If no transcript is available, keep as Ignored with `triage_source: review-confirmed-no-transcript`.
   - **Otherwise (regular pending-claude-review)**: run the normal Claude evaluation against the article text (already in the note body's `## Summary` field or fetch fresh via WebFetch / Instapaper `bookmarks/get_text`).
4. Apply the verdict in place:
   - **Promote to Inbox/Review**: `mcp__obsidian__move_note` to the target folder, then `mcp__obsidian__update_frontmatter` to overwrite `confidence`/`verdict`/`tags`/`category` and set `triage_source: {source}-cron-claude-revisited` (substitute `discover` or `triage`).
   - **Confirm Ignored**: `mcp__obsidian__update_frontmatter` to set `triage_source: {source}-cron-claude-confirmed` and leave the note in place.
5. Add the URL to `/tmp/processed-urls.txt` as you go; ack at the end.

After processing completes, report to the user with a breakdown:
`Drained N level-2-pending articles: X promoted to Inbox/Review, Y confirmed Ignored, Z hard-routed (LinkedIn/video/podcast).`

The cron paths' pre-write to Ignored means an empty queue is the steady state: if Gemma's high-confidence calls are accurate, Claude doesn't need to revisit anything. The queue only grows when Gemma is uncertain, when Claude-only logic is needed (ai-tooling obsolescence check), or when the source requires browser-side handling (LinkedIn / video / podcast). If queue drain regularly surfaces promotions Gemma→Claude, that's signal to retune Gemma's prompt or promote feed weights.

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

### Step 2.5: Feed weight graduation / demotion surfacing

After the main dashboard, run:

```bash
python3 scripts/accuracy-metrics.py --feed-weight-candidates
```

This reads `lifetime.rss.by_feed` in `accuracy-stats.yaml` and applies
the thresholds documented in `reading-prefs.md` §Feed weights:

- **Graduate 0.3 → 0.6**: ≥20 articles evaluated AND per-feed rolling
  precision ≥40%.
- **Demote (any → 0.1)**: ≥30 articles evaluated AND per-feed rolling
  precision <15%.

If the command prints anything other than "No feed weight changes suggested.",
relay the output verbatim. The user applies the suggested weight changes to
`config/feeds.yaml` manually — there's no auto-apply today because a
curation system shouldn't silently shift its own routing behavior without
explicit human approval.

If the command prints "No feed weight changes suggested." (the common case),
skip this block entirely — don't surface an empty section.

### Step 3: Actionable suggestions

Based on the numbers, suggest the next action the user should take. Rules:

| Condition | Suggestion |
|---|---|
| Review > 20 | "Run `/curaitor:review` — N articles waiting" |
| Review-ignored not run in ≥14 days | "Run `/curaitor:review-ignored` to check for false negatives" |
| Rolling window < 20 | "Review more articles to build accuracy data" |
| Cron log timestamp outside expected window | "Check cron health — triage/discover may have failed" |
| Cache entries < Inbox count (any) | "`/curaitor:read` will pre-generate N missing summaries on start" |
| Cache entries > Inbox count + Review count (accumulated cruft) | "Run `scripts/summarize-inbox.py --gc --apply` to reap stale entries" |
| Ignored > 100 with no recent review-ignored | "Run `/curaitor:review-ignored` — N articles to scan" |

Print at most 2-3 suggestions, in priority order.

## Conventions

- **One screen, no scrolling.** Trim aggressively; hide rolling-window detail behind `--verbose`.
- **Scripts, not notes.** `prefetch-review.py` reads the vault; do not open individual notes via `mcp__obsidian__read_note`.
- **No side effects.** Never write to config or the vault from this skill.
- **Cron timestamps** come from log tails — don't parse crontab directly; the user's crontab may differ from defaults.

## Common Pitfalls

- **Stale precision/recall when rolling window is empty.** Show `--` not `0.0%`. Graduation logic already handles the `< 20` case; don't duplicate that logic here.
- **Empty log files.** A single empty `tail -1` is not diagnostic of cron failure — the log may have just been rotated or a run may be in progress. Only flag cron as unhealthy if the log is genuinely stale (>1 expected interval).
- **Missing vault.** `prefetch-review.py` exits nonzero if it can't find a curaitor-flavored vault. Surface that to the user with a hint to run `/curaitor:seed-preferences` or point the Obsidian MCP at the right vault.
- **`accuracy-metrics.py --json` vs plain.** Plain output prints a human dashboard; `--json` is for the webapp. This skill uses the plain form — don't switch to `--json` and then format the JSON.
