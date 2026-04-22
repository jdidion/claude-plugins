# /cu:review — Interactive article review session

Browse articles from the Review queue one at a time in the cmux browser, discuss with Claude, and give feedback.

## Arguments
$ARGUMENTS — Optional: number of articles to review (default: all), or "ignored" to review the Ignored folder.

## Step 1: Load context

1. Read `config/reading-prefs.md`
2. List notes in `Curaitor/Review/` folder via `mcp__obsidian__list_directory`
3. If $ARGUMENTS is "ignored", list `Curaitor/Ignored/` folder instead

If the queue is empty, tell the user and exit.

## Monitor orientation

If the user's primary cmux monitor is vertical, set `CURAITOR_MONITOR=vertical` in their shell env. When set, this skill prefers `cmux browser open-split-below` (stacks panes vertically) over the default `cmux browser open-split` (horizontal). When unset or `horizontal`, use the default.

## Step 2: LinkedIn pre-authentication

Many Review articles are LinkedIn posts. Check if any articles have linkedin.com URLs. If so, authenticate at the start of the session:

1. Open LinkedIn in cmux browser:
   ```bash
   if [ "$CURAITOR_MONITOR" = "vertical" ]; then
     cmux browser open-split-below "https://www.linkedin.com/login"
   else
     cmux browser open "https://www.linkedin.com/login"
   fi
   ```
2. Track the returned `surface:NN` ID for all subsequent browser commands
3. Use Bitwarden CLI to fill credentials (look up the LinkedIn item in Bitwarden):
   ```bash
   cmux browser fill "EMAIL_REF" "$(bw get username linkedin.com)" --surface surface:NN
   cmux browser fill "PASSWORD_REF" "$(bw get password linkedin.com)" --surface surface:NN
   ```
4. User may need to approve 2FA on their phone — wait for confirmation

Skip this step if no LinkedIn articles in the queue or if BW_SESSION is not set.

## Step 3: Present queue overview

```
Review queue: 18 articles

1. [ai-tooling]  "Optimize LLM Efficiency with Sequencing Tool"
2. [ai-tooling]  "Structural Metadata Reconstruction Attack on LLMs"
3. [ai-tooling]  "Introducing Axion: AI-Friendly Programming Language"
...

Starting with #1.
```

### Topic grouping (20+ articles)
When the review queue has 20 or more articles, pre-group them by topic before presenting. This enables batch decisions and faster throughput.

1. **Cluster articles** by semantic similarity (shared tags, category, title keywords). Groups should have 2+ articles. Articles that don't naturally cluster with others remain standalone — don't force grouping.

2. **Present grouped overview** instead of a flat list:
```
Review queue: 42 articles (7 groups + 5 standalone)

━━ MCED / Liquid Biopsy (6) ━━
  "MCED Slides - Multi-Cancer Early Detection"
  "Caris Life Sciences multi-cancer early detection cfDNA"
  ... 4 more
  → My suggestion: t:MCED & Liquid Biopsy — all related, create topic
  [.] accept  [expand] show all  [n] recycle group  [skip] review individually

━━ AI Agent Architecture (5) ━━
  "Platform Engineering with MCP"
  "Building Reliable Agents"
  ... 3 more
  → My suggestion: t:AI Agent Architecture — extend existing topic
  [.] accept  [expand] show all  [n] recycle group  [skip] review individually

━━ Standalone articles (5) ━━
  1. "OpenCode vs Claude Code" — instapaper · ai-tooling
  2. "Predicting Protein Thermostability" — rss · methods
  ... (reviewed individually as normal)
```

3. **Group actions**: The user can act on an entire group with one verdict:
   - **`.`** — accept the suggestion (e.g., create/extend topic for all articles in group)
   - **y** — move all to Inbox
   - **n** — recycle all (each counts as FP)
   - **t** or **t:Topic Name** — attach all to a topic
   - **expand** — break the group open and review each article individually
   - **skip** — leave all in Review

4. **Standalone articles** are reviewed one-at-a-time using the normal flow (steps 4+).

5. **Always offer grouping opt-out**: If the user prefers flat review, typing `flat` at the grouped overview switches to the normal sequential flow.

## Step 3.5: Pre-fetch pipeline (script + parallel sub-agents)

**Purpose**: Eliminate wait time between articles by pre-computing data in the background. Two layers:

### Layer 1: Script pre-fetch (zero tokens)

Run the pre-fetch script to read all notes, parse frontmatter, detect repos, and collect vault metadata:

