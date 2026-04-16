# curaitor — AI-Powered Article Discovery, Triage & Review

An article reading assistant that automates discovery and triage while keeping you in the loop for what matters.

## AI-authored content disclosure

When Claude generates content that will be visible to others (Slack posts, topic summaries, article notes) or any content that hasn't been explicitly reviewed and approved by the user, always append:

> *Authored by Claude, pending human review*

This applies to: Slack messages via the `p` verdict, auto-generated topic summaries, and any content posted to external services. It does NOT apply to internal notes (frontmatter, preference updates, accuracy stats) that are only consumed by the system.

## Commands

- `/cu:triage` — Process Instapaper saves: fetch, evaluate, route to Obsidian, archive
- `/cu:discover` — Surface new articles from RSS feeds with semantic relevance evaluation
- `/cu:review` — Interactive review: browse Review queue in cmux browser, discuss, give verdicts
- `/cu:read` — Deep reading: read Inbox articles with full summary, RAG discussion, save or discard
- `/cu:review-ignored` — Check Ignored folder for false negatives
- `/cu:seed-preferences` — One-time: analyze Zotero + Instapaper history to build initial preferences

## Setup

1. Copy `.env.example` to `.env` and fill in your API credentials
2. Install: `pip3 install requests-oauthlib pyyaml`
3. Run `claude` in this directory — all `/cu:*` commands are available
4. Run `/cu:seed-preferences` to initialize from your reading history

## Scripts (reduce token usage)

Use these instead of inline Python — they handle OAuth, parsing, and batch operations:

```bash
# Find the right Python (pixi's python3 may lack deps)
eval "$(bash scripts/find-python.sh)"

# Instapaper API
$CURAITOR_PYTHON scripts/instapaper.py list [--limit N] [--folder archive]
$CURAITOR_PYTHON scripts/instapaper.py text BOOKMARK_ID
$CURAITOR_PYTHON scripts/instapaper.py archive ID [ID ...]

# RSS feeds
$CURAITOR_PYTHON scripts/feeds.py [--days N] [--category CAT]

# Batch write Obsidian notes (faster than individual MCP calls for >10 notes)
echo '[{"path":"Curaitor/Inbox/title.md","frontmatter":{...},"content":"..."}]' | $CURAITOR_PYTHON scripts/write-notes.py

# Pre-fetch article data for review (zero tokens — reads vault directly)
python3 scripts/prefetch-review.py review --include-meta    # Review queue
python3 scripts/prefetch-review.py ignored --days 30 --include-meta  # Ignored
python3 scripts/prefetch-review.py inbox --include-meta     # Inbox

# Workspace setup
bash scripts/setup.sh [review|triage|both]
```

For interactive single-note operations, prefer `mcp__obsidian__write_note` (MCP). For batch triage (>10 articles), use `scripts/write-notes.py`.

## Triage rules

`config/triage-rules.yaml` contains deterministic routing rules that supplement LLM evaluation:
- `inbox_domains`: articles from these domains go straight to Inbox
- `inbox_title_keywords`: title keyword matches → Inbox
- `ignored_title_patterns`: known junk patterns → Curaitor/Ignored
- `source_weights`: Instapaper saves (hand-curated) get higher signal weight than RSS

## Credentials

Load from `.env` in the repo root (gitignored):

```python
from requests_oauthlib import OAuth1Session
import os

creds = {}
env_path = os.path.join(os.path.dirname(os.path.abspath('.')), '.env')
for path in ['.env', os.path.expanduser('~/.instapaper-credentials')]:
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    creds[k] = v
        break

session = OAuth1Session(
    creds['INSTAPAPER_CONSUMER_KEY'],
    client_secret=creds['INSTAPAPER_CONSUMER_SECRET'],
    resource_owner_key=creds['INSTAPAPER_ACCESS_TOKEN'],
    resource_owner_secret=creds['INSTAPAPER_ACCESS_SECRET'],
)
```

### Instapaper API endpoints
- `POST /api/1/bookmarks/list` — list bookmarks (params: folder_id, limit)
- `POST /api/1/bookmarks/get_text` — get article text (params: bookmark_id)
- `POST /api/1/bookmarks/archive` — archive bookmark (params: bookmark_id)

## Obsidian integration

Articles are stored as notes with structured frontmatter. Access via Obsidian MCP tools.

