# /salvage — Remove AI writing patterns and humanize text

Strip AI-generated writing patterns from text using a diagnose-reconstruct-audit workflow. Synthesized from mshumer/unslop, theclaymethod/unslop, conorbronsdon/avoid-ai-writing, tropes.fyi, and hardikpandya/stop-slop.

## Arguments

$ARGUMENTS — Text to process, provided as:
- Inline text or a file path
- Optional flags: `--preset <voice>`, `--context <profile>`, `--strict`, `--detect`, `--prevent`

**Presets (voice):** `crisp` (default), `warm`, `expert`, `story`
**Contexts (tolerance):** `linkedin`, `blog`, `technical`, `email`, `docs`, `casual`
**Modes:** rewrite (default), detect (flag-only with `--detect`), prevent (emit system instruction with `--prevent`), learn (build voice profile with `--learn`), feedback (refine voice from edits with `--feedback`)

## Workflow

### Pass 1: Diagnose (script-assisted)

Run the detection script to mechanically scan for flagged patterns:

```bash
python3 <plugin_root>/scripts/detect.py <file_or_text> --context <context> --json
```

The script checks: Tier 1 vocabulary (62 entries), Tier 2 clusters, Tier 3 density, banned phrases, and structural patterns. All word lists live in `config/patterns.yaml`.

If the script is unavailable, diagnose inline using the priority categories below.

**P0 — Credibility killers** (always fix):
- Tier 1 vocabulary (see `config/patterns.yaml` for full list — 62 near-certain AI signals)
- Throat-clearing openers and structural closers
- Sweeping opening statements before narrowing to topic
- Em-dash overuse (target: zero or near-zero)
- Bold overuse for emphasis
- Chatbot artifacts ("As an AI", "I'd be happy to", knowledge-cutoff disclaimers)
- "Serves as" dodge — replacing simple "is" with pompous alternatives ("stands as", "marks", "represents")

**P1 — Obvious AI patterns** (fix in most contexts):
- Tier 2 vocabulary clusters (3+ in one piece)
- Formulaic structure: hook → context → 3 body sections → takeaway → CTA
- Binary contrasts ("It's not about X, it's about Y")
- Triple-negation reveal ("Not X. Not Y. Just Z.")
- Rhetorical question openers and self-answered questions ("The X? A Y.")
- Significance inflation ("game-changing", "revolutionary")
- Synonym cycling (rotating near-synonyms to fake variety)
- Uniform sentence rhythm (similar length/structure in sequence)
- Excessive bullet lists, numbered lists, and one-sentence paragraphs
- Filler adverbs and hedge phrases
- False vulnerability and performative authenticity
- Vague attributions ("experts say", "industry reports suggest", "some observers")
- Invented concept labels (fabricated compound terms like "supervision paradox")
- Patronizing analogies ("Think of it as...")
- Dead metaphor beating (repeating one metaphor 5-10 times)
- One-point dilution (single argument restated many ways)

**P2 — Stylistic polish** (fix when strict, tolerate otherwise):
- Tier 3 vocabulary at high density (5+ per 500 words)
- Slight over-formality
- Parenthetical hedging
- Generic positive conclusions
- Fractal summaries (restating thesis at every structural level)
- Content duplication (near-verbatim repetition within same piece)
- Unicode decoration overuse (→ arrows, smart quotes for emphasis)

### Pass 2: Reconstruct

If `config/voice-profile.yaml` exists and has non-null values, load it and apply the user's voice during reconstruction:
- Match sentence length to their statistical profile (mean and variance)
- Match punctuation habits (em-dash frequency, semicolon usage, etc.)
- Apply style notes as additional constraints
- Prefer their vocabulary preferences; avoid their avoided words
- Follow their structural patterns (opener style, closer style, paragraph length)

If a voice profile is not available, fall back to the selected voice preset.

Rewrite the text applying the voice profile (or preset), preserving all facts.

**Rules for reconstruction:**
1. Start with the actual topic. No warming up.
2. Vary sentence length deliberately. Mix short punches with longer explanations.
3. Use concrete verbs. "Cut" not "implement a reduction." "Broke" not "experienced a disruption."
4. Have opinions. State them directly. "This approach fails because..." not "Some might argue there are challenges..."
5. Use first person where natural. "I" and "we" are fine.
6. Leave some roughness. Perfect polish reads as synthetic.
7. Show uncertainty honestly. "I don't know" beats "The answer remains nuanced."
8. If a sentence can be removed without changing meaning, remove it.
9. Never add content that wasn't in the original. Preserve every fact, number, proper noun, technical term, quote, and URL.

