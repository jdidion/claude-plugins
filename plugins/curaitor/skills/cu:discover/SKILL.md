# /discover — Surface new articles from RSS feeds

Fetch recent articles from configured RSS feeds, evaluate for cross-disciplinary relevance, and route to Obsidian folders.

## Arguments
$ARGUMENTS — Optional: number of days to look back (default 7), or a category filter (e.g., "ai", "genomics").

## Step 1: Load preferences, feeds, and autonomy level

Read from `config/`:
1. `reading-prefs.md` — learned preferences
2. `feeds.yaml` — RSS feed list
3. `accuracy-stats.yaml` — current autonomy level
4. `triage-rules.yaml` — deterministic rules and autonomy overrides

If `feeds.yaml` has no feeds configured, tell the user to export OPML from Feedly or add feeds manually.

**FEEDLY_TOKEN check**: If `.env` is missing `FEEDLY_TOKEN`, surface a one-line warning in the final summary (Step 6) noting that Step 7 will be skipped. Do not block discovery — the token is only needed to mark articles read in Feedly's UI.

## Step 2: Fetch articles from each feed

For each feed in `feeds.yaml`:
1. WebFetch the RSS feed URL
2. Parse article titles, URLs, dates, and descriptions/abstracts
3. Filter to articles within the lookback period (default 7 days)

## Step 3: Deduplicate

Check Obsidian for existing notes **and the Recycle log** with matching URLs. Use `python3 scripts/triage-write.py --dedup-only --urls URL1 URL2 ...` for batch checking — it checks both live notes and `Curaitor/Recycle.md`, and returns `duplicate_from_note` / `duplicate_from_recycle` counts. Exact URL duplicates are immediately recycled — append `- [title](url) (duplicate)` or `(duplicate from Recycle)` to `Curaitor/Recycle.md`. Do NOT create notes for duplicates. A rising `duplicate_from_recycle` count indicates dedup regression — investigate if it exceeds ~5% of inflow.

## Step 4: Evaluate each article

For each new article, evaluate against `reading-prefs.md`.

**Non-text sources**: If a feed entry links to a video or podcast, check for a transcript or show notes in the RSS description. If available, evaluate from that. If not, route to `Curaitor/Review/` as uncertain. Add `media_type: video|podcast` to frontmatter.

- **Summary** (from RSS description/abstract/transcript — do NOT WebFetch full text in unattended mode to save time)
- **Category**: `ai-tooling` | `genomics` | `methods` | `general`
- **Confidence**: `high-interested` | `uncertain` | `high-not-interested`
- **Cross-disciplinary check**:
  - Does this paper introduce a method from another field applicable to cfDNA/genomics?
  - Does this AI tool solve a problem the user faces in bioinformatics pipelines?
  - Is this a novel approach or just incremental work?
- **Slop check**: Does the RSS description read like AI-generated filler? Look for: Tier 1 AI vocabulary (delve, tapestry, landscape, robust, seamless, ecosystem, holistic, nuanced, game-changing), throat-clearing phrases, binary contrasts ("It's not X, it's Y"), significance inflation without specifics. Tag `slop_label: clean|mild|slop|heavy-slop`. Slop articles with no source link → recycle immediately.

## Step 5: Route to Obsidian

Same three-tier routing as `/triage`, with **autonomy-level overrides**:
- **Level 0**: RSS → only Ignored if deterministic rule matches. LLM uncertain → Review.
- **Level 1+**: Standard three-tier routing.

- **High confidence interested** → Obsidian `Curaitor/Inbox/`
- **Uncertain** → Obsidian `Curaitor/Review/`
- **High confidence not interested** → Obsidian `Curaitor/Ignored/`

Note format same as `/triage`, but `source: rss` and include `feed_name` in frontmatter.

## Step 6: Present summary

```
Discovered 42 new articles across 12 feeds:
  5 → Inbox     ★ (titles listed)
  8 → Review    ? (titles listed)
 29 → Ignored   (count only)

Top picks:
1. "Title" — why this is relevant
2. "Title" — why this is relevant
...
```

## Step 7: Mark as read in Feedly

After writing Obsidian notes, mark the discovered articles as read in Feedly so they don't appear as unread in the Feedly UI. Collect all URLs that were just written to Obsidian into a temp file, then run:

```bash
python3 scripts/feedly.py mark-read "$FEEDLY_STREAM_ID" --urls-file /tmp/curaitor-discovered-urls.txt
```

Only run this if `FEEDLY_TOKEN` is set in `.env`. If the token is expired, skip silently and note it in the summary.

## Rules
- Only evaluate based on RSS title/description/abstract — don't WebFetch full articles (too slow for many feeds)
- Always read `reading-prefs.md` first
- Always deduplicate against existing Obsidian notes
- Be terse — summary table, not play-by-play
