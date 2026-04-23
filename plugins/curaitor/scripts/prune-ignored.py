#!/usr/bin/env python3
"""Archive reviewed-and-confirmed-ignored notes from Curaitor/Ignored/ after cooldown.

The /cu:review-ignored skill sets `reviewed_ignored: YYYY-MM-DD` in the
frontmatter when the user confirms an ignored article was correctly classified.
After a cooldown (default 30 days), those notes can be archived out of the live
folder since their signal has been captured.

Usage:
    python3 scripts/prune-ignored.py [--days N] [--apply]

    --days N   cooldown in days (default 30)
    --apply    actually move files (default: dry-run)

Output: JSON summary to stdout.
"""

import argparse
import json
import os
import re
import sys
from datetime import date

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


# --- Frontmatter parsing ---

REVIEWED_RE = re.compile(r'^reviewed_ignored:\s*(\d{4}-\d{2}-\d{2})\s*$', re.MULTILINE)


def read_reviewed_ignored(filepath):
    """Return the reviewed_ignored date string from frontmatter, or None."""
    with open(filepath, encoding='utf-8') as fh:
        head = fh.read(1024)
    m = REVIEWED_RE.search(head)
    if not m:
        return None
    return m.group(1)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description='Archive reviewed-ignored notes past cooldown'
    )
    parser.add_argument('--days', type=int, default=30,
                        help='Cooldown in days (default 30)')
    parser.add_argument('--apply', action='store_true',
                        help='Actually move files (default: dry-run)')
    args = parser.parse_args()

    vault = find_vault()
    ignored_dir = os.path.join(vault, 'Curaitor', 'Ignored')
    today = date.today()

    candidates = 0
    would_move = 0
    moved = 0
    skipped_unreviewed = 0
    by_month = {}

    if os.path.isdir(ignored_dir):
        for fname in sorted(os.listdir(ignored_dir)):
            if not fname.endswith('.md') or fname.startswith('.'):
                continue
            candidates += 1
            src = os.path.join(ignored_dir, fname)
            reviewed = read_reviewed_ignored(src)
            if reviewed is None:
                skipped_unreviewed += 1
                continue

            try:
                reviewed_date = date.fromisoformat(reviewed)
            except ValueError:
                skipped_unreviewed += 1
                continue

            age = (today - reviewed_date).days
            if age < args.days:
                continue

            month_key = reviewed[:7]  # YYYY-MM
            archive_dir = os.path.join(vault, 'Curaitor', 'Archive', f'Ignored-{month_key}')
            dst = os.path.join(archive_dir, fname)
            would_move += 1
            by_month[month_key] = by_month.get(month_key, 0) + 1

            if args.apply:
                os.makedirs(archive_dir, exist_ok=True)
                os.rename(src, dst)
                moved += 1

    output = {
        'vault': vault,
        'candidates': candidates,
        'would_move': would_move,
        'moved': moved,
        'skipped_unreviewed': skipped_unreviewed,
        'by_month': by_month,
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


if __name__ == '__main__':
    main()
