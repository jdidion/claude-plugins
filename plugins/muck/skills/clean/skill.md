# /muck:clean — Rewrite text to remove AI slop

Strip AI-generated writing patterns from text using a diagnose-reconstruct-audit workflow. Preserves all facts while making the text sound human.

## Arguments

$ARGUMENTS — Text to clean, provided as:
- Inline text or a file path
- Optional flags: `--preset <voice>`, `--context <profile>`, `--strict`

**Presets (voice):** `crisp` (default), `warm`, `expert`, `story`
**Contexts (tolerance):** `linkedin`, `blog`, `technical`, `email`, `docs`, `casual`

## Workflow

### Pass 1: Diagnose (script-assisted)

Run the detection script:

```bash
python3 <plugin_root>/scripts/detect.py <input> --context <context> --json
```

All word lists live in `config/patterns.yaml`. If the script is unavailable, diagnose inline.

### Pass 2: Reconstruct

If `config/voice-profile.yaml` exists and has non-null values, load it and apply the user's voice:
- Match sentence length to their statistical profile (mean and variance)
- Match punctuation habits (em-dash frequency, semicolon usage, etc.)
- Apply style notes as additional constraints
- Prefer their vocabulary preferences; avoid their avoided words
- Follow their structural patterns (opener style, closer style, paragraph length)

If no voice profile, fall back to the selected voice preset.

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
Short, direct sentences. 5-15 words average. Cut ruthlessly. One idea per sentence. No hedging. Prefer periods over commas.

### warm
Friendly, conversational. 8-20 words average. Use contractions. Like explaining to a smart friend.

### expert
Authoritative, confident. 10-25 words average. Make claims without hedging. Show expertise through specifics, not credentials.

### story
Narrative flow. Varied sentence length (5-30 words). Scene, tension, resolution, insight. Let readers draw conclusions.

## Scoring Rubric

Score on 8 criteria, 1-5 each. **32/40 to pass.**

| Criterion | 1 (AI-obvious) | 5 (human-natural) |
|-----------|----------------|-------------------|
| **Directness** | Buries the point | Opens with the point |
| **Rhythm** | Uniform length | Varied, unpredictable |
| **Concrete verbs** | Abstract/passive | Active/specific |
| **Reader trust** | Tells what to think | Presents evidence |
| **Authenticity** | Press release | Specific person |
| **Content density** | Filler pads it | Every sentence carries weight |
| **Fact preservation** | Facts altered | All facts preserved |
| **Pattern avoidance** | AI patterns remain | No detectable patterns |

## Fact Preservation Rules

**Absolute preservation (never change):**
Numbers, dates, percentages, proper nouns, technical terms, quoted material, URLs, code, cause-and-effect relationships, comparative claims.

**Semantic preservation (meaning must survive):**
Author's stance, scope qualifiers ("some" vs "all"), sequence and causation.

## Output

Return the rewritten text, followed by:

```
---
Score: [N]/40
Preset: [name]
Context: [name]
Changes: [count] P0, [count] P1, [count] P2 patterns fixed
```

## Self-Reference Escape Hatch

When writing *about* AI patterns, flagged vocabulary used analytically is exempt. Test: is the word describing AI behavior, or being used AS AI behavior?
