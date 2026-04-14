# /muck:voice — Learn and refine your writing voice

Build and refine a voice profile so `/muck:clean` and `/muck:guard` match your natural writing style. Two modes: learn (from samples) and feedback (from edits).

## Arguments

$ARGUMENTS — Mode and inputs:
- `--learn [files...]` — analyze writing samples to build a profile
- `--feedback [before.md after.md]` — refine profile from your edits
- `--feedback "text"` — direct text feedback
- `--show` — display current voice profile
- `--reset` — clear the voice profile

## Learn Mode (--learn)

Build a voice profile from writing samples.

### Usage

```
/muck:voice --learn file1.md file2.md file3.md    # analyze specific files
/muck:voice --learn                                # open file browser to choose
```

### Workflow

**Step 1: Select samples.** If no files provided, browse for them:
1. Check for `gum` CLI (`gum file --all`). If available, use it as a TUI file picker.
2. Otherwise, Glob for `.md`, `.txt`, `.org` files in working directory and common locations.
3. Present the list and ask the user to pick 3-5 files of their best writing.

**Step 2: Mechanical analysis.**

```bash
python3 <plugin_root>/scripts/analyze-voice.py --json file1.md file2.md file3.md
```

Extracts: sentence length stats, punctuation habits, contraction rate, first-person usage, vocabulary diversity, frequent content words, structural patterns.

**Step 3: LLM style analysis.** Read the samples and extract higher-order observations:
- How do paragraphs typically open? (example, claim, question, anecdote)
- What is the overall tone? (direct, conversational, academic, confrontational)
- Does the writing use analogies? From what domain?
- How does the writer handle uncertainty or disagreement?
- Are there signature phrases or constructions?
- What is conspicuously absent? (lists, headers, rhetorical questions, hedging)

**Step 4: Write the profile.** Merge script stats and LLM observations into `config/voice-profile.yaml`:
- `stats` and `punctuation` from the script
- `style_notes` from LLM analysis (5-10 concise observations)
- `preferred_words` from distinctive top content words
- `avoided_words` if standard words are conspicuously absent
- Record sample file paths and timestamp

**Step 5: Confirm.** Print the profile summary and ask if the user wants to adjust anything.

Running `--learn` again replaces the profile. Use `--learn --append` to add without replacing.

## Feedback Mode (--feedback)

Refine the voice profile from user edits or direct feedback. Closes the learning loop: muck writes, user edits, muck learns.

### File diff mode

```
/muck:voice --feedback before.md after.md
```

1. Run the diff script:
   ```bash
   python3 <plugin_root>/scripts/diff-voice.py before.md after.md --json
   ```
   Extracts: word replacements, sentence length shifts, punctuation changes, contraction/first-person adjustments.

2. LLM interprets the diff and generates higher-order observations.

3. Update `config/voice-profile.yaml`:
   - Append observations to `feedback_log` (keeps last 20 entries)
   - If a pattern appears in 3+ feedback entries, promote to `style_notes`
   - If specific word replacements recur, add to `preferred_words` / `avoided_words`

4. Report what was learned and what changed.

### Text feedback mode

```
/muck:voice --feedback "too formal, more contractions"
```

Parse feedback, map to profile changes, update voice-profile.yaml, confirm.

### Interactive mode

```
/muck:voice --feedback
```

Ask what to adjust, present options (tone, sentence length, vocabulary, structure, punctuation), capture response, update profile.

### Promotion rules

- **3 occurrences** → promoted to `style_notes` (soft guidance)
- **5 occurrences** → promoted to `preferred_words`/`avoided_words` (hard rule)
- Manual promote: `/muck:voice --feedback promote "observation text"`

## Show Mode (--show)

Display the current voice profile in a readable summary:

```
Voice profile (last updated 2026-04-14, 3 samples):

Stats: 14.2 avg words/sentence (std 7.1), 18.3 contractions/1k, 12.7 first-person/1k
Punctuation: rare em-dashes (0.3/1k), moderate semicolons (2.1/1k)
Style: opens with examples, direct disagreement, short paragraphs, no rhetorical questions
Preferred: "but", "also", "just", "actually"
Avoided: "however", "additionally", "furthermore"
Feedback: 4 logged observations, 1 promoted to style_notes
```