### Pass 3: Audit (automatic)

Re-scan the rewrite for any remaining AI patterns. If P0 or P1 issues remain, fix them. Report the final score.

## Voice Presets

### crisp (default)
Short, direct sentences. 5-15 words average. Cut ruthlessly. One idea per sentence. No hedging. If a word doesn't earn its place, delete it. Prefer periods over commas.

### warm
Friendly, conversational. 8-20 words average. Use contractions. Address the reader occasionally. Soft landings — end paragraphs with something human, not a lecture. Like explaining to a smart friend.

### expert
Authoritative, confident. 10-25 words average. Make claims without hedging. Show expertise through specifics, not credentials. Use numbers and names. Skip "I think" — just state what you know.

### story
Narrative flow. Varied sentence length (5-30 words). Structure as scene, tension, resolution, insight. One story, one point. Let readers draw their own conclusions from the evidence you present.

## Scoring Rubric

Score the output on 8 criteria, 1-5 each. **32/40 to pass.**

| Criterion | 1 (AI-obvious) | 5 (human-natural) |
|-----------|----------------|-------------------|
| **Directness** | Buries the point in preamble | Opens with the point |
| **Rhythm** | Uniform sentence length/structure | Varied, unpredictable |
| **Concrete verbs** | Abstract/passive ("was implemented") | Active/specific ("built", "cut") |
| **Reader trust** | Tells reader what to think | Presents evidence, lets reader think |
| **Authenticity** | Sounds like a press release | Sounds like a specific person wrote it |
| **Content density** | Filler pads every paragraph | Every sentence carries weight |
| **Fact preservation** | Facts altered, numbers rounded | All facts exactly preserved |
| **Pattern avoidance** | Multiple AI patterns remain | No detectable AI patterns |

## Fact Preservation Rules

**Absolute preservation (never change):**
- Numbers, dates, percentages, measurements
- Proper nouns (people, companies, products, places)
- Technical terms, jargon, abbreviations
- Quoted material (direct quotes must be verbatim)
- URLs, file paths, code
- Cause-and-effect relationships
- Comparative claims (X is better than Y)

