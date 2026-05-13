#!/usr/bin/env python3
"""OpenAlex citation-impact lookup for high-prestige-gated feeds.

Used by the impact-check branch in `discover-cron.py` to decide whether
an article from a `triage_mode: high-prestige-gated` feed (Nature, Science,
NEJM, etc.) should bypass its strong-prior-to-Ignore. If OpenAlex reports
FWCI (Field-Weighted Citation Impact) ≥ threshold for the article's DOI,
the article is "high-impact" and routes to Inbox instead of Ignored.

Why FWCI and not Crossref Event Data
-----------------------------------
The original Phase 1 plan (pod 01KRGZAXYA4SG9YY6KRH3R8P7T) called for
Crossref Event Data. That API is now administratively shut down — every
endpoint at api.eventdata.crossref.org returns 403, and Crossref's own
service docs URL redirects to a deprecated path. We replaced it with
OpenAlex FWCI as the closest free, unmetered, no-key alternative.

What FWCI captures
------------------
FWCI = (this paper's citations) / (mean citations of papers in same field
+ same publication year). FWCI > 1 means above-average impact for the
paper's age + field. FWCI handles the "young paper" problem inherently —
it compares against same-cohort papers, so a 2-week-old paper with one
citation can have a much higher FWCI than a 5-year-old paper with 100.

What it doesn't capture
-----------------------
News/blog/policy mentions. A paper that's all over Twitter but not yet
cited has FWCI 0. The original Crossref Event Data signal would have
caught that; FWCI alone won't. The inbox_keyword_match bypass + the
existing Instapaper-rescue path (PR #84) cover most user-relevant
late-bloomer cases.

Lag profile
-----------
Empirical: of the last 30 days of Nature papers, 49/50 have FWCI = 0
because they have zero citations yet. The 1 that fires is the rare
immediate-citation-flurry paper. Over 60-90 days, the non-zero rate
climbs as citations accumulate. v0 design accepts the cold-start
problem; the inbox_keyword_match bypass + Instapaper rescue compensate.

API
---
Endpoint: https://api.openalex.org/works/doi:<DOI>
- Free, unmetered, no key required.
- Polite-pool: include mailto in User-Agent.
- The same OpenAlex client used by feeds.py's openalex backend.

Cache
-----
DOI -> (fwci, cited_by_count, queried_at) at
.curaitor/openalex-impact-cache.json in the Obsidian vault. TTL 7 days.
FWCI updates roughly weekly on OpenAlex's side, so a tighter cache adds
no value.

CLI
---
    python3 scripts/openalex_impact.py check <DOI>             # JSON to stdout
    python3 scripts/openalex_impact.py check <DOI> --refresh   # bypass cache
    python3 scripts/openalex_impact.py cache                   # cache stats

Returns (from `check`):
    {"doi": "10.1038/...", "fwci": 0.0|float, "cited_by_count": int,
     "in_news": bool (alias for fired), "fired": bool, "from_cache": bool,
     "error": Optional[str]}
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from _ssl_util import build_ssl_context  # noqa: E402

_SSL_CONTEXT = build_ssl_context()

API_BASE = 'https://api.openalex.org/works'
POLITE_UA = 'curaitor/0.4 (mailto:johnpaul@didion.net)'

CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# v0 default threshold. FWCI ≥ 1.0 = above field-and-year average.
# Empirical: only ~2% of recent Nature papers exceed this in the first 30 days,
# but those that do are exactly the "everyone is talking about this" papers.
DEFAULT_THRESHOLD = 1.0


def _vault_path() -> Path:
    """Locate the Obsidian vault via triage-write.find_vault()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('_tw', SCRIPT_DIR / 'triage-write.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('cannot locate triage-write.py')
    tw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tw)
    return Path(tw.find_vault())


def cache_path(vault: Path | None = None) -> Path:
    """Cache file at <vault>/.curaitor/openalex-impact-cache.json."""
    v = vault if vault is not None else _vault_path()
    return v / '.curaitor' / 'openalex-impact-cache.json'


