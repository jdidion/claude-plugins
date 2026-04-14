#!/usr/bin/env python3
"""Analyze writing samples to build a voice profile.

Extracts mechanical patterns from text files: sentence statistics,
vocabulary preferences, punctuation habits, structural tendencies.
The LLM adds higher-order observations on top.

Usage:
    python3 analyze-voice.py file1.md file2.md ...
    python3 analyze-voice.py --json file1.md   # machine-readable
"""

import argparse
import json
import math
import re
import string
import sys
from collections import Counter
from pathlib import Path


def split_sentences(text):
    """Split text into sentences, handling common abbreviations."""
    # Crude but effective for analysis purposes
    text = re.sub(r'([.!?])\s+', r'\1\n', text)
    return [s.strip() for s in text.split('\n') if s.strip() and len(s.strip().split()) >= 3]


def analyze_file(filepath):
    """Analyze a single writing sample."""
    text = Path(filepath).read_text(encoding='utf-8', errors='replace')

    # Strip markdown frontmatter
    if text.startswith('---'):
        end = text.find('---', 3)
        if end > 0:
            text = text[end + 3:]

    # Strip markdown formatting for analysis
    clean = re.sub(r'^#+\s+.*$', '', text, flags=re.MULTILINE)  # headers
    clean = re.sub(r'```[\s\S]*?```', '', clean)  # code blocks
    clean = re.sub(r'`[^`]+`', '', clean)  # inline code
    clean = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', clean)  # links
    clean = re.sub(r'[*_]{1,2}([^*_]+)[*_]{1,2}', r'\1', clean)  # bold/italic
    clean = re.sub(r'^\s*[-*]\s+', '', clean, flags=re.MULTILINE)  # list markers
    clean = re.sub(r'^\s*\d+\.\s+', '', clean, flags=re.MULTILINE)  # numbered lists

    sentences = split_sentences(clean)
    if not sentences:
        return None

    # Sentence length stats
    lengths = [len(s.split()) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
    std_dev = math.sqrt(variance)
    median_len = sorted(lengths)[len(lengths) // 2]

    # Paragraph analysis
    paragraphs = [p.strip() for p in clean.split('\n\n') if p.strip()]
    para_lengths = [len(p.split()) for p in paragraphs if len(p.split()) >= 3]
    avg_para = sum(para_lengths) / max(len(para_lengths), 1)

    # Punctuation habits
    punct = {
        'em_dashes': clean.count('—') + clean.count(' -- '),
        'semicolons': clean.count(';'),
        'colons': clean.count(':'),
        'exclamations': clean.count('!'),
        'questions': clean.count('?'),
        'parentheses': clean.count('('),
        'ellipses': clean.count('...') + clean.count('…'),
    }
    # Normalize per 1000 words
    word_count = len(clean.split())
    punct_per_1k = {k: round(v * 1000 / max(word_count, 1), 1) for k, v in punct.items()}

    # Contraction usage
    contractions = len(re.findall(r"\b\w+'\w+\b", clean))
    contraction_rate = round(contractions * 1000 / max(word_count, 1), 1)

    # First-person usage
    first_person = len(re.findall(r'\b[Ii]\b|\b[Mm]y\b|\b[Mm]e\b|\b[Ww]e\b|\b[Oo]ur\b', clean))
    first_person_rate = round(first_person * 1000 / max(word_count, 1), 1)

    # Sentence starters
    starters = []
    for s in sentences:
        words = s.split()
        if words:
            starters.append(words[0].lower().rstrip(','))
    starter_counts = Counter(starters).most_common(10)

    # Paragraph starters
    para_starters = []
    for p in paragraphs:
        words = p.split()
        if words:
            para_starters.append(words[0].lower().rstrip(','))
    para_starter_counts = Counter(para_starters).most_common(10)

    # Vocabulary diversity (type-token ratio)
    words_lower = [w.lower().strip(string.punctuation) for w in clean.split() if w.strip(string.punctuation)]
    ttr = len(set(words_lower)) / max(len(words_lower), 1)

    # Frequent words (excluding stopwords)
    stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                 'would', 'could', 'should', 'may', 'might', 'shall', 'can',
                 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                 'as', 'into', 'through', 'during', 'before', 'after', 'above',
                 'below', 'between', 'and', 'but', 'or', 'nor', 'not', 'so',
                 'yet', 'both', 'either', 'neither', 'each', 'every', 'all',
                 'any', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
                 'only', 'own', 'same', 'than', 'too', 'very', 'just', 'that',
                 'this', 'these', 'those', 'it', 'its', 'they', 'them', 'their',
                 'we', 'us', 'our', 'you', 'your', 'he', 'him', 'his', 'she',
                 'her', 'i', 'my', 'me', 'if', 'then', 'when', 'where', 'how',
                 'what', 'which', 'who', 'whom', 'about', 'up', 'out', 'also'}
    content_words = [w for w in words_lower if w not in stopwords and len(w) > 2]
    freq_words = Counter(content_words).most_common(20)

    # Question sentences
    question_pct = round(sum(1 for s in sentences if s.endswith('?')) / max(len(sentences), 1) * 100, 1)

    # List usage
    list_items = len(re.findall(r'^\s*[-*]\s+', text, re.MULTILINE))
    numbered_items = len(re.findall(r'^\s*\d+\.\s+', text, re.MULTILINE))

    return {
        'file': str(filepath),
        'word_count': word_count,
        'sentence_count': len(sentences),
        'paragraph_count': len(paragraphs),
        'sentence_length': {
            'mean': round(avg_len, 1),
            'median': median_len,
            'std_dev': round(std_dev, 1),
            'min': min(lengths),
            'max': max(lengths),
            'distribution': {
                'short_1_8': sum(1 for l in lengths if l <= 8),
                'medium_9_18': sum(1 for l in lengths if 9 <= l <= 18),
                'long_19_30': sum(1 for l in lengths if 19 <= l <= 30),
                'very_long_31plus': sum(1 for l in lengths if l > 30),
            }
        },
        'avg_paragraph_words': round(avg_para, 1),
        'punctuation_per_1k_words': punct_per_1k,
        'contraction_rate_per_1k': contraction_rate,
        'first_person_rate_per_1k': first_person_rate,
        'question_pct': question_pct,
        'list_items': list_items + numbered_items,
        'type_token_ratio': round(ttr, 3),
        'common_sentence_starters': starter_counts,
        'common_paragraph_starters': para_starter_counts,
        'frequent_content_words': freq_words,
    }


def merge_profiles(analyses):
    """Merge multiple file analyses into a single profile."""
    if not analyses:
        return {}

    total_words = sum(a['word_count'] for a in analyses)
    total_sentences = sum(a['sentence_count'] for a in analyses)

    # Weighted averages
    avg_sent_len = sum(a['sentence_length']['mean'] * a['sentence_count'] for a in analyses) / max(total_sentences, 1)
    avg_std_dev = sum(a['sentence_length']['std_dev'] * a['sentence_count'] for a in analyses) / max(total_sentences, 1)

    # Merge punctuation (weighted by word count)
    punct_keys = analyses[0]['punctuation_per_1k_words'].keys()
    merged_punct = {}
    for k in punct_keys:
        merged_punct[k] = round(sum(a['punctuation_per_1k_words'][k] * a['word_count'] for a in analyses) / max(total_words, 1), 1)

    # Merge contraction and first-person rates
    contraction = round(sum(a['contraction_rate_per_1k'] * a['word_count'] for a in analyses) / max(total_words, 1), 1)
    first_person = round(sum(a['first_person_rate_per_1k'] * a['word_count'] for a in analyses) / max(total_words, 1), 1)

    # Merge frequent words
    all_words = Counter()
    for a in analyses:
        for word, count in a['frequent_content_words']:
            all_words[word] += count

    return {
        'samples_analyzed': len(analyses),
        'total_words': total_words,
        'total_sentences': total_sentences,
        'sentence_length': {
            'mean': round(avg_sent_len, 1),
            'std_dev': round(avg_std_dev, 1),
            'range': f"{min(a['sentence_length']['min'] for a in analyses)}-{max(a['sentence_length']['max'] for a in analyses)}",
        },
        'punctuation_per_1k_words': merged_punct,
        'contraction_rate_per_1k': contraction,
        'first_person_rate_per_1k': first_person,
        'question_pct': round(sum(a['question_pct'] for a in analyses) / len(analyses), 1),
        'type_token_ratio': round(sum(a['type_token_ratio'] for a in analyses) / len(analyses), 3),
        'frequent_content_words': all_words.most_common(30),
        'per_file': analyses,
    }


def main():
    parser = argparse.ArgumentParser(description='Analyze writing samples for voice profiling')
    parser.add_argument('files', nargs='+', help='Writing sample files')
    parser.add_argument('--json', action='store_true', help='JSON output')
    args = parser.parse_args()

    analyses = []
    for f in args.files:
        path = Path(f)
        if not path.is_file():
            print(f"Warning: {f} not found, skipping", file=sys.stderr)
            continue
        result = analyze_file(path)
        if result:
            analyses.append(result)

    if not analyses:
        print("No valid samples to analyze", file=sys.stderr)
        sys.exit(1)

    merged = merge_profiles(analyses)

    if args.json:
        print(json.dumps(merged, indent=2))
    else:
        print(f"Analyzed {merged['samples_analyzed']} samples ({merged['total_words']} words, {merged['total_sentences']} sentences)")
        print()
        sl = merged['sentence_length']
        print(f"Sentence length:  mean={sl['mean']} words, std_dev={sl['std_dev']}, range={sl['range']}")
        print(f"Contractions:     {merged['contraction_rate_per_1k']}/1000 words")
        print(f"First person:     {merged['first_person_rate_per_1k']}/1000 words")
        print(f"Questions:        {merged['question_pct']}% of sentences")
        print(f"Vocab diversity:  TTR={merged['type_token_ratio']}")
        print()
        print("Punctuation (per 1k words):")
        for k, v in merged['punctuation_per_1k_words'].items():
            if v > 0:
                print(f"  {k}: {v}")
        print()
        print("Top content words:")
        for word, count in merged['frequent_content_words'][:15]:
            print(f"  {word}: {count}")


if __name__ == '__main__':
    main()