### Folders
All triage folders live under `Curaitor/` in the Obsidian vault:
- **Curaitor/Inbox/** — high-confidence interesting, ready to read
- **Curaitor/Review/** — uncertain, needs human review
- **Curaitor/Ignored/** — triage agent thinks not interesting (machine classification, reviewable for false negatives)
- **Curaitor/Recycle.md** — dismissed articles (simple unordered list of `- [title](url)` links)
- **Curaitor/Archive/** — human-reviewed and dismissed during `/cu:read`, with audit trail in `Curaitor/Archive/Archive.md`
- **Library/** — permanently saved articles from deep read sessions
- **Topics/** — topic notes with linked articles

### Folder semantics and triage signals
- **Curaitor/Ignored/** is written ONLY by triage/discover agents (machine classification). The review agent reads from it (for `/cu:review-ignored`) and moves articles OUT, but NEVER adds to it.
- **Curaitor/Recycle.md** collects dismissed articles as a simple list of links. Articles arrive here from two paths:
  - `/cu:review`: user dismisses an article from Review → **false positive** (triage was wrong to flag it as uncertain/interesting)
  - `/cu:review-ignored`: user confirms an article was correctly ignored → **true negative** (triage was right)
- **Curaitor/Archive/** is written ONLY by `/cu:read` (human decision after deep reading). Contains `Archive.md` with audit trail.

### Triage quality signals
Every human verdict during `/cu:review` and `/cu:review-ignored` provides a signal about triage quality:
- **True positive**: article kept during review (y, !, t, c, b, r, p, skip) — triage was right to flag it for review
- **False positive**: article recycled during review (n) — triage shouldn't have put this in Review. Agent analyzes WHY and updates preferences to decrease future false-positive rate.
- **True negative** (via `/cu:review-ignored`): user confirms article was correctly ignored → reinforces correct triage behavior
- **False negative** (via `/cu:review-ignored`): user rescues a wrongly-ignored article → agent analyzes WHY and updates preferences to decrease future false-negative rate.

**Net signal correction for multi-step paths:**
- **Ignored → Review → Ignored** (rescued then recycled): final signal is **TN** (triage was right to ignore it originally), not FP
- **Review → Ignored → Review** (recycled then rescued): final signal is **TP** (triage was right to flag it originally), not FN

The final disposition determines the signal, not intermediate steps. Check `confidence` and `reviewed_ignored` frontmatter to detect these paths.

### Note format
```markdown
---
title: "Article Title"
url: https://...
source: instapaper
bookmark_id: 12345
date_triaged: 2026-04-04
category: ai-tooling
verdict: read-now
tags: [ai, dev-tools]
---

## Summary
2-3 sentence summary.

## Verdict: Read Now
Why this is worth reading.
```

Note paths use the `Curaitor/` prefix: `Curaitor/Inbox/{sanitized-title}.md`, etc.

## Three-tier confidence routing

Read `config/reading-prefs.md` before every evaluation:
- **High confidence interested** → Obsidian `Curaitor/Inbox/`
- **Uncertain** → Obsidian `Curaitor/Review/`
- **High confidence not interested** → Obsidian `Curaitor/Ignored/`

In unattended mode (cron), NEVER prompt — uncertain always goes to `Curaitor/Review/`.

## Progressive autonomy

The agent earns routing autonomy by demonstrating accuracy. Read `config/accuracy-stats.yaml` at the start of every triage/discover run for the current level.

| Level | Name | Routing behavior |
|-------|------|-----------------|
| **0** | Cold start | Instapaper: never Ignored (Review at worst). RSS: only Ignored if deterministic rule matches. Prompt review-ignored after every run. |
| **1** | Normal | Standard three-tier routing. Remind review-ignored every 14 days. |
| **2** | Confident | Less conservative uncertain threshold. Review-ignored monthly. |
| **3** | Auto-recycle | Known junk patterns auto-recycled. Still routes uncertain to Review. |

Graduation requires rolling precision/recall thresholds + review-ignored passes. Run `python3 scripts/accuracy-metrics.py` to view progress. See `config/triage-rules.yaml` `autonomy_overrides` for per-level routing rules.

After each `/cu:review` or `/cu:review-ignored` session, update `config/accuracy-stats.yaml` with TP/FP/TN/FN signals and check graduation/demotion criteria. Demotion: 3+ false negatives in one review-ignored pass drops a level.

### Duplicate handling

Exact URL duplicates (URL already exists in any vault folder) are immediately recycled — append `- [title](url) (duplicate)` to `Curaitor/Recycle.md`. Never create a note in Ignored for duplicates. Duplicates do not count as triage quality signals.

## CRITICAL: Do not use AskUserQuestion during review

NEVER use AskUserQuestion during `/cu:review` or `/cu:review-ignored`. It only supports 4 options and interrupts text output mid-sentence. Instead:
- Print all text output completely FIRST
- Then print the verdict menu as plain text
- Wait for the user to type their response as free text

## Interactive review

Menu (printed as text, not AskUserQuestion):
```
!:deep-read  ?:discuss  y:inbox  t:topic  c:clip  b:bookmark  r:zotero  p:post  n:recycle  skip  q:quit
```

Users can type inline commands:
- `! compare this to our current approach` — deep read with context
- `? does this support hg38?` — discuss before deciding
- Or bare keys: `y`, `n`, `c`, `r`, `skip`, `q`

### Verdicts
- **!** — Deep read: save permanently (papers→Zotero, others→Library/), fetch full text, interactive RAG discussion, save discussion notes when done
- **?** — Discuss: fetch full text, answer questions, re-show menu when user says "done"
- **y** — Inbox: move to Curaitor/Inbox/, star GitHub repo if detected, add to Tools & Projects catalog
- **c** — Clip: add repo/tool to Tools & Projects catalog, delete article (only shown when repo/tool detected)
- **r** — Zotero: save as reference via Zotero API
- **n** — Recycle: not keeping. Append `- [title](url)` to `Curaitor/Recycle.md`, delete the note. This is a **false positive** — analyze why triage routed this to Review and update preferences to decrease the false-positive rate.
- **skip** — Leave in Curaitor/Review/
- **q** — Quit, show session summary

### GitHub repo detection
Before opening each article, check if the URL or title contains a GitHub/GitLab repo link. If detected:
- Offer to open the repo instead of the article
- On **y**, **!**, or **c**: star via `gh api user/starred/OWNER/REPO -X PUT`
- Add to `Tools & Projects.md` in Obsidian vault root

### Tools & Projects catalog
Maintained at vault root as `Tools & Projects.md`. Organized by category:
```markdown
## Genomics & Bioinformatics
- [Helicase](https://github.com/owner/helicase) — SIMD-vectorized FASTQ/FASTA parsing

## AI & Development Tools
- [beads](https://github.com/steveyegge/beads) — Persistent structured memory for coding agents
```

## cmux browser

For interactive review in [cmux](https://github.com/manaflow-ai/cmux):

```bash
# Open URL in browser pane (returns surface:NN)
cmux browser open "https://example.com"

# Navigate existing surface
cmux browser goto "https://new-url.com" --surface surface:NN

# Wait for load
cmux browser wait --load-state complete --surface surface:NN --timeout-ms 5000

# Get DOM snapshot
cmux browser snapshot --compact --surface surface:NN

# Interact with elements (ref IDs from snapshot)
cmux browser click "REF_ID" --surface surface:NN
cmux browser fill "REF_ID" "value" --surface surface:NN
```

Track `surface:NN` from first open, reuse for all subsequent commands. Do NOT use `cmux browse`.

If cmux is not available, fall back to printing the URL for the user to open manually.

## LinkedIn authentication

Many articles are LinkedIn posts requiring login:
- Use Bitwarden CLI if available: `bw get username/password linkedin.com` (requires BW_SESSION)
- Pre-authenticate at session start if LinkedIn URLs are in the review queue
- User may need to approve 2FA via phone

## Auto-tagging and topic linking

### Tagging
When writing ANY Obsidian note (triage, discover, or review), always generate semantic tags from the article content. Tags should be:
- Lowercase, hyphenated (e.g., `variant-calling`, `ai-agents`, `cfDNA`)
- A mix of broad (`genomics`, `machine-learning`) and specific (`bloom-filters`, `nanopore-basecalling`)
- 3-8 tags per article
- Stored in frontmatter `tags` array

### Topic detection
Before finalizing an article note, search Obsidian for existing topic notes that match the article's tags:
1. Use `mcp__obsidian__search_notes` to find notes tagged with the same terms
2. Look in `Topics/` folder for existing topic notes
3. If matching topics are found, mention them when presenting the article:
   ```
   Related topics: [[Variant Calling Methods]], [[AI-Assisted Development]]
   ```

### Topic linking
When a match is found during `/cu:review`:
- Add the topic names to the article note as `related_topics` in frontmatter
- Add `[[wiki-links]]` to the related topics in the note body
- Offer to append a backlink in the topic note (e.g., under a "## Related Articles" section)

When the user asks to "create a new topic" during review:
1. Create a note in `Topics/{Topic Name}.md` with frontmatter tags
2. Add the current article as the first related article
3. Ask the user for a brief description of the topic scope
4. Search Obsidian for other existing articles that match the topic's tags and offer to link them

### Tag consistency
When generating tags, first check what tags already exist in the vault by scanning recent notes. Prefer existing tags over creating new synonyms (e.g., if `variant-calling` exists, don't create `variant-callers`).

## Preference learning

`config/reading-prefs.md` contains natural language rules. After each review verdict, if the decision reveals a genuinely new pattern, append to `## Learned patterns`:
```
- YYYY-MM-DD: [TP|FP|TN|FN] User [interested in / not interested in] [pattern]. Example: "Title". [analysis of why triage was right/wrong]
```
Signal types:
- **TP** (true positive): article kept during `/cu:review` — reinforce correct triage behavior
- **FP** (false positive): article recycled during `/cu:review` — analyze and correct the over-inclusion pattern
- **TN** (true negative): confirmed ignored during `/cu:review-ignored` — reinforce correct ignore behavior
- **FN** (false negative): rescued during `/cu:review-ignored` — analyze and correct the over-exclusion pattern

Only log informative patterns — not every decision.

## Zotero integration

Saves papers via Zotero's local connector API (`localhost:23119`). Setup:
1. Enable local API in Zotero: Preferences > Advanced > "Allow other applications..."
2. Copy `config/zotero.yaml.example` to `config/zotero.yaml` and set your collection

Helper script (reduces token usage):
```bash
python scripts/zotero.py check                          # is Zotero running?
python scripts/zotero.py collections                    # list collections
python scripts/zotero.py save URL --title T --tags t1,t2 --collection C1
python scripts/zotero.py add-note ITEM_KEY "<p>HTML note</p>"
python scripts/zotero.py search QUERY
```

Paper detection: DOI URLs, bioRxiv, arXiv, nature.com/articles, academic.oup.com, springer.com. Non-papers only saved to Zotero on explicit `r` verdict.

## Non-text sources (videos, podcasts)

When triaging or discovering a video (YouTube, Vimeo) or podcast episode:

1. **Detect media type** from URL: `youtube.com`, `youtu.be`, podcasting platforms, `.mp3`/`.mp4` links
2. **Check for transcript**: YouTube auto-generates transcripts (accessible via WebFetch on the page or transcript APIs); podcast feeds often include show notes or linked transcripts
3. **If transcript available**: use it to generate the summary — evaluate the same way as article text
4. **If no transcript but description/show notes exist**: evaluate from those (treat like an RSS abstract)
5. **If neither**: route to `Curaitor/Review/` as uncertain — the user can decide interactively
6. **Frontmatter**: add `media_type: video` or `media_type: podcast` so review agent knows to expect non-text content

During `/cu:review` deep read (`!`), fetch the transcript for RAG discussion rather than the page HTML.

## PDF reading

When the `pdf-reader` MCP server is available (globally installed), use `read_pdf` for fetching full content from PDF-format papers. This extracts text AND images (figures, tables), which is critical for scientific papers where figures carry key information.

Usage: check if `read_pdf` tool is available. If so, prefer it over WebFetch for PDF URLs (DOI, bioRxiv, arXiv, nature.com, academic.oup.com). If not available, fall back to WebFetch or cmux browser snapshot.

## Feeds

`config/feeds.yaml` lists RSS feeds for `/cu:discover`. Add/remove by editing the file.

## Feedly integration

After `/cu:discover` processes RSS articles, mark them as read in Feedly so they don't pile up as unread.

Helper script:
```bash
python3 scripts/feedly.py profile                         # test auth
python3 scripts/feedly.py list STREAM_ID [--unread-only]  # list entries
python3 scripts/feedly.py mark-read STREAM_ID --urls-file FILE
python3 scripts/feedly.py mark-read STREAM_ID --urls URL1 URL2
```

Stream ID: set `FEEDLY_STREAM_ID` in `.env` (get from your Feedly collection URL)

Auth: `FEEDLY_TOKEN` in `.env`. Token is a JWT from Feedly's web session (`localStorage['feedly.session']`). To refresh: log into Feedly in cmux browser, then extract via `cmux browser eval "JSON.parse(localStorage.getItem('feedly.session')).feedlyToken"`.

## Scheduling (unattended)

```bash
# Triage Instapaper every 6 hours
0 */6 * * * cd $CURAITOR_DIR && claude -p "/cu:triage" --permission-mode bypassPermissions >> ~/curaitor-triage.log 2>&1

# Discover from feeds daily at 6am
0 6 * * * cd $CURAITOR_DIR && claude -p "/cu:discover" --permission-mode bypassPermissions >> ~/curaitor-discover.log 2>&1
```

### Cron authentication

Scheduled jobs need valid API credentials. The cron service auto-sets `SHELL`, `PATH`, and `HOME` and resolves the absolute `claude` path.

- **Anthropic API**: Set `ANTHROPIC_API_KEY` in crontab env. Keys don't expire.
- **AWS Bedrock**: SSO tokens expire (8-12h) and `aws sso login` is interactive. Either refresh SSO manually each day, or create a dedicated IAM user with only `bedrock:InvokeModel` permission and use static keys for cron.
- **Google Vertex**: Set `GOOGLE_APPLICATION_CREDENTIALS` to a service account JSON. Doesn't expire.
