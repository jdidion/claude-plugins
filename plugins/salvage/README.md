# salvage

Claude Code skill that strips AI-generated writing patterns from text using a diagnose-reconstruct-audit workflow.

## Usage

```
/salvage <text or file>                    # rewrite with default settings
/salvage <file> --preset expert            # authoritative voice
/salvage <file> --context linkedin          # linkedin-tolerant thresholds
/salvage <file> --detect                    # flag patterns without rewriting
/salvage --prevent                          # emit a compact system instruction for CLAUDE.md
```

**Presets:** `crisp` (default), `warm`, `expert`, `story`
**Contexts:** `linkedin`, `blog`, `technical`, `email`, `docs`, `casual`

## Examples

### Rewrite mode (default)

Input:
```
In today's rapidly evolving landscape, it's important to note that leveraging
robust AI ecosystems is crucial for fostering innovative solutions. This
groundbreaking approach serves as a testament to the power of holistic
thinking. Here's the thing — it's not about the tools, it's about the mindset.
```

Output (crisp preset):
```
AI systems work better when you pick the right parts and connect them well.
We saw a 40% reduction in pipeline errors after switching to modular tools.
The mindset matters: build small, test often, replace what breaks.

---
Score: 36/40
Preset: crisp
Context: blog
Changes: 8 P0, 2 P1, 0 P2 patterns fixed
```

### Detect mode

```
/salvage draft.md --detect --context linkedin
```

Output:
```
Detected 5 issues (3 P0, 2 P1, 0 P2) in 142 words

| Line | Severity | Pattern                              | Suggestion                      |
|------|----------|--------------------------------------|---------------------------------|
| 3    | P0       | Tier 1: 'leverage'                   | use, apply, build on            |
| 3    | P0       | Tier 1: 'ecosystem'                  | system, network, community      |
| 7    | P0       | Banned (throat_clearing): 'Picture this' | Cut entirely or rewrite     |
| 5    | P1       | Binary contrast: 'It's not X, it's Y'  | State what it IS about       |
| -    | P1       | Uniform rhythm: variance=2.3 (avg 14 words) | Mix short and long sentences |
```

### Prevent mode

```
/salvage --prevent
```

Emits a compact writing-style instruction you can paste into any CLAUDE.md or skill preamble. The LLM then avoids generating slop in the first place rather than cleaning it up after.

### Voice presets

| Preset | Style | Sentence length | Best for |
|--------|-------|----------------|----------|
| `crisp` | Terse, direct | 5-15 words | Emails, Slack, docs |
| `warm` | Conversational, friendly | 8-20 words | Blog posts, READMEs |
| `expert` | Authoritative, confident | 10-25 words | Technical writing, reports |
| `story` | Narrative, varied | 5-30 words | Case studies, talks |

### Context profiles

Different contexts tolerate different levels of AI patterns. The `--context` flag adjusts thresholds:

| Pattern | linkedin | blog | technical | email | docs | casual |
|---------|----------|------|-----------|-------|------|--------|
| Tier 1 vocab | fix | fix | fix | fix | fix | fix |
| Tier 2 clusters | fix | fix | tolerate | fix | tolerate | fix |
| Throat-clearing | fix | fix | fix | fix | tolerate | fix |
| Structural template | fix | fix | tolerate | fix | tolerate | fix |
| Formal tone | tolerate | fix | tolerate | fix | tolerate | fix |
| Em-dash density | fix | fix | tolerate | fix | tolerate | fix |

For example, `--context technical` tolerates em-dashes and Tier 2 clusters (common in technical prose), while `--context linkedin` flags everything except formal tone.

### Scoring rubric

The skill scores output on 8 criteria (1-5 each, 40 max, 32 to pass):

1. **Directness** — does it open with the point?
2. **Rhythm** — is sentence length varied and unpredictable?
3. **Concrete verbs** — active/specific ("built") over abstract/passive ("was implemented")?
4. **Reader trust** — presents evidence, or tells the reader what to think?
5. **Authenticity** — sounds like a person, or like a press release?
6. **Content density** — every sentence carries weight, or filler pads it out?
7. **Fact preservation** — all facts exactly preserved from original?
8. **Pattern avoidance** — no detectable AI patterns remain?

## How it works

1. **Diagnose** — `scripts/detect.py` mechanically scans for flagged vocabulary, banned phrases, and structural patterns against `config/patterns.yaml`. This runs outside the LLM to save tokens.
2. **Reconstruct** — the LLM rewrites the text using the selected voice preset, preserving all facts.
3. **Audit** — re-scan the rewrite for remaining patterns and report a score (32/40 to pass).

## Detection script

The detection script runs independently:

```bash
python3 scripts/detect.py "your text here" --context blog
python3 scripts/detect.py input.md --json    # machine-readable output
cat draft.md | python3 scripts/detect.py -   # stdin
```

Requires PyYAML (`pip install pyyaml`).

## Pattern database

All flagged words, phrases, and context profiles live in `config/patterns.yaml`:
- **Tier 1** (62 entries) — near-certain AI signals, always replace
- **Tier 2** (38 entries) — legitimate words that become AI signals when clustered (3+)
- **Tier 3** (16 entries) — common words that signal AI only at high density (5+ per 500 words)
- **Banned phrases** — throat-clearing openers, emphasis crutches, meta-commentary, structural closers, chatbot artifacts

## Sources

This skill synthesizes patterns and approaches from:

- [mshumer/unslop](https://github.com/mshumer/unslop) — original unslop prompt for removing AI writing patterns
- [theclaymethod/unslop](https://github.com/theclaymethod/unslop) — expanded unslop with vocabulary tiers and scoring
- [conorbronsdon/avoid-ai-writing](https://github.com/conorbronsdon/avoid-ai-writing) — AI writing avoidance guidelines
- [tropes.fyi](https://tropes.fyi) — comprehensive directory of AI writing tropes and patterns
- [hardikpandya/stop-slop](https://github.com/hardikpandya/stop-slop) — skill file for removing AI tells from prose (scoring rubric, quick checks)
- [Stephen Turner — "De-slop the text you shouldn't be writing anyway"](https://blog.stephenturner.us/p/deslop) — Claude skill by a UVA bioinformatician; references tropes.fyi and stop-slop
