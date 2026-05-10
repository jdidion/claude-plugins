#!/usr/bin/env python3
"""Build or rebuild the Recycle.md TSV index.

Scans the Obsidian vault's live Recycle.md + most-recent N monthly archives
(Curaitor/Archive/Recycle-YYYY-MM.md) and writes a TSV at
`.curaitor/recycle-index.tsv` with one row per unique normalized URL:

    <url_normalized>\t<source_file>\t<title>

This is the fast-path dedup index that `has_recycled.py` reads. Each triage
run can cache the whole thing in memory (370 rows today, bounded growth) and
do O(1) lookups without parsing markdown at all.

Idempotent. Safe to re-run. The TSV is fully derived from the markdown — if
it drifts from the markdown (user hand-edits Recycle.md), just rerun this
script or let the checksum watchdog trigger it (future work).

Usage:
    python3 scripts/recycle-reindex.py                 # auto-discover vault
    python3 scripts/recycle-reindex.py --vault <path>  # explicit vault path
    python3 scripts/recycle-reindex.py --dry-run       # count only, no write

Exit codes:
    0 — success (or dry-run completed)
    1 — vault not found / invalid
    2 — IO error writing TSV
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Reuse triage-write.py's URL normalization + recycle-parsing helpers so this
# script can't drift out of sync with what the live dedup code does.
_spec = importlib.util.spec_from_file_location('_tw', SCRIPT_DIR / 'triage-write.py')
if _spec is None or _spec.loader is None:
    print('ERROR: cannot load triage-write.py from script dir', file=sys.stderr)
    sys.exit(1)
triage_write = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage_write)


# Matches the tagged-recycle-line format:
#   - [title](url) (duplicate)
#   - [title](url) (duplicate from Recycle)
#   - [title](url)
# First-group=title, second-group=url. Same regex as triage-write's
# _RECYCLE_LINE but we also want the title for the TSV.
import re  # noqa: E402
_RECYCLE_LINE_WITH_TITLE = re.compile(
    r'^\s*-\s+\[([^\]]*)\]\(\s*<?([^)\s>]+)>?\s*\)',
)


def parse_recycle_file(path: Path) -> list[tuple[str, str, str]]:
    """Return list of (normalized_url, source_file_rel, title) tuples."""
    rows: list[tuple[str, str, str]] = []
    if not path.is_file():
        return rows
    try:
        with path.open(encoding='utf-8') as fh:
            for line in fh:
                m = _RECYCLE_LINE_WITH_TITLE.match(line)
                if not m:
                    continue
                title = m.group(1).strip()
                url = m.group(2).strip()
                norm = triage_write.normalize_url(url)
                if norm:
                    rows.append((norm, path.name, title))
    except (OSError, UnicodeDecodeError) as e:
        print(f'WARN: cannot read {path}: {e}', file=sys.stderr)
    return rows


def collect_sources(vault: Path, archive_window: int) -> list[Path]:
    """Return live Recycle.md + most recent `archive_window` monthly archives."""
    sources = []
    live = vault / 'Curaitor' / 'Recycle.md'
    if live.is_file():
        sources.append(live)
    archive_dir = vault / 'Curaitor' / 'Archive'
    if archive_dir.is_dir():
        archives = sorted(
            (f for f in archive_dir.iterdir()
             if f.name.startswith('Recycle-') and f.name.endswith('.md')),
            reverse=True,
        )
        sources.extend(archives[:archive_window])
    return sources


def _content_checksum(sources: list[Path]) -> str:
    """SHA-256 over the concatenation of every source file, for drift detection."""
    h = hashlib.sha256()
    for p in sources:
        try:
            h.update(p.read_bytes())
        except OSError:
            # Don't silently include a missing file in the checksum.
            h.update(b'__MISSING__')
    return h.hexdigest()


def write_tsv(tsv_path: Path, rows: list[tuple[str, str, str]], checksum: str) -> None:
    """Atomic-ish TSV write. First line is a header with the source checksum."""
    tsv_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tsv_path.with_suffix(tsv_path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as fh:
        fh.write(f'# recycle-index v1 checksum={checksum}\n')
        fh.write('url_normalized\tsource_file\ttitle\n')
        for norm, src, title in rows:
            # Escape tabs/newlines in title just in case someone puts one there.
            safe_title = title.replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
            fh.write(f'{norm}\t{src}\t{safe_title}\n')
    os.replace(tmp, tsv_path)


def main() -> int:
    parser = argparse.ArgumentParser(description='Build or rebuild recycle-index.tsv')
    parser.add_argument('--vault', help='Override auto-discovered vault path')
    parser.add_argument('--archive-window', type=int, default=3,
                        help='Number of monthly archives to include (default 3)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Count rows, print summary, do not write TSV')
    parser.add_argument('--json', action='store_true',
                        help='Emit a machine-readable summary on stdout')
    args = parser.parse_args()

    vault_str = args.vault or triage_write.find_vault()
    vault = Path(vault_str)
    if not vault.is_dir():
        print(f'ERROR: vault not found at {vault}', file=sys.stderr)
        return 1

    sources = collect_sources(vault, args.archive_window)
    if not sources:
        print(f'WARN: no Recycle.md or archives in {vault}/Curaitor/', file=sys.stderr)
        # Still write an empty index — dedup callers expect a file to exist.

    # Dedup on normalized URL across all sources, preferring the earliest (live
    # file first, then most-recent archive, then older). This matches the live
    # dedup's intent — if the same URL is in Recycle.md AND Recycle-2026-04.md
    # we only keep one row in the index. Exactly which one wins is irrelevant
    # for membership testing; we keep the first seen for stable output order.
    seen = set()
    rows: list[tuple[str, str, str]] = []
    per_file: dict[str, int] = {}
    duplicates_across_files = 0
    for p in sources:
        before = len(rows)
        for norm, src, title in parse_recycle_file(p):
            if norm in seen:
                duplicates_across_files += 1
                continue
            seen.add(norm)
            rows.append((norm, src, title))
        per_file[p.name] = len(rows) - before

    checksum = _content_checksum(sources)
    tsv_path = vault / '.curaitor' / 'recycle-index.tsv'

    summary = {
        'vault': str(vault),
        'tsv_path': str(tsv_path),
        'sources_scanned': [p.name for p in sources],
        'unique_urls': len(rows),
        'per_file_new': per_file,
        'duplicates_across_files': duplicates_across_files,
        'checksum': checksum,
        'dry_run': args.dry_run,
    }

    if not args.dry_run:
        try:
            write_tsv(tsv_path, rows, checksum)
        except OSError as e:
            print(f'ERROR: cannot write TSV: {e}', file=sys.stderr)
            return 2

    if args.json:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write('\n')
    else:
        print(f'Vault:            {vault}')
        print(f'TSV:              {tsv_path}')
        print(f'Sources:          {", ".join(s.name for s in sources) or "(none)"}')
        print(f'Unique URLs:      {len(rows)}')
        print(f'Cross-file dupes: {duplicates_across_files}')
        print(f'Checksum:         {checksum[:16]}...')
        if args.dry_run:
            print('(dry-run — no TSV written)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
