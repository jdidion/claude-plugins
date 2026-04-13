#!/usr/bin/env python3
"""Write triage results to Obsidian from minimal LLM JSON output.

The LLM only needs to produce evaluation results (summary, category, verdict, tags).
This script handles: deduplication, folder routing, frontmatter templating, filename
sanitization, and writing — saving tokens on boilerplate generation.

Usage:
    # Pipe LLM evaluation JSON:
    echo '[{...}]' | python3 scripts/triage-write.py

    # Or from file:
    python3 scripts/triage-write.py < /tmp/evaluations.json

    # Dedup-only mode (check which URLs already exist):
    python3 scripts/triage-write.py --dedup-only --urls url1 url2 ...
    python3 scripts/triage-write.py --dedup-only --urls-file /tmp/urls.txt

Input JSON: array of objects, each with:
  - title (str, required)
  - url (str, required)
  - summary (str, required) — 2-3 sentences
  - category (str) — ai-tooling|genomics|methods|general
  - confidence (str) — high-interested|uncertain|high-not-interested
  - verdict (str) — read-now|save-reference|review|skip|obsolete
  - tags (list[str]) — semantic tags
  - verdict_text (str) — one-line verdict explanation
  - takeaways (list[str]) — key bullet points (optional)
  - source (str) — instapaper|rss|chrome-reading|etc.
  - bookmark_id (int) — Instapaper bookmark ID (optional)
  - feed_name (str) — RSS feed name (optional)
  - date_saved (str) — YYYY-MM-DD (optional, defaults to today)

Output: JSON summary to stdout.
"""

import json
import os
import re
import sys
from datetime import date

import yaml

# --- Vault discovery ---

VAULT_PATHS = [
    os.path.expanduser("~/Obsidian"),
    os.path.expanduser("~/Documents/Obsidian"),
]


