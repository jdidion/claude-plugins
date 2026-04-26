# Bug report: Dedup leaks in /cu:review and /cu:read

**Date**: 2026-04-26
**Reporter**: Claude (interactive `/cu:read` session)
**Status**: Mitigations shipped in this report; retrospective fix applied to current vault state. Outstanding work below.

## Symptoms observed

During the 2026-04-26 `/cu:read` session on the Inbox, two classes of dedup leaks surfaced:

### 1. Leftover Inbox / Review notes after `t`/`c`/`b` verdicts
Inbox contained three notes whose URLs were **already committed to curated catalogs** from prior sessions:
- `Curaitor/Inbox/FalkorDB graph database as the next step after Karpathy's LLM wiki.md` — repo was starred and the entry was already in `Tools & Projects.md` (Graph Databases & GraphRAG section) from the 2026-04-26 `/cu:review` batch-verdict session. The source note in `Curaitor/Inbox/` was never deleted.
- `Curaitor/Inbox/GenNA Conditional generation of nucleotide sequences guided by natural-language.md` — article was already attached to `Personal/Topics/Variant Annotation.md` (line 173) from a prior session. Source note was never deleted.
- `Curaitor/Inbox/Reading cell division histories from the methylome.md` — URL was already in `Personal/Topics/Journal Club Ideas.md`. Detected by the new `--find-leftovers` scan as the third instance.

Two of the three required an in-session "wait, didn't we already review that?" prompt from the user — the agent presented the article as if it were a fresh read. This is visible friction (user distracted from real decisions) and indicates the `t`/`c`/`b` verdict paths in past sessions ran the attach/star step but skipped the `mcp__obsidian__delete_note` step.

### 2. Recycle.md duplicate appends within a session
During the same session, the agent `n`-recycled two articles and the append wrote bare `- [title](url)` lines to `Curaitor/Recycle.md` via `mcp__obsidian__write_note --mode append`. There was no check for existing entries:
- "Direct RNA sequencing and signal alignment..." was recycled once via `/cu:read` — but it was **already** in Recycle.md line 2 from a prior session. Net effect: same URL on lines 2 and 30.
- "Flow matching for generative modelling..." was recycled at the user's direction, then the user changed their mind and asked to save it to Zotero. The Recycle.md line had to be surgically removed via `Edit` to clean up.

The `cmd_write` path in `scripts/triage-write.py` already had intra-batch dedup logic (lines 400-434) and a `cmd_dedup_recycle` collapser for one-shot cleanup (line 520) — but the interactive `/cu:review` and `/cu:read` verdict paths bypassed both and appended directly through Obsidian MCP.

## Root cause

**The interactive verdict handlers in `skills/cu:review/SKILL.md`, `skills/cu:read/SKILL.md`, and `skills/cu:review-ignored/SKILL.md` documented the recycle append as a raw `mcp__obsidian__write_note --mode append` operation**, with no mention of the dedup tooling that already existed for cron ingest.

There were also **no pre-flight checks at session start** to detect notes whose URLs had already been committed to a Topic, `Tools & Projects.md`, or `Bookmarks.md` but hadn't been deleted from the source folder. The only existing dedup scan (`build_url_index`) was built for *triage-time* ingest dedup, not *post-verdict* cleanup verification.

## Fixes shipped

All in `plugins/curaitor/` on 2026-04-26.

### `scripts/triage-write.py`

Two new subcommands:

- **`--add-to-recycle --url URL [--title T] [--tag TAG]`** — single-entry append that normalizes the URL, checks against the live `Recycle.md` and recent monthly archives via the existing `build_recycle_index`, and skips the write if already recorded. Returns JSON `{status: appended|skipped, ...}` on stdout for skill-layer introspection.
- **`--find-leftovers`** — scans `Curaitor/Inbox` and `Curaitor/Review` for notes whose frontmatter URL is already present in `Personal/Topics/**/*.md`, `Topics/**/*.md`, `Tools & Projects.md`, or `Bookmarks.md`. Returns JSON listing each leftover with the catalog/topic file that already holds it. Safe at every interactive session start; O(notes × curated_files) but bounded by the real vault size.

Also reused the existing `normalize_url` → hash-free match (no host-canonicalization drift) and the `_URL_LINE` regex for frontmatter parsing.

### `skills/cu:review/SKILL.md`

- Added **Step 0.5: Reap leftover notes** between the Level-2 drain and queue load. Runs `--find-leftovers`, deletes each reported note, reports `Reaped N leftover review notes.`
- Replaced every documented `append to Curaitor/Recycle.md` instance (n verdict, post-Slack recycle, recycle-format section) with the `--add-to-recycle` helper command. Added explicit "never `mcp__obsidian__write_note --mode append` directly" warning with reference to the past double-append incident.

### `skills/cu:read/SKILL.md`

