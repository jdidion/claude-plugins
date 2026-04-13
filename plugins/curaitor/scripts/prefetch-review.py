#!/usr/bin/env python3
"""Pre-fetch article data for /cu:review and /cu:review-ignored.

Reads Obsidian notes, parses frontmatter, detects repos, collects tags and topics.
Outputs JSON that the review agent can consume directly, saving LLM tokens on
mechanical work (note reading, parsing, repo detection).

Usage:
    python3 scripts/prefetch-review.py review [--limit N]
    python3 scripts/prefetch-review.py ignored [--days N]
    python3 scripts/prefetch-review.py inbox [--limit N]

Output: JSON array to stdout, one object per article.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

# Vault path — auto-detect from common locations
VAULT_PATHS = [
    os.path.expanduser("~/Obsidian"),
    os.path.expanduser("~/Documents/Obsidian"),
]

GITHUB_RE = re.compile(r'github\.com/([^/\s]+/[^/\s#?]+)', re.IGNORECASE)
GITLAB_RE = re.compile(r'gitlab\.com/([^/\s]+/[^/\s#?]+)', re.IGNORECASE)


def find_vault():
    """Find the Obsidian vault that contains curaitor folders."""
    candidates = []
    config_path = os.path.expanduser("~/Library/Application Support/obsidian/obsidian.json")
    if os.path.exists(config_path):
        import json as _json
        with open(config_path) as f:
            config = _json.load(f)
        for v in config.get('vaults', {}).values():
            p = v.get('path', '')
            if os.path.isdir(p):
                candidates.append(p)
    candidates.extend(p for p in VAULT_PATHS if os.path.isdir(p))

    curaitor_markers = ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']
    best, best_score = None, 0
    for p in candidates:
        score = sum(1 for m in curaitor_markers if os.path.isdir(os.path.join(p, m)))
        if score > best_score:
            best, best_score = p, score
    if best:
        return best
    if candidates:
        return candidates[0]
    print("Could not find Obsidian vault", file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(content):
    """Extract YAML frontmatter from markdown."""
    if not content.startswith('---'):
        return {}, content
    end = content.find('---', 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    fm = {}
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' not in line:
            continue
        key, val = line.split(':', 1)
        key = key.strip()
        val = val.strip()
        # Handle YAML arrays: [a, b, c]
        if val.startswith('[') and val.endswith(']'):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(',') if v.strip()]
        # Strip quotes
        elif val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        fm[key] = val
    return fm, body


def detect_repo(url, title='', body=''):
    """Detect GitHub/GitLab repo from URL, title, or body."""
    for text in [url, title, body[:500]]:
        m = GITHUB_RE.search(text)
        if m:
            repo = m.group(1).rstrip('/')
            # Strip .git suffix
            if repo.endswith('.git'):
                repo = repo[:-4]
            return {'host': 'github', 'repo': repo}
        m = GITLAB_RE.search(text)
        if m:
            repo = m.group(1).rstrip('/')
            return {'host': 'gitlab', 'repo': repo}
    return None


def extract_sections(body):
    """Extract Summary and Why review sections from note body."""
    sections = {}
    current = None
    lines = []
    for line in body.split('\n'):
        if line.startswith('## '):
            if current:
                sections[current] = '\n'.join(lines).strip()
            current = line[3:].strip().lower()
            lines = []
        elif current:
            lines.append(line)
    if current:
        sections[current] = '\n'.join(lines).strip()
    return sections


def read_folder(vault, folder, limit=None, days=None):
    """Read all .md notes from a vault folder."""
    path = os.path.join(vault, folder)
    if not os.path.isdir(path):
        # Try under Curaitor/ prefix
        path = os.path.join(vault, 'Curaitor', folder)
        if not os.path.isdir(path):
            return []

    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    articles = []
    for f in sorted(os.listdir(path)):
        if not f.endswith('.md') or f.startswith('.'):
            continue
        filepath = os.path.join(path, f)
        with open(filepath) as fh:
            content = fh.read()

        fm, body = parse_frontmatter(content)

        # Filter by date if needed
        if cutoff and fm.get('date_triaged', '9999') < cutoff:
            continue

        url = fm.get('url', '')
        title = fm.get('title', f.replace('.md', ''))
        repo = detect_repo(url, title, body)
        sections = extract_sections(body)

        article = {
            'filename': f,
            'path': os.path.relpath(filepath, vault),
            'title': title,
            'url': url,
            'source': fm.get('source', ''),
            'category': fm.get('category', ''),
            'date_triaged': fm.get('date_triaged', ''),
            'confidence': fm.get('confidence', ''),
            'verdict': fm.get('verdict', ''),
            'tags': fm.get('tags', []),
            'reviewed_ignored': fm.get('reviewed_ignored', ''),
            'review_decision': fm.get('review_decision', ''),
            'repo': repo,
            'summary': sections.get('summary', ''),
            'why_review': sections.get('why review?', sections.get('verdict', '')),
            'has_linkedin': 'linkedin.com' in url,
        }
        articles.append(article)

        if limit and len(articles) >= limit:
            break

    return articles


def list_topics(vault):
    """List existing topic notes."""
    topics_dir = os.path.join(vault, 'Topics')
    if not os.path.isdir(topics_dir):
        return []
    return [f.replace('.md', '') for f in os.listdir(topics_dir)
            if f.endswith('.md') and not f.startswith('.')]


def collect_vault_tags(vault):
    """Collect all unique tags from recent notes."""
    tags = set()
    for folder in ['Inbox', 'Review', 'Ignored', 'Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']:
        path = os.path.join(vault, folder)
        if not os.path.isdir(path):
            continue
        for f in os.listdir(path):
            if not f.endswith('.md'):
                continue
            with open(os.path.join(path, f)) as fh:
                content = fh.read()
            fm, _ = parse_frontmatter(content)
            article_tags = fm.get('tags', [])
            if isinstance(article_tags, list):
                tags.update(article_tags)
    return sorted(tags)


def main():
    parser = argparse.ArgumentParser(description='Pre-fetch review data from Obsidian vault')
    parser.add_argument('folder', choices=['review', 'ignored', 'inbox'],
                        help='Which folder to pre-fetch')
    parser.add_argument('--limit', type=int, help='Max articles to return')
    parser.add_argument('--days', type=int, default=30,
                        help='Lookback days for ignored (default 30)')
    parser.add_argument('--include-meta', action='store_true',
                        help='Include vault tags and topics in output')
    args = parser.parse_args()

    vault = find_vault()

    folder_map = {'review': 'Review', 'ignored': 'Ignored', 'inbox': 'Inbox'}
    folder = folder_map[args.folder]

    days = args.days if args.folder == 'ignored' else None
    articles = read_folder(vault, folder, limit=args.limit, days=days)

    output = {'articles': articles, 'count': len(articles)}

    if args.include_meta:
        output['topics'] = list_topics(vault)
        output['vault_tags'] = collect_vault_tags(vault)

    json.dump(output, sys.stdout, indent=2)
    print(f"\n{len(articles)} articles from {folder}/", file=sys.stderr)


if __name__ == '__main__':
    main()