**Semantic preservation (meaning must survive):**
- The author's stance and opinions
- Scope and qualifications ("some" vs "all", "often" vs "always")
- Sequence and causation (don't imply causation where only correlation was stated)

## Learn Mode (--learn)

Build a voice profile from writing samples so future rewrites match the user's natural voice.

### Usage

```
/salvage --learn file1.md file2.md file3.md    # analyze specific files
/salvage --learn                                # open file browser to choose
```

### Workflow

**Step 1: Select samples.** If no files are provided, browse for them:
1. Check for `gum` CLI (`gum file --all`). If available, use it as a TUI file picker.
2. Otherwise, use Glob to list `.md`, `.txt`, and `.org` files in the working directory and common writing locations (`~/Documents`, `~/Desktop`, Obsidian vault).
3. Present the list and ask the user to pick 3-5 files that represent their best writing.

**Step 2: Mechanical analysis.** Run the analysis script:

```bash
python3 <plugin_root>/scripts/analyze-voice.py --json file1.md file2.md file3.md
```

This extracts: sentence length stats, punctuation habits, contraction rate, first-person usage, vocabulary diversity, frequent content words, and structural patterns.

**Step 3: LLM style analysis.** Read the sample files and extract higher-order observations that the script cannot detect:
- How do paragraphs typically open? (example, claim, question, anecdote)
- What is the overall tone? (direct, conversational, academic, confrontational)
- Does the writing use analogies? From what domain?
- How does the writer handle uncertainty or disagreement?
- Are there signature phrases or constructions?
- What is conspicuously absent? (lists, headers, rhetorical questions, hedging)

**Step 4: Write the profile.** Merge script stats and LLM observations into `config/voice-profile.yaml`:
- Populate `stats` and `punctuation` from the script output
- Populate `style_notes` from LLM analysis (5-10 concise observations)
- Populate `preferred_words` from the top content words that are distinctive (not just common)
- Populate `avoided_words` if any standard words are conspicuously absent
- Record sample file paths and timestamp

**Step 5: Confirm.** Print the profile summary and ask if the user wants to adjust anything.

### Updating the profile

Running `--learn` again replaces the profile. To add to it without replacing, use `--learn --append`.

## Feedback Mode (--feedback)

Refine the voice profile from user edits or direct feedback. This closes the learning loop: salvage writes, user edits, salvage learns.

### Usage

```
/salvage --feedback before.md after.md       # diff two files (salvage output vs user edit)
/salvage --feedback "too formal"             # direct text feedback
/salvage --feedback                          # interactive: ask what to adjust
```

### Workflow

**File diff mode** (`--feedback before.md after.md`):

1. Run the diff script:
   ```bash
   python3 <plugin_root>/scripts/diff-voice.py before.md after.md --json
   ```
   This extracts: word replacements, sentence length shifts, punctuation changes, contraction/first-person adjustments, words added/removed.

2. The LLM interprets the mechanical diff and generates higher-order observations:
   - "User shortened sentences and added contractions — wants more casual tone than 'crisp' preset delivers"
   - "User replaced 'however' with 'but' consistently — prefers informal conjunctions"
   - "User removed all parenthetical asides — dislikes hedging even more than the skill does"

3. Update `config/voice-profile.yaml`:
   - Append observations to `feedback_log` (keeps last 20 entries)
   - If a pattern appears in 3+ feedback entries, promote it to `style_notes`
   - If specific word replacements recur, add to `preferred_words` / `avoided_words`

4. Report what was learned and what changed in the profile.

**Text feedback mode** (`--feedback "too formal"`):

1. Parse the feedback for actionable adjustments
2. Map to profile changes (e.g., "too formal" → lower formality, increase contractions)
3. Update `config/voice-profile.yaml` with the observation
4. Confirm the change

**Interactive mode** (`--feedback` with no args):

1. Ask: "What would you adjust about the last rewrite?"
2. Present options: tone, sentence length, vocabulary, structure, punctuation, other
3. Capture the response and update the profile

### Promotion rules

Feedback observations are logged but not immediately applied as hard rules. Promotion:
- **3 occurrences** of the same pattern → promoted to `style_notes` (soft guidance)
- **5 occurrences** → promoted to `preferred_words`/`avoided_words` (hard rule)
- User can manually promote via `/salvage --feedback promote "observation text"`

## Output Format

### Rewrite mode (default)

Return the rewritten text directly. Follow with a brief report:

```
---
Score: [N]/40
Preset: [name]
Context: [name]
Changes: [count] P0, [count] P1, [count] P2 patterns fixed
```

### Detect mode (--detect)

Run the detection script and return the report. No rewrite is performed.

```bash
python3 <plugin_root>/scripts/detect.py <input> --context <context>
```

If the script is unavailable, return a table of flagged patterns:

```
| Line | Severity | Pattern | Suggestion |
|------|----------|---------|------------|
```

### Prevent mode (--prevent)

Emit a compact system instruction suitable for CLAUDE.md or skill preambles. This prevents slop from being generated in the first place, rather than cleaning it up afterward.

Output:

```markdown
## Writing style

Write direct, specific prose. No filler, no hedging, no AI patterns.

**Never use:** delve, tapestry, landscape, paradigm, leverage, robust, seamless, ecosystem, holistic, nuanced, compelling, innovative, crucial, multifaceted, embark, testament, spearhead, foster, utilize, facilitate, moreover, furthermore, nonetheless, certainly, reimagine, resonate, serves as, stands as.

**Never write:** "it's important to note", "it's worth noting", "in today's", "in an era of", "the power of", "the art of", "at its core", "at the end of the day", "shed light on", "pave the way", "deep dive", "double-edged sword", "here's the thing", "let that sink in", "picture this", "think of it as".

**Structure:** Start with the point. No sweeping openers. No "it's not X, it's Y" contrasts. No self-answered questions. No "final thoughts" closers. Vary sentence length. Use concrete verbs.

**Voice:** State claims directly. Use "I" and "we". Show uncertainty with "I don't know", not "the answer remains nuanced". If a sentence adds nothing, cut it.
```

## Self-Reference Escape Hatch

When writing *about* AI writing patterns (like this skill file itself), flagged vocabulary used in an analytical or meta context is exempt. The test: is the word being used to describe AI behavior, or is it being used AS the AI behavior? Only flag the latter.