def _load_cache(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open() as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as fh:
        json.dump(cache, fh)
    os.replace(tmp, path)


def _normalize_doi(doi: str) -> str:
    """Strip URL prefix + lowercase. Stable cache key."""
    d = doi.strip()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'doi:'):
        if d.lower().startswith(prefix):
            d = d[len(prefix):]
    return d.lower()


# Regex patterns to lift a DOI out of a publisher's article URL.
# Only publishers where the DOI is directly visible in the URL path are
# covered here. For the rest (Cell, JAMA, Lancet, JCI, BMJ — they expose
# PII or article IDs in the URL but not the DOI), the impact-check will
# return no-DOI and the article defaults to Ignored unless the parallel
# inbox_keyword_match bypass fires.
import re  # noqa: E402

# Nature family: nature.com/articles/s41586-XXX-XXX-X -> 10.1038/s41586-XXX-XXX-X
# Covers Nature, Nature Medicine, Nature Aging, etc.
_DOI_NATURE = re.compile(r'nature\.com/articles/([\w.-]+?)(?:[?#]|$)')
# Science.org: doi/<flavor>/10.1126/science.<id> -> 10.1126/science.<id>
_DOI_SCIENCE = re.compile(r'science\.org/doi/(?:abs/|full/|pdf/)?(10\.1126/[\w.-]+?)(?:[?#]|$)')
# NEJM: nejm.org/doi/<flavor>/10.1056/NEJM... -> 10.1056/NEJM...
_DOI_NEJM = re.compile(r'nejm\.org/doi/(?:abs/|full/|pdf/)?(10\.1056/[\w.-]+?)(?:[?#]|$)')


def extract_doi_from_url(url: str) -> str | None:
    """Best-effort DOI extraction from a publisher article URL.

    Returns a normalized DOI string on hit, None on miss. Designed for the
    high-prestige-gated feed set; URLs from publishers that don't expose
    DOIs in the path (Cell PII, JAMA fullarticle IDs, etc.) return None.
    """
    if not url:
        return None
    m = _DOI_NATURE.search(url)
    if m:
        return f'10.1038/{m.group(1)}'.lower()
    m = _DOI_SCIENCE.search(url)
    if m:
        return m.group(1).lower()
    m = _DOI_NEJM.search(url)
    if m:
        return m.group(1).lower()
    return None