- Same **Step 0.5: Reap leftover notes** pre-flight (Inbox only; `/cu:read` doesn't touch Review).
- Replaced the §g.n menu-description and §h.n handler with the `--add-to-recycle` helper command. Same warning.

### `skills/cu:review-ignored/SKILL.md`

- Replaced the Step 1.3 duplicate-ignored recycle and the Step 3 "all good" recycle with the `--add-to-recycle` helper.

## Retrospective cleanup applied

- `/Users/jodidion/Library/CloudStorage/.../Obsidian/Curaitor/Recycle.md` manually de-duplicated (dropped line 32 "Flow matching..." and the duplicate "Direct RNA..." at line 30). `--dedup-recycle --dry-run` now reports 0 duplicates across 30 entries.
- `Curaitor/Inbox/Reading cell division histories from the methylome.md` deleted (already covered by `Personal/Topics/Journal Club Ideas.md`). `--find-leftovers` now reports 0 leftovers.
- NMI flow-matching review saved to Zotero (key `GB3MML3H`) after the accidental double-recycle surfaced that it had never actually been saved to Zotero despite being flagged as Inbox-worthy on 2026-04-22.

## Verification

```bash
python3 scripts/triage-write.py --dedup-recycle --dry-run
# {"would_drop": 0, "unique_urls": 30, ...}

python3 scripts/triage-write.py --find-leftovers
# {"leftover_count": 0, ...}

python3 scripts/triage-write.py --add-to-recycle --url "https://example.com/test-abc123" --title "Test"
# {"status": "appended", ...}

python3 scripts/triage-write.py --add-to-recycle --url "https://example.com/test-abc123" --title "Test"
# {"status": "skipped", "reason": "already in recycle (live or archive)", ...}
```

The helper is idempotent: re-running with the same URL is a no-op. Test entry was removed after verification.

## Outstanding work

These are follow-ups the dev agent should pick up; they are NOT blockers for the dedup leak fix:

1. **Zotero dedup parity.** `scripts/zotero.py save` has no `--add-to-recycle`-style dedup — it will happily create a second Zotero entry for the same URL. If the user re-runs `r` on the same article (e.g. after a mistake-recycle like the flow-matching incident), we get duplicate Zotero items. Same pattern should be applied: `zotero.py save` should query Zotero by URL/DOI first and skip if present, returning `{status: already_saved, item_key: ...}`.

2. **Topic-attach dedup.** `/cu:review` and `/cu:read` currently append to `## Related Articles` in a Topic note without checking if the URL is already linked under that heading. The `--find-leftovers` scan will catch the Inbox-side leftover, but the topic note itself could have the same URL listed twice. Add a helper `triage-write.py --attach-to-topic --url URL --title TITLE --topic "Topic Name" --section "Related Articles"` that reads the topic file, skips the append if the URL is already linked, and writes only on a fresh hit.

3. **Tools & Projects dedup.** Same pattern as topic-attach — the `c` verdict appends to `Tools & Projects.md` under a category heading without dedup. An `--add-to-catalog` helper would close the loop.

4. **Bookmarks.md dedup.** Same pattern, for the `b` verdict.

5. **Pyright warnings surfaced.** Three pre-existing unused-variable warnings in `triage-write.py` (rel_path on line 441, args on line 566, _dirs on line 601) and one new one from this change (_p on line 651, the tuple-unpacking placeholder in the leftover walk). None are bugs; drop when convenient.

6. **Topic file globbing.** `--find-leftovers` currently hardcodes `Personal/Topics` and `Topics` as the topic roots. If the user reorganizes, the scan misses. Read the topic-root from `config/user-settings.yaml` (new key: `topic_roots: ["Personal/Topics", "Topics"]`) with the current hardcoded pair as default.

7. **Rolling-window FIFO trim.** Pre-existing bug carried over from the prior session — `config/accuracy-stats.yaml` rolling_window has grown to ~474 entries but the trim-to-50 logic isn't firing. Blocks L2 graduation. Not related to this dedup work but worth surfacing again so the dev agent can tackle it.

## Design notes for the dev agent

- **Why a single Python helper, not an MCP tool?** The dedup scan needs the full monthly-archive index and frontmatter-only reads for O(10K) notes. That's fast in Python (existing `read_frontmatter_only` + regex) and slow if done through Obsidian MCP per-note. The helper pattern also lets cron jobs reuse the exact same code — no skill-layer divergence.

- **Why scan topic files with a URL regex instead of parsing markdown?** The topic format is inconsistent — some entries are `[title](url)` wiki-links, some are `- [Tool](url) — description`, some inline URLs in prose. A permissive URL regex catches all variants and the false-positive risk (matching an unrelated URL that happens to also be in Inbox frontmatter) is low because we're matching *normalized* URLs, not substrings.

- **Why not delete-on-sight in `--find-leftovers`?** Keeping the scan read-only is safer. The skills invoke delete through `mcp__obsidian__delete_note` (which has confirmPath gates + user visibility) rather than a batch Python delete. A future `--reap` flag could add the write path if the user wants a cron-safe cleanup.