def find_vault():
    """Find the Obsidian vault that contains curaitor folders."""
    candidates = []
    config_path = os.path.expanduser("~/Library/Application Support/obsidian/obsidian.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        for v in config.get('vaults', {}).values():
            p = v.get('path', '')
            if os.path.isdir(p):
                candidates.append(p)
    candidates.extend(p for p in VAULT_PATHS if os.path.isdir(p))

    # Prefer the vault with the most curaitor folders
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


# --- URL normalization (shared with feedly.py) ---

def normalize_url(url):
    url = url.strip().rstrip('/').lower()
    url = url.split('?')[0]
    if url.startswith('https://'):
        url = url[8:]
    elif url.startswith('http://'):
        url = url[7:]
    if url.startswith('www.'):
        url = url[4:]
    return url


# --- Deduplication ---

def build_url_index(vault):
    """Scan all triage folders and build a set of normalized URLs."""
    known = set()
    folders = [
        'Inbox', 'Review', 'Ignored', 'Library',
        'Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored',
    ]
    for folder in folders:
        path = os.path.join(vault, folder)
        if not os.path.isdir(path):
            continue
        for f in os.listdir(path):
            if not f.endswith('.md') or f.startswith('.'):
                continue
            filepath = os.path.join(path, f)
            try:
                with open(filepath) as fh:
                    # Only read first 500 chars — URL is in frontmatter
                    head = fh.read(500)
                m = re.search(r'^url:\s*(.+)$', head, re.MULTILINE)
                if m:
                    url = m.group(1).strip().strip('"').strip("'")
                    known.add(normalize_url(url))
            except (OSError, UnicodeDecodeError):
                continue
    return known


# --- Filename sanitization ---

def sanitize_filename(title, max_len=80):
    """Create a safe filename from an article title."""
    # Remove/replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', '', title)
    name = re.sub(r'[\n\r\t]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Truncate
    if len(name) > max_len:
        name = name[:max_len].rsplit(' ', 1)[0]
    return name


# --- Note construction ---

CONFIDENCE_TO_FOLDER = {
    'high-interested': 'Curaitor/Inbox',
    'uncertain': 'Curaitor/Review',
    'high-not-interested': 'Curaitor/Ignored',
}

VERDICT_LABELS = {
    'read-now': 'Read Now',
    'save-reference': 'Save Reference',
    'review': 'Review',
    'skip': 'Skip',
    'obsolete': 'Obsolete',
}


def build_note(article):
    """Construct frontmatter and markdown body from evaluation data."""
    today = date.today().isoformat()

    # Frontmatter
    fm = {
        'title': article['title'],
        'url': article['url'],
        'source': article.get('source', 'unknown'),
        'date_triaged': today,
        'category': article.get('category', 'general'),
        'confidence': article.get('confidence', 'uncertain'),
        'verdict': article.get('verdict', 'review'),
        'tags': article.get('tags', []),
    }
    if article.get('bookmark_id'):
        fm['bookmark_id'] = article['bookmark_id']
    if article.get('feed_name'):
        fm['feed_name'] = article['feed_name']
    if article.get('date_saved'):
        fm['date_saved'] = article['date_saved']
    if article.get('autonomy_level') is not None:
        fm['autonomy_level'] = article['autonomy_level']
    if article.get('media_type'):
        fm['media_type'] = article['media_type']

    # Body
    parts = []
    summary = article.get('summary', '')
    if summary:
        parts.append(f"## Summary\n{summary}")

    verdict_text = article.get('verdict_text', '')
    verdict_label = VERDICT_LABELS.get(article.get('verdict', ''), article.get('verdict', 'Review'))
    if verdict_text:
        parts.append(f"## Verdict: {verdict_label}\n{verdict_text}")

    takeaways = article.get('takeaways', [])
    if takeaways:
        bullets = '\n'.join(f'- {t}' for t in takeaways)
        parts.append(f"## Key takeaways\n{bullets}")

    body = '\n\n'.join(parts)
    return fm, body


def write_note(vault, folder, filename, frontmatter, body):
    """Write note to vault."""
    path = os.path.join(vault, folder, f"{filename}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    parts = ['---']
    parts.append(yaml.dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True).strip())
    parts.append('---')
    parts.append('')
    parts.append(body)

    with open(path, 'w') as f:
        f.write('\n'.join(parts))
    return os.path.relpath(path, vault)


# --- Main ---

def cmd_write(args):
    """Write triage results to Obsidian."""
    vault = find_vault()
    known_urls = build_url_index(vault)

    articles = json.load(sys.stdin)
    if not isinstance(articles, list):
        articles = [articles]

    written = 0
    recycled_dup = 0
    skipped_nourl = 0
    errors = 0
    results = {'inbox': [], 'review': [], 'ignored': []}

    # Recycle file for duplicates
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    os.makedirs(os.path.dirname(recycle_path), exist_ok=True)

    for article in articles:
        url = article.get('url', '').strip()
        if not url or url in ('>-', '-'):
            skipped_nourl += 1
            continue

        norm = normalize_url(url)
        if norm in known_urls:
            # Duplicate — recycle immediately, don't create a note
            title = article.get('title', url)
            with open(recycle_path, 'a') as rf:
                rf.write(f"- [{title}]({url}) (duplicate)\n")
            recycled_dup += 1
            continue

        try:
            fm, body = build_note(article)
            confidence = article.get('confidence', 'uncertain')
            folder = CONFIDENCE_TO_FOLDER.get(confidence, 'Curaitor/Review')
            filename = sanitize_filename(article['title'])
            rel_path = write_note(vault, folder, filename, fm, body)
            known_urls.add(norm)  # prevent self-duplicates within batch
            written += 1

            bucket = folder.split('/')[-1].lower()
            results[bucket].append(article['title'])
        except Exception as e:
            print(f"Error writing {article.get('title', '?')}: {e}", file=sys.stderr)
            errors += 1

    output = {
        'vault': vault,
        'written': written,
        'recycled_duplicate': recycled_dup,
        'skipped_no_url': skipped_nourl,
        'errors': errors,
        'total_input': len(articles),
        'routing': {k: len(v) for k, v in results.items()},
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


def cmd_dedup(args):
    """Check which URLs already exist in the vault."""
    vault = find_vault()
    known_urls = build_url_index(vault)

    # Collect input URLs
    if args.urls_file:
        with open(args.urls_file) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.urls:
        urls = args.urls
    else:
        urls = [line.strip() for line in sys.stdin if line.strip()]

    new_urls = []
    dup_urls = []
    for url in urls:
        norm = normalize_url(url)
        if norm in known_urls:
            dup_urls.append(url)
        else:
            new_urls.append(url)

    output = {
        'total': len(urls),
        'new': len(new_urls),
        'duplicate': len(dup_urls),
        'new_urls': new_urls,
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)
    print(f"{len(new_urls)} new, {len(dup_urls)} duplicates out of {len(urls)}", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Write triage results to Obsidian')
    parser.add_argument('--dedup-only', action='store_true',
                        help='Only check for duplicates, do not write notes')
    parser.add_argument('--urls', nargs='+', help='URLs to check (dedup mode)')
    parser.add_argument('--urls-file', help='File with URLs (dedup mode)')
    args = parser.parse_args()

    if args.dedup_only:
        cmd_dedup(args)
    else:
        cmd_write(args)


if __name__ == '__main__':
    main()
