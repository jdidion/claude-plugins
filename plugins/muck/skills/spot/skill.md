# /muck:spot — Detect AI writing patterns

Scan text for AI slop without rewriting. Returns a diagnostic report of flagged vocabulary, banned phrases, and structural patterns.

## Arguments

$ARGUMENTS — Text to scan, provided as:
- Inline text, a file path, or piped from another command
- Optional: `--context <profile>` (linkedin, blog, technical, email, docs, casual; default: blog)

## Workflow

Run the detection script:

```bash
python3 <plugin_root>/scripts/detect.py <input> --context <context>
```

The script checks against `config/patterns.yaml`:
- **Tier 1** (62 entries) — near-certain AI signals, always flagged
- **Tier 2** (38 entries) — legitimate words that become AI signals when clustered (3+)
- **Tier 3** (16 entries) — common words that signal AI only at high density (5+ per 500 words)
- **Banned phrases** — throat-clearing, emphasis crutches, meta-commentary, structural closers, chatbot artifacts
- **Structural patterns** — em-dash overuse, bold overuse, binary contrasts, triple-negation reveals, self-answered questions, uniform sentence rhythm, punchy fragment overuse

If the script is unavailable, diagnose inline using the same categories.

## Severity Levels

- **P0 — Credibility killers**: Tier 1 vocabulary, throat-clearing, chatbot artifacts, em-dash overuse, "serves as" dodge
- **P1 — Obvious AI patterns**: Tier 2 clusters, formulaic structure, binary contrasts, significance inflation, false vulnerability, vague attributions, invented concept labels
- **P2 — Stylistic polish**: Tier 3 density, over-formality, fractal summaries, content duplication

## Context Profiles

Different contexts tolerate different patterns. See `config/patterns.yaml` for the full tolerance matrix. Example: `--context technical` tolerates em-dashes and Tier 2 clusters.

## Output

```
Detected 12 issues (5 P0, 4 P1, 3 P2) in 342 words

| Line | Severity | Pattern | Suggestion |
|------|----------|---------|------------|
| 3    | P0       | Tier 1: 'leverage' | use, apply, build on |
| ...  | ...      | ...     | ...        |
```

For machine-readable output, add `--json` to the script invocation.
