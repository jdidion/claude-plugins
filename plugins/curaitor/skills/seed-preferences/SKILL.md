# /seed-preferences — One-time preference seeding

Analyze the user's Zotero library and Instapaper history to build initial reading preferences.

## Arguments
$ARGUMENTS — Optional: "zotero", "instapaper", or "all" (default: all).

## Step 1: Gather data from Zotero

Read Zotero API credentials from `~/.zotero-key`:
```
ZOTERO_API_KEY=...
ZOTERO_LIBRARY_ID=...
ZOTERO_LIBRARY_TYPE=user
```

Fetch library items:
```bash
curl -s -H "Zotero-API-Key: $ZOTERO_API_KEY" \
  "https://api.zotero.org/$ZOTERO_LIBRARY_TYPE/$ZOTERO_LIBRARY_ID/items?limit=100&format=json" \
  | python3 -c "
import json, sys
items = json.load(sys.stdin)
for item in items:
    d = item.get('data', {})
    if d.get('itemType') in ('journalArticle', 'preprint', 'conferencePaper', 'book', 'bookSection', 'webpage'):
        tags = [t['tag'] for t in d.get('tags', [])]
        print(f'Title: {d.get(\"title\", \"?\")}')
        print(f'Type: {d.get(\"itemType\", \"?\")}')
        print(f'Tags: {\", \".join(tags) if tags else \"none\"}')
        print(f'Date: {d.get(\"date\", \"?\")}')
        print(f'Publication: {d.get(\"publicationTitle\", d.get(\"publisher\", \"?\"))}')
        print()
"
```

Paginate if needed (check `Total-Results` header).

## Step 2: Gather data from Instapaper

Use the Instapaper API to fetch archived bookmarks (articles the user already read):

```bash
source ~/.instapaper-credentials
python3 -c "
from requests_oauthlib import OAuth1Session
import json, os

creds = {}
with open(os.path.expanduser('~/.instapaper-credentials')) as f:
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

# Fetch archived bookmarks
resp = session.post('https://www.instapaper.com/api/1/bookmarks/list',
    data={'folder_id': 'archive', 'limit': 500})
bookmarks = json.loads(resp.text)
articles = [b for b in bookmarks if b.get('type') == 'bookmark']
for a in articles:
    print(f'Title: {a[\"title\"]}')
    print(f'URL: {a[\"url\"]}')
    print(f'Saved: {a.get(\"time\", \"?\")}')
    print()
"
```

Also fetch current unread bookmarks (Home folder) the same way but with `folder_id='unread'` or omitting it.

## Step 3: Analyze patterns

From the combined Zotero + Instapaper data, identify:

1. **Recurring topics** — what subjects appear most frequently?
2. **Preferred journals/sources** — where does the user save from?
3. **Methods and techniques** — what methodological approaches interest them?
4. **Authors** — any frequently saved authors?
5. **Time patterns** — recent vs historical interest shifts?
6. **Cross-disciplinary signals** — articles from outside genomics that were saved

## Step 4: Write preferences

Update `config/reading-prefs.md` with structured preferences:

```markdown
# Reading Preferences

Seeded from Zotero library (N items) and Instapaper archive (N items) on YYYY-MM-DD.

## Strong interests
- [topic 1]: [evidence from library]
- [topic 2]: [evidence]
...

## Preferred sources
- [journal/site 1]
- [journal/site 2]
...

## Not interested in
- [pattern 1]: [inferred from what's absent or skipped]
...

## Learned patterns
(empty — will grow via /review feedback)
```

## Step 5: Present summary

Show the user what was inferred and ask for corrections:

```
Seeded preferences from 87 Zotero items + 234 Instapaper archives.

Top inferred interests:
  1. cfDNA analysis and fetal fraction estimation
  2. AI-assisted development tools (CLI-native)
  3. Variant calling for low-frequency variants
  ...

Anything I got wrong or missing?
```

## Rules
- This is a one-time setup command — safe to re-run to refresh
- Don't save raw article data, only inferred patterns
- Present inferences for user validation before finalizing
- If Zotero or Instapaper auth fails, proceed with whichever source works