def _query_work(doi: str, timeout: int = 30) -> tuple[float, int, str | None]:
    """Hit OpenAlex /works/doi:<DOI>, return (fwci, cited_by_count, error).

    A missing DOI in OpenAlex (404) returns (0.0, 0, None) — not-yet-indexed
    papers shouldn't poison the cache as errors; they're a normal "lag" state.
    """
    url = f'{API_BASE}/doi:{urllib.parse.quote(doi, safe="/-._~")}'
    req = urllib.request.Request(url, headers={'User-Agent': POLITE_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return 0.0, 0, None  # not yet indexed = legitimate zero
        return 0.0, 0, f'HTTPError {e.code}'
    except Exception as e:  # noqa: BLE001
        return 0.0, 0, f'{type(e).__name__}: {e}'

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return 0.0, 0, f'invalid JSON: {e}'

    fwci = payload.get('fwci')
    if fwci is None:
        # FWCI null in OpenAlex = "we have the work but no FWCI computed yet."
        # Treat as 0 for routing purposes; threshold check still works.
        fwci = 0.0
    cited_by_count = int(payload.get('cited_by_count') or 0)
    return float(fwci), cited_by_count, None


def check_doi(
    doi: str,
    threshold: float = DEFAULT_THRESHOLD,
    *,
    refresh: bool = False,
    cache_path_override: Path | None = None,
) -> dict:
    """Look up a DOI's OpenAlex citation impact.

    Returns:
        {
          'doi': normalized DOI,
          'fwci': float,
          'cited_by_count': int,
          'in_news': bool (alias for fired; kept for callers using the original name),
          'fired': bool (fwci >= threshold),
          'from_cache': bool,
          'error': Optional[str],
        }

    Errors are non-fatal — a query failure returns fwci=0 with `error`
    populated so the caller can log but still route deterministically (a
    failed lookup defaults to "not high-impact").
    """
    norm = _normalize_doi(doi)
    if not norm:
        return {'doi': '', 'fwci': 0.0, 'cited_by_count': 0,
                'in_news': False, 'fired': False, 'from_cache': False,
                'error': 'empty DOI'}

    try:
        cp = cache_path_override if cache_path_override is not None else cache_path()
    except RuntimeError:
        # Vault not findable; degrade to no-cache mode.
        cp = None
        cache = {}
    else:
        cache = _load_cache(cp)

    now = int(time.time())
    if not refresh and norm in cache:
        entry = cache[norm]
        age = now - int(entry.get('queried_at') or 0)
        if age < CACHE_TTL_SECONDS:
            fwci = float(entry.get('fwci') or 0.0)
            cited = int(entry.get('cited_by_count') or 0)
            fired = fwci >= threshold
            return {
                'doi': norm,
                'fwci': fwci,
                'cited_by_count': cited,
                'in_news': fired,
                'fired': fired,
                'from_cache': True,
                'error': None,
            }

    fwci, cited, err = _query_work(norm)
    fired = fwci >= threshold

    if cp is not None:
        cache[norm] = {
            'fwci': fwci,
            'cited_by_count': cited,
            'queried_at': now,
            'queried_at_iso': datetime.now(timezone.utc).isoformat(),
            'error': err,
        }
        try:
            _save_cache(cp, cache)
        except OSError:
            pass

    return {
        'doi': norm,
        'fwci': fwci,
        'cited_by_count': cited,
        'in_news': fired,
        'fired': fired,
        'from_cache': False,
        'error': err,
    }


def cmd_check(args: argparse.Namespace) -> int:
    result = check_doi(args.doi, threshold=args.threshold, refresh=args.refresh)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0 if result.get('error') is None else 1


def cmd_cache_stats(args: argparse.Namespace) -> int:
    del args
    try:
        cp = cache_path()
    except RuntimeError as e:
        print(json.dumps({'error': str(e)}))
        return 1
    if not cp.is_file():
        json.dump({'cache_path': str(cp), 'entries': 0, 'fresh': 0, 'stale': 0,
                   'oldest_age_days': None}, sys.stdout, indent=2)
        sys.stdout.write('\n')
        return 0
    cache = _load_cache(cp)
    now = int(time.time())
    fresh = stale = 0
    fired = 0
    oldest = 0
    for entry in cache.values():
        age = now - int(entry.get('queried_at') or 0)
        if age < CACHE_TTL_SECONDS:
            fresh += 1
        else:
            stale += 1
        if age > oldest:
            oldest = age
        if float(entry.get('fwci') or 0) >= DEFAULT_THRESHOLD:
            fired += 1
    json.dump({
        'cache_path': str(cp),
        'entries': len(cache),
        'fresh': fresh,
        'stale': stale,
        'fired_count': fired,
        'oldest_age_days': round(oldest / 86400, 1) if cache else None,
    }, sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='OpenAlex impact-check for curaitor')
    sub = parser.add_subparsers(dest='command', required=True)

    p_check = sub.add_parser('check', help='Look up FWCI for a DOI')
    p_check.add_argument('doi')
    p_check.add_argument('--refresh', action='store_true',
                         help='Bypass cache, force a live query')
    p_check.add_argument('--threshold', type=float, default=DEFAULT_THRESHOLD,
                         help=f'FWCI threshold (default {DEFAULT_THRESHOLD})')

    sub.add_parser('cache', aliases=['cache-stats'],
                   help='Show cache freshness stats')

    args = parser.parse_args()
    if args.command == 'check':
        return cmd_check(args)
    if args.command in ('cache', 'cache-stats'):
        return cmd_cache_stats(args)
    parser.print_help()
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
