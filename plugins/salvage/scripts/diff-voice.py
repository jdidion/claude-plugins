#!/usr/bin/env python3
"""Compare salvage output with user-edited version to extract voice preferences.

Compares two texts (before/after user edits) and identifies patterns:
- Words the user consistently replaces
- Structural changes (sentence splitting/merging, reordering)
- Punctuation adjustments
- Tone shifts

Usage:
    python3 diff-voice.py salvage-output.md user-edited.md
    python3 diff-voice.py salvage-output.md user-edited.md --json
    python3 diff-voice.py --text-feedback "too formal, needs more contractions"
"""

import argparse
import difflib
import json
import re
import string
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml


def load_profile():
    config_path = Path(__file__).parent.parent / "config" / "voice-profile.yaml"
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def save_profile(profile):
    config_path = Path(__file__).parent.parent / "config" / "voice-profile.yaml"
    with open(config_path, "w") as f:
        yaml.dump(profile, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def tokenize(text):
    """Split text into words, preserving punctuation as separate tokens."""
    return re.findall(r"\b\w+\b|[^\w\s]", text)


def analyze_diff(before_text, after_text):
    """Analyze differences between salvage output and user edits."""
    # Word-level diff
    before_words = tokenize(before_text.lower())
    after_words = tokenize(after_text.lower())

    # Words removed by user (salvage added them, user didn't want them)
    before_counts = Counter(before_words)
    after_counts = Counter(after_words)

    words_removed = {}
    words_added = {}
    for word in set(before_counts.keys()) | set(after_counts.keys()):
        diff = after_counts.get(word, 0) - before_counts.get(word, 0)
        if diff < -1 and word not in string.punctuation:
            words_removed[word] = abs(diff)
        elif diff > 1 and word not in string.punctuation:
            words_added[word] = diff

    # Sentence-level changes
    before_sents = re.split(r"[.!?]+", before_text)
    after_sents = re.split(r"[.!?]+", after_text)
    before_sents = [s.strip() for s in before_sents if s.strip()]
    after_sents = [s.strip() for s in after_sents if s.strip()]

    before_avg_len = sum(len(s.split()) for s in before_sents) / max(len(before_sents), 1)
    after_avg_len = sum(len(s.split()) for s in after_sents) / max(len(after_sents), 1)

    # Punctuation changes
    punct_changes = {}
    for char, name in [("—", "em_dashes"), (";", "semicolons"), ("!", "exclamations"),
                       ("?", "questions"), ("(", "parentheses"), ("...", "ellipses")]:
        before_n = before_text.count(char)
        after_n = after_text.count(char)
        if before_n != after_n:
            punct_changes[name] = {"before": before_n, "after": after_n,
                                   "direction": "increased" if after_n > before_n else "decreased"}

    # Contraction changes
    before_contractions = len(re.findall(r"\b\w+'\w+\b", before_text))
    after_contractions = len(re.findall(r"\b\w+'\w+\b", after_text))

    # First person changes
    fp_pattern = r"\b[Ii]\b|\b[Mm]y\b|\b[Mm]e\b|\b[Ww]e\b|\b[Oo]ur\b"
    before_fp = len(re.findall(fp_pattern, before_text))
    after_fp = len(re.findall(fp_pattern, after_text))

    # Word-level replacements (find substitution pairs)
    replacements = []
    matcher = difflib.SequenceMatcher(None, before_words, after_words)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "replace":
            old_phrase = " ".join(before_words[i1:i2])
            new_phrase = " ".join(after_words[j1:j2])
            if len(old_phrase) < 50 and len(new_phrase) < 50:
                replacements.append({"old": old_phrase, "new": new_phrase})

    observations = []

    # Generate observations
    len_diff = after_avg_len - before_avg_len
    if abs(len_diff) > 3:
        direction = "longer" if len_diff > 0 else "shorter"
        observations.append(f"User prefers {direction} sentences (avg {after_avg_len:.0f} vs salvage's {before_avg_len:.0f} words)")

    if after_contractions > before_contractions + 2:
        observations.append("User added more contractions — prefers conversational tone")
    elif before_contractions > after_contractions + 2:
        observations.append("User removed contractions — prefers formal tone")

    if after_fp > before_fp + 2:
        observations.append("User added more first-person pronouns")
    elif before_fp > after_fp + 2:
        observations.append("User removed first-person pronouns — prefers impersonal style")

    for name, change in punct_changes.items():
        observations.append(f"User {change['direction']} {name}: {change['before']} -> {change['after']}")

    if words_removed:
        top_removed = sorted(words_removed.items(), key=lambda x: -x[1])[:5]
        observations.append(f"Words user removed: {', '.join(w for w, _ in top_removed)}")

    if words_added:
        top_added = sorted(words_added.items(), key=lambda x: -x[1])[:5]
        observations.append(f"Words user added: {', '.join(w for w, _ in top_added)}")

    if replacements:
        top_replacements = replacements[:10]
        for r in top_replacements:
            observations.append(f"Replaced '{r['old']}' -> '{r['new']}'")

    return {
        "sentence_length_shift": round(len_diff, 1),
        "contraction_change": after_contractions - before_contractions,
        "first_person_change": after_fp - before_fp,
        "punctuation_changes": punct_changes,
        "words_removed": dict(sorted(words_removed.items(), key=lambda x: -x[1])[:10]),
        "words_added": dict(sorted(words_added.items(), key=lambda x: -x[1])[:10]),
        "replacements": replacements[:15],
        "observations": observations,
    }


def update_profile_from_feedback(observations, text_feedback=None):
    """Append feedback observations to the voice profile."""
    profile = load_profile()

    if "feedback_log" not in profile:
        profile["feedback_log"] = []

    entry = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "observations": observations,
    }
    if text_feedback:
        entry["text_feedback"] = text_feedback

    profile["feedback_log"].append(entry)

    # Keep last 20 feedback entries
    if len(profile["feedback_log"]) > 20:
        profile["feedback_log"] = profile["feedback_log"][-20:]

    save_profile(profile)
    return profile


def main():
    parser = argparse.ArgumentParser(description="Compare salvage output with user edits")
    parser.add_argument("files", nargs="*", help="Two files: salvage-output user-edited")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--text-feedback", type=str, help="Direct text feedback (no file diff)")
    parser.add_argument("--save", action="store_true", help="Save observations to voice profile")
    args = parser.parse_args()

    if args.text_feedback:
        observations = [args.text_feedback]
        if args.save:
            update_profile_from_feedback(observations, text_feedback=args.text_feedback)
            print(f"Saved text feedback to voice profile")
        else:
            print(f"Feedback: {args.text_feedback}")
            print("Run with --save to persist to voice profile")
        return

    if len(args.files) != 2:
        print("Usage: diff-voice.py <salvage-output> <user-edited> [--json] [--save]", file=sys.stderr)
        sys.exit(1)

    before = Path(args.files[0]).read_text()
    after = Path(args.files[1]).read_text()

    result = analyze_diff(before, after)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Voice feedback analysis ({len(result['observations'])} observations):\n")
        for obs in result["observations"]:
            print(f"  - {obs}")

        if result["replacements"]:
            print(f"\nTop replacements:")
            for r in result["replacements"][:5]:
                print(f"  '{r['old']}' -> '{r['new']}'")

    if args.save and result["observations"]:
        update_profile_from_feedback(result["observations"])
        print(f"\nSaved {len(result['observations'])} observations to voice profile")


if __name__ == "__main__":
    main()
