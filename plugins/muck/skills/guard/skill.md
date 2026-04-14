# /muck:guard — Prevent AI slop during generation

Emit a compact writing-style instruction for CLAUDE.md, skill preambles, or system prompts. Prevents slop from being generated in the first place.

## Arguments

$ARGUMENTS — Optional:
- `--format <format>`: `clause` (default — inline paragraph), `section` (## heading block), `minimal` (one-liner)
- `--context <profile>`: Tailor the guard to a specific writing context
- `--voice`: Include voice profile preferences if available

## Workflow

1. Load `config/patterns.yaml` for the canonical word/phrase lists.
2. If `--voice` is set and `config/voice-profile.yaml` has data, incorporate voice preferences.
3. Generate the guard instruction in the requested format.

## Output Formats

### clause (default)

A single paragraph suitable for inserting into any CLAUDE.md or prompt:

```
Write direct, specific prose. No filler, no hedging, no AI patterns. Never use: delve, tapestry, landscape, paradigm, leverage, robust, seamless, ecosystem, holistic, nuanced, compelling, innovative, crucial, multifaceted, embark, testament, spearhead, foster, utilize, facilitate, moreover, furthermore, nonetheless, certainly, reimagine, resonate, serves as, stands as. Never write: "it's important to note", "it's worth noting", "in today's", "in an era of", "the power of", "the art of", "at its core", "at the end of the day", "shed light on", "pave the way", "deep dive", "double-edged sword", "here's the thing", "let that sink in", "picture this", "think of it as". Start with the point. No sweeping openers. No "it's not X, it's Y" contrasts. No self-answered questions. No "final thoughts" closers. Vary sentence length. Use concrete verbs. State claims directly. Use "I" and "we". Show uncertainty with "I don't know", not "the answer remains nuanced". If a sentence adds nothing, cut it.
```

### section

A full markdown section with heading:

```markdown
## Writing style

Write direct, specific prose. No filler, no hedging, no AI patterns.

**Never use:** delve, tapestry, landscape, ...

**Never write:** "it's important to note", ...

**Structure:** Start with the point. ...

**Voice:** State claims directly. ...
```

### minimal

One-liner for tight token budgets:

```
Write like a human: no AI vocabulary (delve/leverage/robust/seamless/ecosystem), no throat-clearing, no "it's not X it's Y", no summaries. Be direct, vary rhythm, use concrete verbs.
```

### With --voice

If a voice profile exists, append personalized constraints:

```
Match this voice: avg 14-word sentences, frequent contractions, rare em-dashes, opens with concrete examples, states disagreements directly, never uses rhetorical questions.
```