```bash
python3 scripts/prefetch-review.py review --include-meta
```

This returns JSON with all articles including: title, URL, source, category, tags, repo detection, summary, "why review?" text, plus vault-wide tags and topics. Store this in working memory — it replaces steps b-e for most articles.

### Layer 2: Parallel sub-agents for LLM reasoning (10 at a time)

Using the pre-fetched data, spawn **up to 10 parallel sub-agents** (via the Agent tool with `run_in_background: true`) to generate the LLM-only parts for the first 10 articles. Each sub-agent receives the pre-fetched article data and:

1. Generates/refines semantic tags (using vault_tags for consistency)
2. Matches the best existing topic (from the topics list) or suggests a new one
3. Writes the "My suggestion" line (one sentence: verdict + reasoning)
4. Composes the full assessment block ready to print

**Sliding window**: After the user gives a verdict on article N, if article N+10 hasn't been pre-processed yet, spawn a new background agent for it.

**Fallback**: If a sub-agent hasn't finished when the user reaches that article, generate inline using the script pre-fetch data (which is always available).

## Step 4: For each article

### a. Check for pre-fetched summary

If a pre-fetched summary is available for this article, skip steps b-e and go straight to presenting it (step f). Otherwise, compute inline:

### b. Read the Obsidian note
Use `mcp__obsidian__read_note` to get the full note including frontmatter.

### c. Detect GitHub/GitLab repos

Before opening, check if the article URL or title contains a GitHub/GitLab repo link:
- URL matches `github.com/{owner}/{repo}` or `gitlab.com/{owner}/{repo}`
- Title contains "GitHub -" or "GitLab -" followed by `{owner}/{repo}`
- Article text/description contains a `github.com/{owner}/{repo}` link

If a repo is detected, extract the `owner/repo` and note it. When presenting the article, offer to open the repo instead:

```
  Repo detected: github.com/steveyegge/beads
  [r] Open repo instead  |  [a] Open article  |  [b] Open both
```

Default to the repo URL for GitHub/GitLab-linked articles.

### d. Open in cmux browser
```bash
if [ "$CURAITOR_MONITOR" = "vertical" ]; then
  cmux browser open-split-below "ARTICLE_URL"  # or REPO_URL if user chose [r]
else
  cmux browser open "ARTICLE_URL"  # or REPO_URL if user chose [r]
fi
# or if reusing existing surface:
cmux browser goto "URL" --surface surface:NN
cmux browser wait --load-state complete --surface surface:NN --timeout-ms 5000
```

### e. Auto-tag and search for related topics

Generate 3-8 semantic tags from the article content:
- Lowercase, hyphenated (e.g., `variant-calling`, `ai-agents`, `cfDNA`)
- Mix of broad (`genomics`, `machine-learning`) and specific (`bloom-filters`, `nanopore-basecalling`)
- Check existing vault tags first — prefer existing tags over creating synonyms

Then search Obsidian for matching topic notes:
1. `mcp__obsidian__search_notes` for key tags
2. Check `Topics/` folder for notes with matching tags
3. Note any matches for display

### f. Present Claude's assessment
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Article 1/18: "Optimize LLM Efficiency with Sequencing Tool"
Category: ai-tooling | Source: instapaper
Repo: github.com/davidtarjan/pi-mono (if detected)
Tags: ai-agents, token-optimization, tool-batching
Topics: [[AI-Assisted Development]] (if any found)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Summary
(from the Obsidian note)

## Why review?
(from the Obsidian note)

## My suggestion [. to accept]
(one sentence starting with the verdict key, e.g. "n — product announcement, no technical depth" or "y — novel method directly applicable to your cfDNA work" or "t:Variant Calling — new statistical framework")

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### f. Ask for verdict

Do NOT use AskUserQuestion — it only supports 4 options max. Instead, print the FULL menu as text and wait for the user to type their response.

**CRITICAL: Always print ALL menu items.** Never abbreviate or truncate the menu. Conditional items: `c` (only when repo/tool detected), `r` (only for publications — DOI, bioRxiv, arXiv, journal articles). Every other item MUST always appear:

```
d:deep-read  y:inbox  t:topic  c:clip  b:bookmark  r:zotero  p:post  n:recycle  skip  q:quit
```

**Topic suggestion**: Replace `t:topic` with a specific suggestion like `t:Variant Calling Methods` whenever possible. Infer from the article's tags, content, and matching existing topics. Only fall back to bare `t:topic` if no reasonable topic can be inferred.

