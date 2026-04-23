#!/usr/bin/env python3
"""Rotate Curaitor/Recycle.md into monthly archives when it grows too large.

When Recycle.md exceeds the configured line threshold (default 1000, tunable
via user-settings.yaml `recycle_rollover_threshold`), the file is moved to
`Curaitor/Archive/Recycle-YYYY-MM.md` using today's year-month, and a fresh
empty Recycle.md is created.

Dedup callers (triage-write.py) should also scan the most-recent 3 archives
alongside the live file to keep ~90 days of recycled URLs in the dedup set.

Usage:
    python3 scripts/recycle-rollover.py              # dry-run
    python3 scripts/recycle-rollover.py --apply      # actually rotate
    python3 scripts/recycle-rollover.py --threshold N --apply

Exit 0 on success (including no-op). Exit 1 on vault-not-found or OS errors.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date

import yaml


# --- Vault discovery (mirrors triage-write.py) ---

VAULT_PATHS = [
    os.path.expanduser("~/Obsidian"),
    os.path.expanduser("~/Documents/Obsidian"),
]


def find_vault():
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

    markers = ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']
    best, best_score = None, 0
    for p in candidates:
        score = sum(1 for m in markers if os.path.isdir(os.path.join(p, m)))
        if score > best_score:
            best, best_score = p, score
    if best:
        return best
    if candidates:
        return candidates[0]
    print("Could not find Obsidian vault", file=sys.stderr)
    sys.exit(1)


# --- Config ---

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'user-settings.yaml'
)


def _load_int_setting(key, default):
    if os.path.isfile(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH) as f:
                data = yaml.safe_load(f) or {}
            return int(data.get(key, default))
        except (OSError, yaml.YAMLError, ValueError):
            pass
    return default


def load_threshold(default=1000):
    """Lines in Curaitor/Recycle.md that trigger auto-rotation."""
    return _load_int_setting('recycle_rollover_threshold', default)


def load_archive_window(default=3):
    """How many recent monthly Recycle archives to include in the dedup scan."""
    return _load_int_setting('recycle_archive_window', default)


# --- Rotation ---

_RECYCLE_LINE = re.compile(r'^\s*-\s+\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)')


def count_entries(path):
    """Count entry lines (those matching the recycle link pattern)."""
    if not os.path.isfile(path):
        return 0
    n = 0
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if _RECYCLE_LINE.match(line):
                n += 1
    return n


def needs_rotation(recycle_path, threshold):
    return count_entries(recycle_path) >= threshold


def rotate(vault, threshold, apply=False):
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    archive_dir = os.path.join(vault, 'Curaitor', 'Archive')
    stamp = date.today().strftime('%Y-%m')
    archive_path = os.path.join(archive_dir, f'Recycle-{stamp}.md')

    entries = count_entries(recycle_path)

    result = {
        'vault': vault,
        'recycle_path': recycle_path,
        'archive_path': archive_path,
        'threshold': threshold,
        'entries': entries,
        'rotated': False,
        'reason': None,
    }

    if not os.path.isfile(recycle_path):
        result['reason'] = 'no-recycle-file'
        return result

    if entries < threshold:
        result['reason'] = 'below-threshold'
        return result

    # If the archive for this month already exists, append rather than overwrite.
    # That way repeated rotations in the same month don't lose data.
    if apply:
        os.makedirs(archive_dir, exist_ok=True)
        if os.path.isfile(archive_path):
            # Append current file to the existing archive
            with open(archive_path, 'a', encoding='utf-8') as dst, \
                 open(recycle_path, encoding='utf-8') as src:
                dst.write('\n')
                shutil.copyfileobj(src, dst)
            os.remove(recycle_path)
        else:
            shutil.move(recycle_path, archive_path)
        # Leave Recycle.md absent — triage-write.py re-creates it on first write.
        result['rotated'] = True
        result['reason'] = 'rotated'
    else:
        result['reason'] = 'would-rotate'

    return result


def main():
    parser = argparse.ArgumentParser(description='Rotate Curaitor/Recycle.md into monthly archives')
    parser.add_argument('--apply', action='store_true',
                        help='Actually perform the rotation (default: dry-run)')
    parser.add_argument('--threshold', type=int,
                        help='Line-count trigger (default: from user-settings.yaml or 1000)')
    args = parser.parse_args()

    vault = find_vault()
    threshold = args.threshold if args.threshold is not None else load_threshold()
    result = rotate(vault, threshold, apply=args.apply)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == '__main__':
    main()
