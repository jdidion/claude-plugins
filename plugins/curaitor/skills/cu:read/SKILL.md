# /cu:read — Deep reading session for Inbox articles

Read through articles in your Inbox one at a time: open in cmux browser, get a structured summary, discuss interactively, then decide what to do with it.

## Arguments
$ARGUMENTS — Optional: number of articles to read (default: all in Inbox), or a specific note filename.

## Step 1: Load context

1. Read `config/reading-prefs.md`
2. List notes in `Curaitor/Inbox/` folder via `mcp__obsidian__list_directory`

If Inbox is empty, tell the user and exit.

## Step 2: Present Inbox overview

```
Inbox: 23 articles

 1. [genomics]    "UPDhmm: detecting uniparental disomy from NGS trio data"
 2. [genomics]    "PScnv: personalized self-normalizing CNV detection"
 3. [ai-tooling]  "Harness design for long-running application development"
 ...

Starting with #1.
```

## Step 3: For each article

### a. Read the Obsidian note
Use `mcp__obsidian__read_note` to get the full note including frontmatter (title, url, tags, category).

### b. Open in cmux browser
```bash
cmux browser open "ARTICLE_URL"
# or reuse existing surface:
cmux browser goto "ARTICLE_URL" --surface surface:NN
cmux browser wait --load-state complete --surface surface:NN --timeout-ms 5000
```

### c. Fetch full content
Get the complete article text for RAG discussion:
- **Papers (DOI, bioRxiv, arXiv, nature.com):** If the `read_pdf` MCP tool is available, use it for PDF URLs — it extracts text AND images (figures, tables). Otherwise WebFetch the full text. If paywalled, use `cmux browser snapshot --compact` to get what's visible.
- **GitHub repos:** `gh api repos/OWNER/REPO --jq '.description'` + WebFetch the README
- **Blog posts / LinkedIn:** WebFetch or `cmux browser snapshot --compact`

Store the fetched content in working memory for the discussion.

### d. Auto-tag and search for related topics
Generate 3-8 semantic tags. Search `Topics/` folder for matching topic notes. Note any matches.

### e. Present structured summary

Print a thorough summary (NOT using AskUserQuestion):

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Article 1/23: "UPDhmm: detecting uniparental disomy from NGS trio data"
Category: genomics | Source: instapaper
Tags: uniparental-disomy, hidden-markov-model, trio-analysis, ngs, prenatal
Topics: [[Aneuploidy Detection]] (if found)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Summary
(3-5 sentences covering key contribution, method, and results)

## Key findings
- (bullet points of main results)

## Methods
- (brief description of approach)

## Relevance
(how this connects to the user's work and interests)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
What would you like to discuss?
```

### f. Interactive RAG discussion

Enter a conversational loop. The user can ask anything about the article:
- "How does this compare to X?"
- "What are the limitations?"
- "Could we apply this method to cfDNA?"
- "Summarize the methods section in more detail"
- "What datasets did they use?"

Answer from the fetched article content. If the user asks about something not in the text, say so and offer to WebSearch for more context.

Continue until the user signals they're done by typing a verdict key or "done".

### g. Ask for verdict

After the discussion (or if the user gives a verdict at any point), print:

```
r:zotero  t:topic  c:clip  b:bookmark  p:post  a:archive  skip  q:quit
```

The user can type:
- **r** — Save to Zotero (for publications/papers), then remove from Inbox
- **t** or **t Topic Name** — Attach to a topic (existing or new), remove from Inbox
- **c** — Clip: star GitHub repo + add to Tools & Projects catalog, remove from Inbox (for tools/libraries)
- **p** — Post to Slack, then archive (same flow as `/cu:review` post — prompt for channel, draft message, send)
- **a** or **a reason** — Archive: reviewed and not keeping. Logs to `Curaitor/Archive/Archive.md` with audit trail.
- **skip** — Leave in Inbox, move to next article
- **q** — Quit, show session summary
- Any other text — continue the discussion

### h. Handle verdict

- **r** → Save to Zotero via API. Add discussion notes as a Zotero note attachment. Delete from Obsidian `Curaitor/Inbox/`.
- **t** → Attach to topic (same flow as `/cu:review` topic mode). Add article summary + discussion notes under the topic. Delete from `Curaitor/Inbox/`.
- **c** → Star GitHub repo (`gh api user/starred/OWNER/REPO -X PUT`), add to `Tools & Projects.md`, delete from `Curaitor/Inbox/`.
- **b** → **Bookmark**: save the link to `Bookmarks.md` in Obsidian vault root (organized by category, same format as Tools & Projects). If `config/user-settings.yaml` has `bookmark_command`, run that instead. Delete from `Curaitor/Inbox/`.
- **p** → **Post to Slack**: same flow as `/cu:review` — prompt for channel (default from `config/user-settings.yaml`), draft message, present for editing, send via `mcp__slack-mcp__send_slack_message`, then archive with reason "Posted to Slack #{channel}". Delete from `Curaitor/Inbox/`.
- **a** → **Archive**: append an entry to `Curaitor/Archive/Archive.md` with title, URL, date, summary, questions asked during discussion, and reason (if provided). Then delete from `Curaitor/Inbox/`. Format:
  ```markdown
  ### {title}
  - **URL**: {url}
  - **Date reviewed**: {YYYY-MM-DD}
  - **Category**: {category}
  - **Summary**: {1-2 sentence summary}
  - **Questions asked**: {list from discussion, or "none"}
  - **Reason archived**: {user's reason if provided, otherwise "Reviewed — not keeping"}
  ```
- **skip** → Leave in `Curaitor/Inbox/`, move to next article.
- **q** → Stop, show session summary.

### i. Save discussion notes

For **r** and **t** verdicts, before removing the article, compile discussion notes from the conversation:
- Key takeaways the user expressed
- Connections to their work mentioned during discussion
- Action items or follow-ups
- Questions that remain open

For Zotero: add as a note on the Zotero entry.
For topics: append under the article's entry in the topic note.

### j. Update preferences

If the verdict reveals a new preference pattern, append to `config/reading-prefs.md`.

## Step 4: Session summary

```
Reading session complete:
  3 → Zotero (with discussion notes)
  2 → Topics
  1 → Clipped (Tools catalog)
  2 → Discarded
  15 remaining in Inbox

Discussion notes saved for:
  "UPDhmm" — 4 notes on Zotero entry
  "Harness design" — added to [[AI Agent Architecture]] topic
```

## Rules
- Always fetch full article content before presenting the summary
- The summary should be thorough — this is deep reading, not triage
- Wait for user input — this is interactive
- Do NOT use AskUserQuestion — print menus as text
- Save discussion notes before removing articles on r/t verdicts
- On discard (d), confirm with the user before deleting
- Track cmux browser surface:NN and reuse it
