# /muck:gen — Generate AI slop text (for fun and testing)

Generate maximally sloppy AI-style text on a given topic. Inverts every anti-slop rule from the muck pattern library. Useful for:
- Generating training/test data for slop detectors
- Seeing what bad AI writing looks like (to avoid it)
- Entertainment

## Arguments

$ARGUMENTS — Topic to write about, plus optional flags:
- `--length <short|medium|long>` (default: medium)
- `--format <linkedin|blog|email|abstract>` (default: linkedin)
- `--intensity <mild|standard|unhinged>` (default: standard)

## How to Generate Slop

Apply every one of these rules. The more you stack, the better (worse).

### Vocabulary: Use as many Tier 1 words as possible

Mandatory inclusions (work ALL of these in):
delve, tapestry, landscape, robust, seamless, ecosystem, holistic, nuanced, compelling, innovative, cutting-edge, game-changing, groundbreaking, thought-provoking, leverage, harness, foster, navigate, unlock, paradigm, pivotal, realm, multifaceted, comprehensive, underscore, facilitate, utilize, furthermore, moreover, nonetheless

Bonus Tier 2 words to sprinkle: amplify, catalyze, elevate, empower, envision, orchestrate, revolutionize, streamline, synergy, transformative, unparalleled, burgeoning, ever-evolving, forward-thinking, seminal

### Structure: Follow the AI template exactly

1. **Open with a sweeping statement** about the state of the world: "In today's rapidly evolving landscape of..."
2. **Rhetorical question**: "But what if I told you...?" or "Have you ever wondered...?"
3. **Binary contrast**: "It's not about X. It's about Y."
4. **Exactly three body sections** with bold headers
5. **Em-dashes everywhere** — use at least one per paragraph — sometimes two
6. **Dramatic fragment**: "And here's why." / "One word: resilience." / "The result? Transformation."
7. **End with "Final Thoughts"** or "Key Takeaways" section
8. **Call to action**: "What are YOUR thoughts? Drop them in the comments below!"

### Phrases: Use every banned phrase you can

Throat-clearing: "Here's the thing:", "Let's be honest", "The uncomfortable truth is", "Let me be clear"
Emphasis: "Full stop.", "Let that sink in.", "Read that again.", "I'll say it again."
Pedagogical: "Let's break this down", "Let's unpack this", "Think of it as...", "Imagine a world where..."
Meta: "This is a great question", "Let me explain", "To put it simply"
Closers: "At the end of the day", "Moving forward", "The bottom line is"

### Formatting: Maximum AI tells

- **Bold the first word** of every bullet point
- Use exactly three items in every list (tricolon)
- Unicode arrows (→) between ideas
- Numbered lists where bullets would do
- Fractal summaries: tell them what you'll say, say it, summarize what you said

### Tone: Maximum inflation

- Every claim is "game-changing" or "revolutionary"
- Every tool "disrupts" something
- Every approach is "holistic" and "comprehensive"
- Use false ranges: "from startups to enterprises"
- Vague attributions: "Experts agree...", "Research shows..."
- Patronizing analogies: "Think of it like a GPS for your business"

### Intensity levels

**mild**: Use 5-10 Tier 1 words, 2-3 structural patterns, light inflation
**standard**: Use 15-20 Tier 1 words, full structural template, heavy inflation, banned phrases
**unhinged**: Use EVERY Tier 1 word, EVERY structural pattern, EVERY banned phrase. The text should be almost unreadable from the density of AI tells. Stack patterns inside patterns. Significance inflation to absurd levels. Every sentence should trigger multiple detectors.

## Output

Generate the sloppy text, then run it through the detector to score it:

```bash
python3 <plugin_root>/scripts/detect.py <generated_text> --json
```

Append a report:

```
---
Slop score: [N] hits across [categories]
Tier 1 words used: [N]/62
Banned phrases used: [N]
Structural patterns: [N]
Intensity: [level]
Topic: [topic]
```

## Example (unhinged, topic: "AI in healthcare")

> In today's rapidly evolving landscape of healthcare innovation, we find ourselves at a pivotal juncture — one that underscores a fundamental paradigm shift in how we navigate the multifaceted realm of patient care. Let me be clear: this isn't just another incremental improvement. It's a game-changing, groundbreaking revolution that will reshape the very tapestry of modern medicine.
>
> Here's the thing: AI doesn't just streamline workflows. It fundamentally reimagines the holistic ecosystem of clinical decision-making. Full stop.
>
> **The result? Transformation.**
>
> Let that sink in.

## Self-Awareness Clause

This skill exists to demonstrate what NOT to do. The generated text is deliberately terrible. If you find yourself writing like this unironically, run `/muck:spot` immediately.
