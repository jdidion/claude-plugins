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

**FEEDLY_TOKEN check**: If `~/projects/claude-plugins/plugins/curaitor/.env` is missing `FEEDLY_TOKEN`, surface a one-line warning in the final summary (Step 6) noting that Step 7 will be skipped. Do not block discovery — the token is only needed to mark articles read in Feedly's UI.

## Step 2: Fetch articles from each feed

For each feed in `feeds.yaml`:
1. WebFetch the RSS feed URL
2. Parse article titles, URLs, dates, and descriptions/abstracts
3. Filter to articles within the lookback period (default 7 days)

## Step 3: Deduplicate

Check Obsidian for existing notes **and the Recycle log** with matching URLs. Use `python3 scripts/triage-write.py --dedup-only --urls URL1 URL2 ...` for batch checking — it checks both live notes and `Curaitor/Recycle.md`, and returns `duplicate_from_note` / `duplicate_from_recycle` counts. Exact URL duplicates are immediately recycled — append `- [title](url) (duplicate)` or `(duplicate from Recycle)` to `Curaitor/Recycle.md`. Do NOT create notes for duplicates. A rising `duplicate_from_recycle` count indicates dedup regression — investigate if it exceeds ~5% of inflow.

## Step 3.5: Optional local-model pre-pass

If `config/user-settings.yaml:local_triage.enabled` is true, pipe the deduped article list through the local pre-pass before LLM evaluation:

```bash
echo '[...articles...]' | python3 scripts/local-triage.py
```

The script is a pass-through no-op when `local_triage.enabled` is false (the default). When enabled, it augments each article with a `_local` object containing the local model's `confidence`/`verdict`/`category`/`slop_label`/`tags`/`summary` plus a `skip` boolean.

Articles with `_local.skip == true` (strict mode: the local model confidently tagged them `high-not-interested`) route straight to `Curaitor/Ignored/` with frontmatter `triage_source: local-model` and `local_model: <tag>`. **Do NOT re-evaluate these with Claude** — that would defeat the point of the pre-pass.

All other articles (including `_local.skip == false` and any articles where the local model errored out) continue to Step 4 normal Claude evaluation.

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

Only run this if `FEEDLY_TOKEN` is set in `~/projects/claude-plugins/plugins/curaitor/.env`.

**Token expiry handling** — behavior depends on execution mode:

- **Interactive mode** (user ran the skill manually): if the Feedly API returns 401/token-expired, **pause** and tell the user how to refresh the token. The token lives in Feedly's browser localStorage — instruct them to:
  1. Open [feedly.com](https://feedly.com) while signed in
  2. Open devtools (Cmd+Opt+I / Ctrl+Shift+I) → Console
  3. Run `JSON.parse(localStorage.getItem('feedlyDevAccessToken') || localStorage.getItem('auth.access_token'))` (key name varies; try both)
  4. Copy the resulting string into `FEEDLY_TOKEN=...` in `~/projects/claude-plugins/plugins/curaitor/.env`
  5. Re-run `/cu:discover`

- **Cron mode** (non-interactive): skip silently, log one line `FEEDLY_TOKEN expired on YYYY-MM-DD — skip mark-read step` to stderr, and continue. Do not block the pipeline.

**Interactive vs cron detection**: check the env var `CURAITOR_CRON`. If `CURAITOR_CRON=1` (cron wrappers should set this), use cron-mode behavior. Otherwise assume interactive. No fallback to TTY detection — the env var is the single source of truth. If `CURAITOR_CRON` is unset in an ambiguous context, **default to cron-safe (non-blocking) behavior** to avoid wedging an unattended run.

## Step 8: Suggest next action

After the summary, check the Review queue (`Curaitor/Review/`). If non-empty, print a single line: `Next: run /cu:review — N articles waiting` (where N is the count of notes in the folder). If the Review queue is empty, print nothing. Do **not** auto-invoke `/cu:review` — this is a hint only.

## Rules
- Only evaluate based on RSS title/description/abstract — don't WebFetch full articles (too slow for many feeds)
- Always read `reading-prefs.md` first
- Always deduplicate against existing Obsidian notes
- Be terse — summary table, not play-by-play
