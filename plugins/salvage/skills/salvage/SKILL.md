# /salvage — Remove AI writing patterns and humanize text

Strip AI-generated writing patterns from text using a diagnose-reconstruct-audit workflow. Synthesized from mshumer/unslop, theclaymethod/unslop, conorbronsdon/avoid-ai-writing, tropes.fyi, and hardikpandya/stop-slop.

## Arguments

$ARGUMENTS — Text to process, provided as:
- Inline text or a file path
- Optional flags: `--preset <voice>`, `--context <profile>`, `--strict`, `--detect`, `--prevent`

**Presets (voice):** `crisp` (default), `warm`, `expert`, `story`
**Contexts (tolerance):** `linkedin`, `blog`, `technical`, `email`, `docs`, `casual`
**Modes:** rewrite (default), detect (flag-only with `--detect`), prevent (emit system instruction with `--prevent`)

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

Rewrite the text applying the selected voice preset, preserving all facts.

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
