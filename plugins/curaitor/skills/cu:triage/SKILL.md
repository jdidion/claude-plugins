# /triage — Process Instapaper saves

Fetch unread Instapaper bookmarks, evaluate each article, route to Obsidian folders, and archive in Instapaper.

## Arguments
$ARGUMENTS — Optional: specific URL(s) to triage manually. If empty, fetch from Instapaper API.

## Step 1: Load preferences and autonomy level

Read from `config/`:
1. `reading-prefs.md` — learned preferences that guide confidence routing
2. `accuracy-stats.yaml` — current autonomy level and accuracy metrics
3. `triage-rules.yaml` — deterministic rules and autonomy overrides for the current level

**Autonomy routing overrides** (from `triage-rules.yaml` `autonomy_overrides`):
- **Level 0**: Instapaper articles → never Ignored (Review at worst). RSS → only Ignored if a deterministic rule matches.
- **Level 1+**: Standard three-tier routing for both sources.

## Step 2: Fetch bookmarks from Instapaper

Source credentials from `~/.instapaper-credentials`, then authenticate and list bookmarks.

If no access token exists yet, do the xAuth token exchange first:

```bash
source ~/.instapaper-credentials
# xAuth token exchange (one-time, save tokens to ~/.instapaper-credentials)
curl -s -X POST "https://www.instapaper.com/api/1/oauth/access_token" \
  --user "$INSTAPAPER_CONSUMER_KEY:$INSTAPAPER_CONSUMER_SECRET" \
  -d "x_auth_username=YOUR_EMAIL&x_auth_password=YOUR_PASSWORD&x_auth_mode=client_auth"
```

If tokens already exist, list unread bookmarks:

```bash
source ~/.instapaper-credentials
# Use OAuth 1.0a signed request to list bookmarks
# The response includes bookmark_id, title, url, description for each bookmark
```

NOTE: OAuth 1.0a request signing is complex. Use a Python one-liner with `requests_oauthlib` or `oauth1` for signing:

```bash
python3 -c "
from requests_oauthlib import OAuth1Session
import json, os

creds_path = os.path.expanduser('~/.instapaper-credentials')
creds = {}
with open(creds_path) as f:
    for line in f:
        if '=' in line:
            k, v = line.strip().split('=', 1)
            creds[k] = v

session = OAuth1Session(
    creds['INSTAPAPER_CONSUMER_KEY'],
    client_secret=creds['INSTAPAPER_CONSUMER_SECRET'],
    resource_owner_key=creds.get('INSTAPAPER_ACCESS_TOKEN', ''),
    resource_owner_secret=creds.get('INSTAPAPER_ACCESS_SECRET', ''),
)

# List unread bookmarks (up to 500)
resp = session.post('https://www.instapaper.com/api/1/bookmarks/list', data={'limit': 500})
bookmarks = json.loads(resp.text)
# Filter to just bookmarks (not user/meta objects)
articles = [b for b in bookmarks if b.get('type') == 'bookmark']
print(json.dumps(articles, indent=2))
"
```

If this fails with auth errors, the access token exchange hasn't been done yet. Ask the user for their Instapaper email/password to perform the one-time xAuth exchange.

## Step 3: Evaluate each article

For each bookmark, fetch the article text:

```bash
python3 -c "
from requests_oauthlib import OAuth1Session
import os

# ... same session setup as above ...
resp = session.post('https://www.instapaper.com/api/1/bookmarks/get_text', data={'bookmark_id': BOOKMARK_ID})
print(resp.text)  # Returns HTML of processed article
"
```

Or use WebFetch on the article URL as a simpler alternative.

### LinkedIn link mining
When the article is a LinkedIn post, check the post content for ALL external links — not just GitHub. LinkedIn posts often link to product sites (.org, .io, .dev), blog posts, arxiv papers, or docs. Before classifying as "no repo/no source", extract every link from the post body via WebFetch or cmux browser snapshot. Resolve shortened `lnkd.in` links. The real content is often behind one of these links, not in the LinkedIn post itself.

