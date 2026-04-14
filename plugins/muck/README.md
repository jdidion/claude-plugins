# muck

Four tools for fighting AI slop: spot it, guard against it, clean it up, and learn your voice.

## Commands

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/muck:spot` | Detect slop | Before submitting — "how sloppy is this?" |
| `/muck:guard` | Prevent slop | When configuring CLAUDE.md or skill preambles |
| `/muck:clean` | Remove slop | After drafting — rewrite with human voice |
| `/muck:voice` | Learn your voice | Periodically — teach muck how you write |

## Quick start

```bash
# Detect slop in a file
/muck:spot draft.md

# Clean up a sloppy draft
/muck:clean draft.md --preset crisp

# Generate a guard clause for CLAUDE.md
/muck:guard --format section

# Teach muck your voice from writing samples
/muck:voice --learn essay.md blogpost.md memo.md

# Refine voice from your edits
/muck:voice --feedback muck-output.md my-edit.md

# Direct feedback
/muck:voice --feedback "too formal, shorter sentences"

# See your voice profile
/muck:voice --show
```

## Examples

### /muck:spot

```
/muck:spot draft.md --context linkedin
```

```
Detected 8 issues (4 P0, 3 P1, 1 P2) in 230 words

| Line | Severity | Pattern                              | Suggestion                 |
|------|----------|--------------------------------------|----------------------------|
| 1    | P0       | Tier 1: 'leverage'                   | use, apply, build on       |
| 1    | P0       | Tier 1: 'ecosystem'                  | system, network, community |
| 3    | P0       | Banned: 'Here's the thing'           | Cut entirely               |
| 5    | P1       | Binary contrast: 'It's not X, it's Y'| State what it IS about    |
```

### /muck:clean

Input:
```
In today's rapidly evolving landscape, it's important to note that leveraging
robust AI ecosystems is crucial for fostering innovative solutions.
```

Output (crisp preset):
```
AI systems work better when you pick the right parts and connect them.
We cut pipeline errors 40% by switching to modular tools.

---
Score: 37/40
Preset: crisp
Context: blog
Changes: 6 P0, 1 P1, 0 P2 patterns fixed
```

### /muck:guard

```
/muck:guard --format minimal
```

```
Write like a human: no AI vocabulary (delve/leverage/robust/seamless/ecosystem),
no throat-clearing, no "it's not X it's Y", no summaries. Be direct, vary rhythm,
use concrete verbs.
```

### /muck:voice --learn

```
/muck:voice --learn essay.md blogpost.md memo.md
```

```
Analyzed 3 samples (4,200 words, 312 sentences)

Sentence length:  mean=14.2 words, std_dev=7.1, range=3-38
Contractions:     18.3/1000 words (high — conversational)
First person:     12.7/1000 words (moderate)
Em-dashes:        0.3/1000 words (rare)

Style notes:
  - Opens paragraphs with concrete examples, not abstractions
  - Uses analogies from biology and engineering
  - States disagreements directly without softening
  - Prefers short paragraphs (2-3 sentences)
  - Never uses rhetorical questions

Saved to config/voice-profile.yaml
```

### /muck:voice --feedback

```
/muck:voice --feedback muck-output.md my-edits.md
```

```
Voice feedback analysis (4 observations):

  - User prefers shorter sentences (avg 11 vs muck's 16 words)
  - User added more contractions — prefers conversational tone
  - Replaced 'however' -> 'but'
  - Replaced 'additionally' -> 'also'

Saved 4 observations to voice profile (3 more to promote to style_notes)
```

## Voice presets

| Preset | Style | Sentence length | Best for |
|--------|-------|----------------|----------|
| `crisp` | Terse, direct | 5-15 words | Emails, Slack, docs |
| `warm` | Conversational | 8-20 words | Blog posts, READMEs |
| `expert` | Authoritative | 10-25 words | Reports, papers |
| `story` | Narrative | 5-30 words | Case studies, talks |

## Context profiles

| Pattern | linkedin | blog | technical | email | docs | casual |
|---------|----------|------|-----------|-------|------|--------|
| Tier 1 vocab | fix | fix | fix | fix | fix | fix |
| Tier 2 clusters | fix | fix | tolerate | fix | tolerate | fix |
| Throat-clearing | fix | fix | fix | fix | tolerate | fix |
| Structural template | fix | fix | tolerate | fix | tolerate | fix |
| Formal tone | tolerate | fix | tolerate | fix | tolerate | fix |
| Em-dash density | fix | fix | tolerate | fix | tolerate | fix |

## Shared resources

All four skills share:
- `config/patterns.yaml` — 62 Tier 1, 38 Tier 2, 16 Tier 3 flagged words + 42 banned phrases + context profiles
- `config/voice-profile.yaml` — learned voice preferences and feedback log
- `scripts/detect.py` — mechanical pattern scanner (runs outside LLM)
- `scripts/analyze-voice.py` — writing sample statistical analysis
- `scripts/diff-voice.py` — before/after edit comparison

Scripts require PyYAML (`pip install pyyaml`).

## Sources

Synthesized from:

- [mshumer/unslop](https://github.com/mshumer/unslop) — original unslop prompt
- [theclaymethod/unslop](https://github.com/theclaymethod/unslop) — vocabulary tiers and scoring
- [conorbronsdon/avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing) — avoidance guidelines
- [tropes.fyi](https://tropes.fyi) — comprehensive AI writing trope directory
- [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) — scoring rubric and quick checks
- [Stephen Turner — "De-slop"](https://blog.stephenturner.us/p/deslop) — Claude skill with tropes.fyi + stop-slop synthesis
