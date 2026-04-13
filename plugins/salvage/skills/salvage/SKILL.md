# /salvage — Remove AI writing patterns and humanize text

Strip AI-generated writing patterns from text using a two-pass workflow: diagnose problems, then reconstruct with a human voice. Synthesized from mshumer/unslop, theclaymethod/unslop, and conorbronsdon/avoid-ai-writing.

## Arguments

$ARGUMENTS — Text to process, provided as:
- Inline text or a file path
- Optional flags: `--preset <voice>`, `--context <profile>`, `--strict`, `--detect`

**Presets (voice):** `crisp` (default), `warm`, `expert`, `story`
**Contexts (tolerance):** `linkedin`, `blog`, `technical`, `email`, `docs`, `casual`
**Modes:** rewrite (default), detect (flag-only with `--detect`)

## Workflow

### Pass 1: Diagnose

Scan the input for AI writing patterns across three categories, in priority order:

**P0 — Credibility killers** (always fix):
- Tier 1 vocabulary (see list below)
- Throat-clearing openers
- "Final thoughts" / "Key takeaways" closers
- Sweeping opening statements before narrowing to topic
- Em-dash overuse (target: zero or near-zero)
- Bold overuse for emphasis
- Chatbot artifacts ("As an AI", "I'd be happy to", knowledge-cutoff disclaimers)

**P1 — Obvious AI patterns** (fix in most contexts):
- Tier 2 vocabulary clusters (3+ in one piece)
- Formulaic structure: hook → context → 3 body sections → takeaway → CTA
- Binary contrasts ("It's not about X, it's about Y")
- Rhetorical question openers
- Significance inflation ("game-changing", "revolutionary")
- Synonym cycling (rotating near-synonyms to fake variety)
- Uniform sentence rhythm (similar length/structure in sequence)
- Excessive bullet lists and numbered lists
- Filler adverbs and hedge phrases

**P2 — Stylistic polish** (fix when strict, tolerate otherwise):
- Tier 3 vocabulary at high density
- Slight over-formality
- Parenthetical hedging
- Generic positive conclusions

For each problem found, note the location and severity.

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

## Vocabulary Tiers

### Tier 1 — Always replace (56 entries)

These words are near-certain AI signals regardless of context.

| Flagged | Replace with |
|---------|-------------|
| delve | dig into, examine, explore |
| tapestry | mix, combination, range |
| landscape | field, market, situation |
| paradigm | model, approach, pattern |
| leverage (verb) | use, apply, build on |
| robust | strong, solid, reliable |
| seamless | smooth, easy, integrated |
| ecosystem | system, network, community |
| holistic | complete, full, whole |
| nuanced | subtle, detailed, specific |
| compelling | strong, convincing, clear |
| innovative | new, original, different |
| crucial | important, key, necessary |
| multifaceted | complex, varied, many-sided |
| embark | start, begin, launch |
| testament | proof, sign, evidence |
| spearhead | lead, drive, start |
| foster | build, grow, encourage |
| underpin | support, form the basis of |
| underscore | show, highlight, stress |
| moreover | also, and, plus |
| furthermore | also, and, besides |
| nonetheless | still, but, yet |
| harnessing | using, applying |
| utilize | use |
| facilitate | help, enable, make possible |
| endeavor | effort, attempt, try |
| commendable | good, impressive, strong |
| noteworthy | notable, worth mentioning |
| intricate | complex, detailed |
| pivotal | key, central, important |
| realm | area, field, world |
| comprehensive | full, complete, thorough |
| arguably | (cut entirely or state the claim directly) |
| indispensable | essential, necessary |
| game-changing | (state the specific change instead) |
| groundbreaking | new, first, original |
| cutting-edge | latest, modern, advanced |
| thought-provoking | interesting, raises questions |
| at the end of the day | (cut entirely) |
| navigate (metaphorical) | handle, manage, work through |
| unlock (metaphorical) | enable, reveal, open |
| shed light on | explain, show, clarify |
| in terms of | for, about, regarding |
| at its core | basically, fundamentally |
| strike a balance | balance, weigh |
| pave the way | lead to, enable, prepare for |
| it's important to note | (cut entirely; just state the thing) |
| it's worth noting | (cut entirely) |
| in today's [X] | (cut entirely or name the specific date/era) |
| in an era of | (cut entirely or be specific) |
| the power of | (cut entirely; describe the effect directly) |
| the art of | (cut entirely) |
| deep dive | detailed look, close examination |
| double-edged sword | tradeoff, has downsides |
| resonate | connect, matter, land |
| reimagine | rethink, redesign, redo |