### Non-text sources (videos, podcasts)
If the URL is a video (YouTube, Vimeo) or podcast, check for a transcript or show notes. Use the transcript to generate the summary if available; otherwise use the description. If neither exists, route to `Curaitor/Review/` as uncertain. Add `media_type: video` or `media_type: podcast` to frontmatter.

For each article, evaluate and assign:

- **Summary** (2-3 sentences — from transcript if video/podcast)
- **Category**: `ai-tooling` | `genomics` | `methods` | `general`
- **Confidence**: `high-interested` | `uncertain` | `high-not-interested`
- **Verdict**: `read-now` | `save-reference` | `review` | `skip` | `obsolete`
- **Obsolescence check** (ai-tooling only):
  - Is this tool/technique now a native Claude Code feature?
  - Has model capability growth made it unnecessary?
  - Is there a better-known alternative?
- **Relevance** (brief note on connection to user's work)

Match against preferences in `reading-prefs.md` to determine confidence level.

## Step 3.5: Deduplicate and recycle duplicates

Before routing, check each article URL against existing vault notes. Use `python3 scripts/triage-write.py --dedup-only --urls URL1 URL2 ...` or check manually. Exact URL duplicates are immediately recycled — append `- [title](url) (duplicate)` to `Curaitor/Recycle.md`. Do NOT create notes in Ignored for duplicates. Duplicates are not triage quality signals.

## Step 4: Route to Obsidian

Use the Obsidian MCP to write notes. Apply **autonomy-level routing overrides** (from Step 1):

- **Level 0**: Instapaper articles → Inbox or Review only (never Ignored). RSS → only Ignored if deterministic rule matches.
- **Level 1+**: Standard three-tier routing.

Route based on confidence (after overrides):

- **High confidence interested** → write to `Curaitor/Inbox/` folder
- **Uncertain** → write to `Curaitor/Review/` folder
- **High confidence not interested** → write to `Curaitor/Ignored/` folder

Note format:
```markdown
---
title: "Article Title"
url: https://...
source: instapaper
bookmark_id: 12345
date_saved: 2026-03-29
date_triaged: 2026-03-29
category: ai-tooling
confidence: high-interested
verdict: read-now
tags: [ai, claude-code, dev-tools]
---

## Summary
2-3 sentence summary.

## Verdict: Read Now
Why this is worth reading.

## Key takeaways
- Bullet points
```

Use the `mcp__obsidian__write_note` tool. The note path should be `Curaitor/{folder}/{sanitized-title}.md`.

## Step 5: Archive in Instapaper

After writing the Obsidian note, archive the bookmark:

```bash
python3 -c "
from requests_oauthlib import OAuth1Session
# ... session setup ...
resp = session.post('https://www.instapaper.com/api/1/bookmarks/archive', data={'bookmark_id': BOOKMARK_ID})
print(resp.status_code)
"
```

## Step 6: Present summary

After processing all bookmarks, show a summary table:

```
Triaged 15 articles:
  3 → Inbox     ★ (titles listed)
  7 → Review    ? (titles listed)
  3 → Ignored   ✗ (titles + reasons)
  2 → Duplicates recycled
  0 → Obsolete  ⊘

All 15 archived in Instapaper.

Autonomy: Level 1 (Normal) | Rolling: --/50 entries
```

If autonomy level is 0, always append: "Run `/cu:review-ignored` to check for false negatives and help calibrate triage accuracy."
If last_review_ignored is older than the reminder threshold for the current level, append the reminder.

## Rules
- Always read `reading-prefs.md` before evaluating
- Never delete Instapaper bookmarks — only archive
- If Instapaper API auth fails, fall back to RSS feed URL stored in `~/.instapaper-credentials` as `INSTAPAPER_RSS_URL`
- If `requests_oauthlib` is not installed, install it: `pip install requests-oauthlib`
- Be terse in output — summary table, not play-by-play