The user can type:
- **`.`** (period) — accept "My suggestion" as the verdict (`.` is used instead of Enter because Claude Code's harness swallows empty prompts before they reach the agent)
- A bare key: `y`, `n`, `c`, `r`, `skip`, `q`
- **Bare `t`** — if a topic was suggested in the menu (e.g., `t:Variant Calling`), use that topic directly. Only ask which topic if no suggestion was shown or the user types `t <different topic>`.
- **`tl`** — list all available topics with numbers, then let the user pick by number or name. Example:
  ```
  Topics:
    1. AI Agent Architecture (12 links)
    2. Variant Calling Methods (8 links)
    3. Rust Learning (5 links)
  Type a number, name, or 'new <name>':
  ```
- **`d <comment>`** — deep read with initial context
- Questions: just type them. No prefix needed. E.g., `<question>`** — ask a question before deciding
- **`t <topic name>`** — attach to existing topic or create new one
- **`n <reason>`** — recycle with a reason (e.g., `n not relevant to current work`)
- Any other free text — treated as a question, answer it, re-show menu

### g. Handle verdict

- **!** → **Deep read mode** (see below). If repo detected: star it and add to Tools catalog.
- **?** → **Discussion mode**: fetch full article text, conversational Q&A loop, re-present verdict when user says "done".
- **y** → move to `Curaitor/Inbox/`, update frontmatter with tags. If repo detected: star it and add to Tools catalog. **True positive** — triage was right to flag this for review.
- **t** → **Topic mode**: attach article to a topic, then delete from Curaitor/Review/ (article lives under the topic, not separately):
  - If user typed `t` alone and related topics were found: list them, ask which one (or "new")
  - If user typed `t <topic name>`: use that topic (create in `Topics/` if new)
  - Add article as a `[[wiki-link]]` under `## Related Articles` in the topic note
  - Add article URL, title, and summary as a sub-entry in the topic note
  - If repo detected: also star it and add to Tools catalog
  - Delete the article from `Curaitor/Review/` — it's now referenced from the topic, no need to keep separately
  - **True positive** — triage was right.
- **c** → **Clip**: add repo/tool to `Tools & Projects.md`, star if GitHub, delete article from `Curaitor/Review/`. **True positive**.
- **b** → **Bookmark**: save the link to `Bookmarks.md` in Obsidian vault root (see Bookmark format below), then delete from `Curaitor/Review/`. If `config/user-settings.yaml` has a custom `bookmark_command`, run that instead. **True positive**.
- **r** → save to Zotero via API, move to `Curaitor/Inbox/`, add zotero_key to frontmatter. **True positive**.
- **p** → **Post to Slack** (see Post flow below), then recycle the article. **True positive**.
- **n** → **Recycle**: the user has reviewed this and doesn't want to keep it. Signal depends on engagement (see below):
  - **If the user asked at least one question about this article OR requested more detail before giving `n`** → **engaged TP**: triage was right to surface it for attention, even though the user chose not to keep it. Record with `engaged: true` in the rolling_window entry.
  - **If the user went straight to `n` with no questions** → **false positive**: triage was wrong to put this in Review. Analyze WHY and update `config/reading-prefs.md` to decrease the future false-positive rate.
  In either case, append `- [title](url)` to `Curaitor/Recycle.md` and delete the article note from `Curaitor/Review/`. NEVER move articles to `Curaitor/Ignored/` — that folder is only for triage-agent classifications.
- **skip** → leave in `Curaitor/Review/`. **True positive** (the user isn't dismissing it, so triage was right to flag it).
- **q** → stop, show session summary

### Post to Slack flow (p)

1. **Prompt for channel**: Print the default channel from `config/user-settings.yaml` (`default_slack_channel`), ask the user to type a channel name, user ID (for DM), or type `.` to accept the default.

2. **Draft the message**: Compose a Slack message with:
   - Article title as a link
   - 1-2 sentence summary
   - Why it's interesting (from Claude's assessment or user's discussion)
   - Tags as hashtags

   Example:
   ```
   *<https://github.com/steveyegge/beads|Beads: A memory upgrade for your coding agent>*
   Persistent structured memory for coding agents using Dolt. Replaces markdown plans with dependency-aware graphs for long-horizon tasks.
   Worth checking out if you're building agentic workflows. #ai-agents #developer-tools
   _*Authored by Claude, pending human review*_
   ```

3. **Present draft to user**: Print the draft and ask the user to edit or approve:
   ```
   Draft message for #ai-general:

   [message text]

   Send as-is (enter), edit (type replacement), or cancel (x)?
   ```

4. **Send**: Use `mcp__slack-mcp__send_slack_message` with the channel and final message text.

5. **Recycle**: After posting, append `- [title](url)` to `Curaitor/Recycle.md`, then delete from `Curaitor/Review/`.

### Bookmark format

`Bookmarks.md` in the Obsidian vault root. Organized hierarchically by category, similar to `Tools & Projects.md`. Each entry is one line:

```markdown
# Bookmarks

## Genomics & Bioinformatics
- [UPDhmm](http://doi.org/10.1093/bioinformatics/btag062) — HMM-based UPD detection from NGS trio data
- [Strand-seq and personalized genomics](https://www.nature.com/articles/s41588-026-02548-4) — Nature Genetics perspective

## AI & Development
- [Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps) — Anthropic engineering post on agent harnesses

## General
- [Unbreaking Software](https://third-bit.com/unbreak/) — Debugging course by Greg Wilson
```

Read the existing `Bookmarks.md` via `mcp__obsidian__read_note`. If it doesn't exist, create it. Append the new entry under the appropriate category. If the category doesn't exist, create it.

**Custom bookmark command**: If `config/user-settings.yaml` has `bookmark_command`, run that instead of writing to Obsidian. Example:
```yaml
# Save to Raindrop.io instead of Obsidian
bookmark_command: "curl -s -X POST 'https://api.raindrop.io/rest/v1/raindrop' -H 'Authorization: Bearer $RAINDROP_TOKEN' -H 'Content-Type: application/json' -d '{\"link\": \"$URL\", \"title\": \"$TITLE\", \"tags\": $TAGS}'"
```

### Recycle format

`Curaitor/Recycle.md` is a simple unordered list of dismissed article links. Append each recycled article as:

```markdown
- [Article Title](https://url)
```

No audit trail, no metadata — just the link for potential future reference.

The review agent should NEVER add articles to `Curaitor/Ignored/`. Only the triage agent (`/cu:triage`, `/cu:discover`) writes to `Curaitor/Ignored/`. The review agent only reads from `Curaitor/Ignored/` (for `/cu:review-ignored`) and moves articles OUT of it.

### f. Star GitHub repos (on y or !)

If a GitHub repo was detected and the user chose `y` or `d`:
1. Star the repo:
   ```bash
   gh api user/starred/OWNER/REPO -X PUT
   ```
2. Get repo description:
   ```bash
   gh api repos/OWNER/REPO --jq '.description'
   ```
3. Add to the **Tools & Projects** catalog in Obsidian (see below)

For GitLab repos, use the GitLab MCP `gitlab_star_project` if available, otherwise skip starring.

### g. Update Tools & Projects catalog

Maintain `Tools & Projects.md` at the root of the Obsidian vault. This is an organized collection of tools and projects discovered through curaitor.

Read the existing note via `mcp__obsidian__read_note` (path: `Tools & Projects.md`). If it doesn't exist, create it.

Format: organized by category, each entry is one line with name as a link and short description.

```markdown
# Tools & Projects

## Genomics & Bioinformatics
- [Helicase](https://github.com/owner/helicase) — SIMD-vectorized FASTQ/FASTA parsing
- [RabbitVar](https://github.com/LeiHaoa/RabbitVar) — Fast germline + somatic variant caller

## AI & Development Tools
- [beads](https://github.com/steveyegge/beads) — Persistent structured memory for coding agents
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — Make any software agent-native via CLI

## Data & Infrastructure
- [Seqa23](https://github.com/...) — Rust crate for querying genomic files across clouds
```

Append the new entry under the appropriate category. If the category doesn't exist, create it. Keep entries sorted alphabetically within each category.

### e. Deep read mode (!)

When the user types `d`, this means "I'm interested AND I want to read and discuss this right now":

1. **Save permanently:**
   - If it's a paper (DOI, bioRxiv, arXiv, nature.com, etc.): save to Zotero via API
   - If it's a blog/tool/LinkedIn post: move to `Library/` folder in Obsidian (create if needed)

2. **Fetch full content:**
   - For PDF URLs (papers): use `read_pdf` MCP tool if available (extracts text + images/figures). Otherwise WebFetch.
   - For papers: fetch abstract + full text if accessible
   - **Hosts that block WebFetch** (`biorxiv.org`, `medrxiv.org`, some `nature.com` articles — 403/303): skip WebFetch. Try (1) swap to `.full.pdf` + `read_pdf`, or (2) `cmux browser goto` + `cmux browser snapshot --compact`.
   - For GitHub repos: read the README
   - For LinkedIn posts: use cmux browser snapshot to get full DOM content
   - Store the fetched content in working memory for the discussion

3. **Interactive RAG discussion:**
   - Present a structured summary (key findings, methods, implications)
   - Then say: "What would you like to discuss about this article?"
   - Answer user's questions from the article content
   - The user may ask things like:
     - "How does this compare to X?"
     - "Could we use this method in our pipeline?"
     - "What are the limitations?"
     - "Summarize the methods section"
   - Continue the discussion until the user says "done" or "next"

4. **Save discussion notes:**
   - When the user finishes discussing, compile the key points from the conversation:
     - User's takeaways and insights
     - Connections to their work
     - Action items or follow-ups mentioned
   - If saved to Zotero: add as a note on the Zotero entry via API
   - If saved to Obsidian Library/: append a `## Discussion Notes` section to the note with date

5. **Update the Obsidian note** with final verdict and move from `Curaitor/Review/` to `Library/` or `Curaitor/Inbox/`

### f. Update preferences
After each verdict, if the decision reveals a genuinely new preference pattern, append to `config/reading-prefs.md` under "## Learned patterns":
```
- YYYY-MM-DD: [TP|FP] User [interested in / not interested in] [pattern]. Example: "Article Title". [analysis of triage accuracy]
```
For **false positives** (a verdict), always log with analysis of why triage was wrong and what rule should change.
For **true positives**, only log if the pattern is genuinely new and informative.

## Step 5: Update accuracy stats and session summary

At the end of the session, update `config/accuracy-stats.yaml`:

1. **Accumulate signals**: For each article reviewed this session, add to `lifetime.{source}.{signal}` (TP or FP) and append to `rolling_window` (FIFO, max 50 entries). For `engaged TP` signals (user asked questions before recycling), also increment `lifetime.{source}.engaged_tp` and set `engaged: true` on the rolling-window entry:
   ```yaml
   # Kept verdict (y/d/t/c/b/r/p/skip)
   {date: "YYYY-MM-DD", source: "instapaper", signal: "tp", title: "Article Title"}
   # Recycled after engagement (user asked questions, then gave n)
   {date: "YYYY-MM-DD", source: "rss", signal: "tp", engaged: true, title: "Article Title"}
   # Recycled without engagement (pure FP)
   {date: "YYYY-MM-DD", source: "rss", signal: "fp", title: "Article Title"}
   ```
   If rolling_window exceeds 50, remove the oldest entries.

2. **Check graduation**: Run `python3 scripts/accuracy-metrics.py --json` to check if graduation criteria are met. If so, increment `autonomy_level` and announce:
   ```
   Autonomy upgraded: Level 1 (Normal) → Level 2 (Confident)
   Precision: 85% | Recall: 90% | 120 articles reviewed | 4 review-ignored passes
   ```

3. **Print session summary**:
```
Review session complete:
  3 → Inbox (TP)
  2 → Recycled (FP)
  1 → Zotero (TP)
  2 → Library (deep read, TP)
  10 remaining in Curaitor/Review/

Accuracy: 5 TP, 2 FP this session | Rolling precision: 82% | Level 1 (Normal)

Preferences updated:
  + interested in terminal-native AI tools
  + not interested in enterprise SaaS tools
```

## Rules
- Always open the article in cmux browser before presenting
- Wait for user input after each article
- **Parallel work checklists**: When running 3+ parallel operations (background agents, batch actions), show a visible checklist so the user can track progress:
  ```
  - [x] Pre-fetch 10 articles
  - [ ] Sub-agent: articles 1-5 (suggestions)
  - [x] Sub-agent: articles 6-10 (suggestions)
  ```
- Keep assessments concise — 3-4 sentences max
- If cmux is not available, show the URL for manual opening
- Only update reading-prefs.md when a pattern is genuinely new
- In deep read mode, be thorough — the user wants to engage deeply with the material
- For cmux browser: use `cmux browser open`, `cmux browser goto`, `cmux browser snapshot`, `cmux browser wait` (NOT `cmux browse`)
- Track the surface:NN ID from the first `cmux browser open` and reuse it