### Tier 2 — Flag in clusters (3+ triggers a flag)

These are legitimate words that become AI signals when clustered together.

amplify, bolster, catalyze, curate, demystify, elevate, empower, envision, galvanize, juxtapose, optimize, orchestrate, proliferate, propel, revolutionize, streamline, synergy, synthesize, tailor, transcend, underline, unpack, unveil, burgeoning, discerning, evolving, ever-evolving, forward-thinking, granular, meticulous, overarching, proliferating, seminal, symbiotic, top-notch, transformative, unparalleled

### Tier 3 — Flag at high density (5+ per 500 words)

Common words that only signal AI when overused: address, align, approach, challenge, context, dynamic, framework, impact, initiative, integrate, objective, perspective, prioritize, scope, strategy, stakeholder

## Banned Phrases

### Throat-clearing openers (always cut)
"Here's the thing" / "The uncomfortable truth is" / "Let me be clear" / "It turns out" / "Let's be honest" / "Here's what most people get wrong" / "The short answer is" / "The reality is" / "What's fascinating is" / "Picture this" / "Imagine a world where" / "In a world where"

### Emphasis crutches (always cut)
"Full stop." / "Let that sink in." / "Read that again." / "Period." / "I'll say it again."

### Meta-commentary (always cut)
"This is a great question" / "That's an interesting point" / "I appreciate you sharing" / "Let me break this down" / "Let me explain" / "To put it simply"

### Structural closers (always cut or rewrite)
"Final thoughts" / "Key takeaways" / "In conclusion" / "The bottom line" / "Looking ahead" / "Moving forward" / "To sum up" / "At the end of the day" / "What does this mean for you?"

## Structural Patterns to Avoid

1. **The AI opening:** Starting with a broad, sweeping statement about the state of the world before narrowing to the topic. Start with the topic.
2. **The three-act template:** Intro hook, context, exactly 3 body sections, takeaway, CTA. Vary your structure.
3. **The binary contrast:** "It's not about X, it's about Y." State what it IS about.
4. **The false range:** "From X to Y" used to sound comprehensive without being specific.
5. **The rhetorical question opener:** "Have you ever wondered...?" "What if I told you...?" Just make the point.
6. **The dramatic fragment:** "And here's why." "One word: resilience." "The result? Transformation." Write complete thoughts.
7. **The synonym cycle:** Rotating near-synonyms across sentences to fake lexical variety. Pick the right word and use it.
8. **The uniform rhythm:** Sequences of sentences with similar length and structure. Mix short and long. Interrupt patterns.

## Voice Presets

### crisp (default)
Short, direct sentences. 5-15 words average. Cut ruthlessly. One idea per sentence. No hedging. If a word doesn't earn its place, delete it. Prefer periods over commas.

### warm
Friendly, conversational. 8-20 words average. Use contractions. Address the reader occasionally. Soft landings — end paragraphs with something human, not a lecture. Like explaining to a smart friend.

### expert
Authoritative, confident. 10-25 words average. Make claims without hedging. Show expertise through specifics, not credentials. Use numbers and names. Skip "I think" — just state what you know.

### story
Narrative flow. Varied sentence length (5-30 words). Structure as scene, tension, resolution, insight. One story, one point. Let readers draw their own conclusions from the evidence you present.

## Context Profiles

Different contexts tolerate different levels of formality. Adjust the rewrite threshold accordingly.

| Pattern | linkedin | blog | technical | email | docs | casual |
|---------|----------|------|-----------|-------|------|--------|
| Tier 1 vocab | fix | fix | fix | fix | fix | fix |
| Tier 2 clusters | fix | fix | tolerate | fix | tolerate | fix |
| Throat-clearing | fix | fix | fix | fix | tolerate | fix |
| Structural template | fix | fix | tolerate | fix | tolerate | fix |
| Formal tone | tolerate | fix | tolerate | fix | tolerate | fix |
| Em-dash density | fix | fix | tolerate | fix | tolerate | fix |

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

Return a table of flagged patterns:

```
| Line | Severity | Pattern | Suggestion |
|------|----------|---------|------------|
```

No rewrite is performed in detect mode.

## Self-Reference Escape Hatch

When writing *about* AI writing patterns (like this skill file itself), flagged vocabulary used in an analytical or meta context is exempt. The test: is the word being used to describe AI behavior, or is it being used AS the AI behavior? Only flag the latter.
