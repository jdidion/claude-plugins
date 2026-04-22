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

# Matches Recycle.md lines: "- [title](url) ..." (url may be bare or surrounded by <>)
_RECYCLE_LINE = re.compile(r'^\s*-\s+\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)')


def _parse_recycle(recycle_path):
    """Return normalized URLs from a Curaitor/Recycle.md file."""
    urls = set()
    if not os.path.isfile(recycle_path):
        return urls
    try:
        with open(recycle_path, encoding='utf-8') as fh:
            for line in fh:
                m = _RECYCLE_LINE.match(line)
                if m:
                    urls.add(normalize_url(m.group(1)))
    except (OSError, UnicodeDecodeError):
        pass
    return urls


def build_url_index(vault):
    """Scan all triage folders + Recycle.md and build a set of normalized URLs.

    Articles that were previously recycled (duplicates, slop, no-source)
    should not re-triage — so Recycle.md is part of the known-URL set.
    """
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
                with open(filepath, encoding='utf-8') as fh:
                    # Only read first 500 chars — URL is in frontmatter
                    head = fh.read(500)
                m = re.search(r'^url:\s*(.+)$', head, re.MULTILINE)
                if m:
                    url = m.group(1).strip().strip('"').strip("'")
                    known.add(normalize_url(url))
            except (OSError, UnicodeDecodeError):
                continue

    known |= _parse_recycle(os.path.join(vault, 'Curaitor', 'Recycle.md'))
    return known


def build_recycle_index(vault):
    """Return only the recycled URLs, for distinguishing duplicate sources."""
    return _parse_recycle(os.path.join(vault, 'Curaitor', 'Recycle.md'))


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
    recycled_urls = build_recycle_index(vault)
    known_urls = build_url_index(vault)  # includes recycled + vault notes

    articles = json.load(sys.stdin)
    if not isinstance(articles, list):
        articles = [articles]

    written = 0
    recycled_dup_note = 0
    recycled_dup_recycle = 0
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
            # Duplicate — recycle, don't create a note.
            # Distinguish whether it matched a live vault note or was previously recycled.
            title = article.get('title', url)
            from_recycle = norm in recycled_urls
            tag = '(duplicate from Recycle)' if from_recycle else '(duplicate)'
            # Only write a new recycle line if this URL isn't already recorded.
            # Accumulating duplicate lines breaks `patch_note` disambiguation
            # later; one entry per normalized URL is enough.
            if not from_recycle:
                with open(recycle_path, 'a', encoding='utf-8') as rf:
                    rf.write(f"- [{title}]({url}) {tag}\n")
                recycled_urls.add(norm)  # prevent intra-batch re-appends
            if from_recycle:
                recycled_dup_recycle += 1
            else:
                recycled_dup_note += 1
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
        'recycled_duplicate': recycled_dup_note + recycled_dup_recycle,
        'recycled_duplicate_from_note': recycled_dup_note,
        'recycled_duplicate_from_recycle': recycled_dup_recycle,
        'skipped_no_url': skipped_nourl,
        'errors': errors,
        'total_input': len(articles),
        'routing': {k: len(v) for k, v in results.items()},
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


def cmd_dedup(args):
    """Check which URLs already exist in the vault or Recycle.md."""
    vault = find_vault()
    recycled_urls = build_recycle_index(vault)
    known_urls = build_url_index(vault)  # includes recycled

    # Collect input URLs
    if args.urls_file:
        with open(args.urls_file) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.urls:
        urls = args.urls
    else:
        urls = [line.strip() for line in sys.stdin if line.strip()]

    new_urls = []
    dup_note_urls = []
    dup_recycle_urls = []
    for url in urls:
        norm = normalize_url(url)
        if norm in recycled_urls:
            dup_recycle_urls.append(url)
        elif norm in known_urls:
            dup_note_urls.append(url)
        else:
            new_urls.append(url)

    output = {
        'total': len(urls),
        'new': len(new_urls),
        'duplicate': len(dup_note_urls) + len(dup_recycle_urls),
        'duplicate_from_note': len(dup_note_urls),
        'duplicate_from_recycle': len(dup_recycle_urls),
        'new_urls': new_urls,
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)
    print(
        f"{len(new_urls)} new, "
        f"{len(dup_note_urls)} duplicates (existing notes), "
        f"{len(dup_recycle_urls)} duplicates (from Recycle.md), "
        f"out of {len(urls)}",
        file=sys.stderr,
    )


def cmd_dedup_recycle(args):
    """Collapse duplicate lines in Curaitor/Recycle.md by normalized URL.

    Accumulating duplicate recycle lines breaks `patch_note` disambiguation
    (one URL with 5 entries can't be edited cleanly). Run this when the file
    gets messy. Idempotent and safe to re-run.
    """
    vault = find_vault()
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    if not os.path.isfile(recycle_path):
        print(f"No Recycle.md at {recycle_path}", file=sys.stderr)
        return

    with open(recycle_path, encoding='utf-8') as fh:
        original = fh.readlines()

    seen = set()
    kept = []
    dropped = 0
    non_entry_lines = 0
    for line in original:
        m = _RECYCLE_LINE.match(line)
        if not m:
            # Non-entry line (heading, blank, freeform note) — keep verbatim
            kept.append(line)
            non_entry_lines += 1
            continue
        norm = normalize_url(m.group(1))
        if norm in seen:
            dropped += 1
            continue
        seen.add(norm)
        kept.append(line)

    if args.dry_run:
        print(json.dumps({
            'vault': vault,
            'recycle_path': recycle_path,
            'total_lines': len(original),
            'entry_lines': len(original) - non_entry_lines,
            'unique_urls': len(seen),
            'would_drop': dropped,
        }, indent=2))
        return

    if dropped == 0:
        print(f"Recycle.md already dedup'd ({len(seen)} unique URLs)", file=sys.stderr)
        return

    # Write-replace with atomic-ish swap via a temp file
    tmp = recycle_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.writelines(kept)
    os.replace(tmp, recycle_path)

    print(json.dumps({
        'vault': vault,
        'recycle_path': recycle_path,
        'before_lines': len(original),
        'after_lines': len(kept),
        'dropped': dropped,
        'unique_urls': len(seen),
    }, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Write triage results to Obsidian')
    parser.add_argument('--dedup-only', action='store_true',
                        help='Only check for duplicates, do not write notes')
    parser.add_argument('--dedup-recycle', action='store_true',
                        help='Collapse duplicate lines in Curaitor/Recycle.md (one-time cleanup)')
    parser.add_argument('--dry-run', action='store_true',
                        help='With --dedup-recycle: report without modifying the file')
    parser.add_argument('--urls', nargs='+', help='URLs to check (dedup mode)')
    parser.add_argument('--urls-file', help='File with URLs (dedup mode)')
    args = parser.parse_args()

    if args.dedup_recycle:
        cmd_dedup_recycle(args)
    elif args.dedup_only:
        cmd_dedup(args)
    else:
        cmd_write(args)


if __name__ == '__main__':
    main()
