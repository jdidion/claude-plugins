#!/usr/bin/env python3
"""Mechanical AI-slop detection for the salvage skill.

Scans text for flagged vocabulary, banned phrases, and structural patterns.
Outputs a diagnostic report so the LLM only handles reconstruction.

Usage:
    python3 detect.py <file_or_text> [--context linkedin|blog|technical|email|docs|casual]
    echo "text" | python3 detect.py - [--context blog]
    python3 detect.py --json <file>   # machine-readable output
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml


def load_patterns():
    config_path = Path(__file__).parent.parent / "config" / "patterns.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def count_words(text):
    return len(text.split())


def find_tier1(text, patterns):
    hits = []
    text_lower = text.lower()
    for word, replacement in patterns["tier1"].items():
        # Strip annotations like "(verb)" or "(metaphorical)"
        search_term = re.sub(r"\s*\(.*?\)\s*", " ", word).strip().lower()
        if search_term in text_lower:
            # Find line numbers
            for i, line in enumerate(text.split("\n"), 1):
                if search_term in line.lower():
                    hits.append({
                        "line": i,
                        "severity": "P0",
                        "pattern": f"Tier 1: '{word}'",
                        "suggestion": replacement,
                    })
    return hits


def find_tier2_clusters(text, patterns):
    hits = []
    text_lower = text.lower()
    found = []
    for word in patterns["tier2"]["words"]:
        if word.lower() in text_lower:
            found.append(word)
    threshold = patterns["tier2"]["cluster_threshold"]
    if len(found) >= threshold:
        hits.append({
            "line": 0,
            "severity": "P1",
            "pattern": f"Tier 2 cluster: {len(found)} words ({', '.join(found[:5])}{'...' if len(found) > 5 else ''})",
            "suggestion": f"Replace {len(found) - threshold + 1}+ with simpler alternatives",
        })
    return hits


def find_tier3_density(text, patterns):
    hits = []
    text_lower = text.lower()
    word_count = count_words(text)
    found = []
    for word in patterns["tier3"]["words"]:
        occurrences = len(re.findall(rf"\b{re.escape(word)}\b", text_lower))
        if occurrences > 0:
            found.append((word, occurrences))
    total = sum(c for _, c in found)
    threshold = patterns["tier3"]["density_threshold"]
    # Normalize to per-500-words
    if word_count > 0:
        density = total * 500 / word_count
    else:
        density = 0
    if density >= threshold:
        top = sorted(found, key=lambda x: -x[1])[:5]
        hits.append({
            "line": 0,
            "severity": "P2",
            "pattern": f"Tier 3 density: {density:.1f}/500w ({', '.join(f'{w}({c})' for w, c in top)})",
            "suggestion": "Reduce frequency of generic AI-favored words",
        })
    return hits


def find_banned_phrases(text, patterns):
    hits = []
    text_lower = text.lower()
    for category, phrases in patterns["banned_phrases"].items():
        severity = "P0" if category in ("throat_clearing", "chatbot_artifacts", "emphasis_crutches") else "P1"
        for phrase in phrases:
            if phrase.lower() in text_lower:
                for i, line in enumerate(text.split("\n"), 1):
                    if phrase.lower() in line.lower():
                        hits.append({
                            "line": i,
                            "severity": severity,
                            "pattern": f"Banned ({category}): '{phrase}'",
                            "suggestion": "Cut entirely or rewrite",
                        })
                        break
    return hits


def find_structural_patterns(text):
    hits = []
    lines = text.split("\n")

    # Em-dash density
    em_dashes = text.count("—") + text.count("--")
    paragraphs = len([l for l in lines if l.strip()])
    if paragraphs > 0 and em_dashes / max(paragraphs, 1) > 0.5:
        hits.append({
            "line": 0,
            "severity": "P0",
            "pattern": f"Em-dash overuse: {em_dashes} in {paragraphs} paragraphs",
            "suggestion": "Target zero or near-zero em-dashes",
        })

    # Bold overuse
    bold_count = len(re.findall(r"\*\*[^*]+\*\*", text))
    if bold_count > 5:
        hits.append({
            "line": 0,
            "severity": "P0",
            "pattern": f"Bold overuse: {bold_count} bold spans",
            "suggestion": "Use bold sparingly for emphasis",
        })

    # Binary contrast
    if re.search(r"[Ii]t'?s not (?:about |just )?\w+.{0,20}it'?s (?:about )?\w+", text):
        hits.append({
            "line": 0,
            "severity": "P1",
            "pattern": "Binary contrast: 'It's not X, it's Y'",
            "suggestion": "State what it IS about directly",
        })

    # Triple-negation reveal (tropes.fyi)
    if re.search(r"Not \w+\.\s*Not \w+\.\s*(Just|But|Only) \w+", text):
        hits.append({
            "line": 0,
            "severity": "P1",
            "pattern": "Triple-negation reveal: 'Not X. Not Y. Just Z.'",
            "suggestion": "State the point directly",
        })

    # Rhetorical self-answered questions (tropes.fyi)
    if re.search(r"The \w+\?\s+[A-Z]", text):
        hits.append({
            "line": 0,
            "severity": "P1",
            "pattern": "Self-posed rhetorical question: 'The X? A Y.'",
            "suggestion": "Make the statement directly",
        })

    # Uniform sentence length
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if len(sentences) >= 5:
        lengths = [len(s.split()) for s in sentences]
        avg = sum(lengths) / len(lengths)
        variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        if variance < 4:
            hits.append({
                "line": 0,
                "severity": "P1",
                "pattern": f"Uniform rhythm: sentence length variance={variance:.1f} (avg {avg:.0f} words)",
                "suggestion": "Mix short and long sentences",
            })

    # Excessive one-sentence paragraphs (tropes.fyi)
    single_paras = 0
    for line in lines:
        stripped = line.strip()
        if stripped and "\n" not in stripped and 5 < len(stripped.split()) < 15:
            single_paras += 1
    if paragraphs >= 4 and single_paras / max(paragraphs, 1) > 0.4:
        hits.append({
            "line": 0,
            "severity": "P1",
            "pattern": f"Punchy fragment overuse: {single_paras}/{paragraphs} paragraphs are single sentences",
            "suggestion": "Vary paragraph length; not every point needs its own line",
        })

    return hits


def detect(text, patterns, context="blog"):
    all_hits = []
    all_hits.extend(find_tier1(text, patterns))
    all_hits.extend(find_tier2_clusters(text, patterns))
    all_hits.extend(find_tier3_density(text, patterns))
    all_hits.extend(find_banned_phrases(text, patterns))
    all_hits.extend(find_structural_patterns(text))

    # Apply context tolerance
    profile = patterns.get("context_profiles", {}).get(context, {})
    if profile:
        filtered = []
        for hit in all_hits:
            # Tier 2 clusters
            if "Tier 2 cluster" in hit["pattern"] and profile.get("tier2_clusters") == "tolerate":
                continue
            # Em-dash
            if "Em-dash" in hit["pattern"] and profile.get("em_dash") == "tolerate":
                continue
            # Throat clearing
            if "throat_clearing" in hit["pattern"] and profile.get("throat_clearing") == "tolerate":
                continue
            # Structural template
            if any(p in hit["pattern"] for p in ("Binary contrast", "Triple-negation", "Uniform rhythm")):
                if profile.get("structural_template") == "tolerate":
                    continue
            filtered.append(hit)
        all_hits = filtered

    # Sort by severity then line
    severity_order = {"P0": 0, "P1": 1, "P2": 2}
    all_hits.sort(key=lambda h: (severity_order.get(h["severity"], 9), h["line"]))

    return all_hits


def format_report(hits, word_count):
    p0 = sum(1 for h in hits if h["severity"] == "P0")
    p1 = sum(1 for h in hits if h["severity"] == "P1")
    p2 = sum(1 for h in hits if h["severity"] == "P2")

    lines = [f"Detected {len(hits)} issues ({p0} P0, {p1} P1, {p2} P2) in {word_count} words", ""]
    if not hits:
        lines.append("No AI patterns detected.")
        return "\n".join(lines)

    lines.append("| Line | Severity | Pattern | Suggestion |")
    lines.append("|------|----------|---------|------------|")
    for h in hits:
        ln = str(h["line"]) if h["line"] > 0 else "-"
        lines.append(f"| {ln} | {h['severity']} | {h['pattern']} | {h['suggestion']} |")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Detect AI writing patterns")
    parser.add_argument("input", help="File path, text, or '-' for stdin")
    parser.add_argument("--context", default="blog", choices=["linkedin", "blog", "technical", "email", "docs", "casual"])
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    args = parser.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    elif Path(args.input).is_file():
        text = Path(args.input).read_text()
    else:
        text = args.input

    patterns = load_patterns()
    hits = detect(text, patterns, args.context)
    word_count = count_words(text)

    if args.json:
        print(json.dumps({"word_count": word_count, "hits": hits}, indent=2))
    else:
        print(format_report(hits, word_count))


if __name__ == "__main__":
    main()
