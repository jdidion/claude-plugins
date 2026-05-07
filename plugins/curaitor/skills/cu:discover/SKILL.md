# /discover — Surface new articles from RSS feeds (interactive only)

Fetch recent articles from configured RSS feeds, evaluate for cross-disciplinary relevance, and route to Obsidian folders.

**Cron no longer invokes this skill.** Scheduled runs go through the headless orchestrator `scripts/discover-cron.py`, which doesn't require Claude auth and performs all of steps 1–5 deterministically via Gemma 4 + `triage-write.py`. This skill is now **interactive-only** — call it when you want Claude's judgment on borderline articles as well as Gemma's, or when you want to manually override the cron schedule.

## Arguments
$ARGUMENTS — Optional: number of days to look back (default 7), or a category filter (e.g., "ai", "genomics").

## Relationship to the headless cron path

`scripts/discover-cron.py` already routes confidently-classified articles (Gemma high-interested → Inbox, high-not-interested or hedged-skip → Ignored, weight=0.1 demoted-feed uncertain → Ignored). Anything Gemma is **uncertain** about lands in `Curaitor/Ignored/` with `triage_source: pending-claude-review` frontmatter AND is enqueued to level-2 so an interactive session (this one) can promote it later via the standard queue-drain path in `skills/cu:status/protocol.md` §Step 0.

That means the interactive skill has two valid use cases:
1. **Ad-hoc manual discover** outside the 6am cron window.
2. **Judgment-layer pass** over cron's output — promote items Gemma routed to Ignored-with-pending-claude-review, or demote low-quality Inbox hits Gemma landed confidently.

## Step 1: Load preferences, feeds, and autonomy level

Read from `config/`:
1. `reading-prefs.md` — learned preferences
2. `feeds.yaml` — RSS feed list
3. `accuracy-stats.yaml` — current autonomy level
4. `triage-rules.yaml` — deterministic rules and autonomy overrides

If `feeds.yaml` has no feeds configured, tell the user to export OPML from Feedly or add feeds manually.

## Step 2: Fetch articles from each feed

Use `scripts/feeds.py --days N` rather than WebFetch — it handles the RSS / Feedly / OpenAlex backend dispatcher and per-feed canonicalization already.

## Step 3: Deduplicate

Check Obsidian for existing notes **and the Recycle log** with matching URLs. Use `python3 scripts/triage-write.py --dedup-only --urls URL1 URL2 ...` — it checks both live notes and `Curaitor/Recycle.md` (plus recent monthly archives), and returns `duplicate_from_note` / `duplicate_from_recycle` counts.

Exact URL duplicates are immediately recycled — append `- [title](url) (duplicate)` or `(duplicate from Recycle)` to `Curaitor/Recycle.md`. Do NOT create notes for duplicates.

The `duplicate_from_recycle` count is **expected to be high** (~60%+ of inflow) once batch-recycle sessions have populated the Recycle log. The old "5% watermark → regression" comment was calibrated before batch-recycle existed and no longer applies. Only treat a rising `duplicate_from_note` count as a dedup regression signal.

## Step 3.5: Optional local-model pre-pass

If `config/user-settings.yaml:local_triage.enabled` is true, pipe the deduped article list through the local pre-pass before LLM evaluation:

```bash
echo '[...articles...]' | python3 scripts/local-triage.py
```

Articles with `_local.skip == true` route to `Curaitor/Ignored/` with frontmatter `triage_source: local-model` and `local_model: <tag>`. All other articles fall through to Step 4.

## Step 4: Evaluate each article

For each new article, evaluate against `reading-prefs.md`.

**Non-text sources**: If a feed entry links to a video or podcast, check for a transcript or show notes in the RSS description. If available, evaluate from that. If not, route to `Curaitor/Review/` as uncertain. Add `media_type: video|podcast` to frontmatter.

- **Summary** (from RSS description/abstract/transcript)
- **Category**: `ai-tooling` | `genomics` | `methods` | `general`
- **Confidence**: `high-interested` | `uncertain` | `high-not-interested`
- **Cross-disciplinary check**:
  - Does this paper introduce a method from another field applicable to cfDNA/genomics?
  - Does this AI tool solve a problem the user faces in bioinformatics pipelines?
- **Slop check**: Tag `slop_label: clean|mild|slop|heavy-slop`. Slop articles with no source link → recycle immediately.

## Step 5: Route to Obsidian

Three-tier routing with autonomy overrides:
- **Level 0**: RSS → only Ignored if deterministic rule matches. LLM uncertain → Review.
- **Level 1+**: Standard three-tier routing.

- **High confidence interested** → `Curaitor/Inbox/`
- **Uncertain** → `Curaitor/Review/`
- **High confidence not interested** → `Curaitor/Ignored/`

Note format same as `/triage`, but `source: rss` and include `feed_name` in frontmatter.

## Step 6: Present summary

```
Discovered 42 new articles across 12 feeds:
  5 → Inbox     ★ (titles listed)
  8 → Review    ? (titles listed)
 29 → Ignored   (count only)
```

## Step 7: Suggest next action

After the summary, check the Review queue (`Curaitor/Review/`). If non-empty, print a single line: `Next: run /cu:review — N articles waiting`. Do **not** auto-invoke `/cu:review` — this is a hint only.

## Rules
- Only evaluate based on RSS title/description/abstract — don't WebFetch full articles
- Always read `reading-prefs.md` first
- Always deduplicate against existing Obsidian notes
- Be terse — summary table, not play-by-play
- Feedly mark-read is deprecated (feeds were removed from Feedly in favor of the Feedly fetch_via backend); no step for it.
