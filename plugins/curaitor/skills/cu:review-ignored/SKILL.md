# /review-ignored — Check ignored articles for false negatives

Batch-scan ignored articles to catch false negatives. This is a high-throughput triage pass, NOT an article-by-article review — present grouped summaries so the user can dismiss entire categories at a glance.

## Arguments
$ARGUMENTS — Optional: number of days to look back (default 30).

## Step 1: Load and read all notes

1. Read `config/reading-prefs.md` from the plugin root
2. Run the pre-fetch script to read all notes, parse frontmatter, and detect repos (zero tokens):
   ```bash
   python3 scripts/prefetch-review.py ignored --days $DAYS --include-meta
   ```
   This returns JSON with all articles, vault tags, and topics. Use this data for grouping instead of individual MCP calls.
3. **Dedup first**: Before presenting articles, run URL dedup against the full vault. Duplicates are common in Ignored (39% in one session). Recycle all duplicates immediately — append `- [title](url) (duplicate)` to `Curaitor/Recycle.md` and delete notes. Report: "Recycled N duplicates before review."

## Step 2: Group by ignore reason and present batches

Cluster articles by their ignore reason/category, then present as grouped summaries. Print ALL output completely before asking for input.

```
Ignored articles (last 30 days): 42 total, 6 categories

━━ Marketing/product announcements (14) ━━
  Enterprise AI platforms, SaaS launch posts, vendor comparisons
  Sample: "Acme AI Platform Launch", "Top 10 Enterprise LLM Tools"

━━ Incremental benchmarks, no new method (8) ━━
  Papers comparing existing tools on standard datasets
  Sample: "Benchmarking CNV Callers on WGS Data", "GATK vs DeepVariant 2026"

━━ Non-applicable LLM content (7) ━━
  OpenAI/Gemini-specific tutorials, prompt engineering listicles
  Sample: "GPT-4 Fine-tuning Guide", "Gemini 2.5 vs GPT-5"

━━ News/opinion, no technical depth (6) ━━
  Industry commentary, funding announcements, executive interviews
  Sample: "AI Startup Raises $50M", "The Future of Genomics in 2027"

━━ Duplicates/outdated (4) ━━
  Topics already covered by a newer or better article in Inbox
  Sample: "Intro to RAG" (superseded by existing Inbox article)

━━ Potentially interesting — flagged for review (3) ━━
  These didn't clearly fit an ignore pattern:
   1. "Novel statistical framework for somatic CNV detection" — tagged incremental but uses new method
      → My suggestion: Rescue — novel method, not just a benchmark
   2. "Building AI agents with persistent memory" — tagged non-applicable but relevant to dev tooling
      → My suggestion: Rescue — directly relevant to your AI agent work
   3. "cfDNA fragmentomics for early cancer detection" — tagged news but has methods section
      → My suggestion: Rescue — has real methods, cfDNA is a core interest

Dismiss entire categories or rescue specific articles.
Examples: "all good", "rescue 1,3 from flagged", "show me the benchmarks list"
```

## Step 3: Process user response

- **"all good"** / **"none"** → confirm all as correctly ignored (**true negatives**). For each confirmed article: append `- [title](url)` to `Curaitor/Recycle.md`, then delete the note from `Curaitor/Ignored/`. Use confirmed ignores as signal that triage is working correctly for these patterns.
- **"rescue N,N"** or article numbers from the flagged list → move to `Curaitor/Review/` (**false negatives**). Agent analyzes WHY triage wrongly ignored these and updates preferences to decrease the false-negative rate.
- **"show me [category]"** → expand that category to show all titles, let user pick
- **"rescue [category] N,N"** → rescue specific articles from an expanded category
- Any rescued article: move from `Curaitor/Ignored/` to `Curaitor/Review/` via `mcp__obsidian__move_note`

## Step 4: Update preferences, accuracy stats, and summarize

### 4a. Update preferences
For **false negatives** (rescued articles), update `config/reading-prefs.md`:
```
- YYYY-MM-DD: FN — user interested in "Title" despite [pattern]. Triage was wrong because: [analysis]. Adjust: [new rule]
```

For **true negatives** (confirmed ignores), optionally reinforce correct patterns:
```
- YYYY-MM-DD: TN — confirmed 14 marketing/announcement articles correctly ignored. Pattern holding.
```

### 4b. Update accuracy stats
Update `config/accuracy-stats.yaml`:
1. Add TN and FN signals to `lifetime.{source}` counts and `rolling_window` (FIFO, max 50)
2. Increment `review_ignored_passes` by 1
3. Set `last_review_ignored` to today's date

### 4c. Check graduation and demotion
- **Graduation**: Check if rolling precision/recall + pass count meet next level criteria. If so, increment `autonomy_level` and announce.
- **Demotion**: If 3+ false negatives were found this pass, demote one level and announce:
  ```
  Autonomy downgraded: Level 2 (Confident) → Level 1 (Normal)
  Reason: 4 false negatives found — triage is being too aggressive
  ```

### 4d. Print summary
```
Reviewed 42 ignored articles:
  3 rescued → moved to Curaitor/Review/ (FN — triage too aggressive)
  39 confirmed ignored → recycled (TN — triage correct)

Accuracy: 39 TN, 3 FN this session | Review-ignored pass #5
Autonomy: Level 1 (Normal) | Rolling precision: 82% | Rolling recall: 88%

Preferences updated:
  ~ FN: CNV papers ARE interesting if they use a novel statistical framework
  ~ TN: Marketing/announcements pattern confirmed (14 articles)
```

## Rules
- **Batch, don't enumerate** — never list all articles individually unless the user asks to expand a category
- Group by ignore reason so entire categories can be dismissed at once
- Proactively flag articles that seem like potential false negatives in a separate "flagged" group
- Only update preferences when a clear pattern correction emerges
- Print all text output FIRST, then prompt — never use AskUserQuestion
