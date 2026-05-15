#!/usr/bin/env python3
"""Headless /curaitor:discover orchestrator for cron.

Replaces `claude -p "/curaitor:discover"` so cron no longer depends on Claude auth.
The pipeline is fully deterministic + Gemma-driven:

  1. Fetch feeds (feeds.py)
  2. Dedup against vault + Recycle.md/archives (triage-write.py internals).
     Resurface-from-Recycle hits are fast-pathed — they already have a
     verdict; we append a single line back to Recycle.md and skip Gemma.
  3. Gemma pre-pass (local-triage.py) on remaining articles.
  4. Route per user's rules:
       - Gemma auto-skip (high-not-interested, or uncertain+skip)   → Ignored
       - feed_weight == 0.1  (demoted) AND _local uncertain         → Ignored
       - Gemma high-interested                                      → Inbox
       - Everything else                                            → Ignored
         with `triage_source: pending-claude-review` frontmatter AND
         enqueue to level-2 so an interactive Claude session re-evaluates
         and potentially promotes to Inbox/Review.
  5. Pre-generate structured summaries for Inbox landings.

Exits 0 on all expected error paths (same contract as the old
`claude -p` wrapper) so cron doesn't mark the run as failed. Writes a
machine-readable summary as the last line of stdout for observability.

Usage:
    CURAITOR_CRON=1 python3 scripts/discover-cron.py [--days N] [--dry-run]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# triage-write.py has a hyphen, so import via importlib.
_spec = importlib.util.spec_from_file_location('_triage_write', SCRIPT_DIR / 'triage-write.py')
if _spec is None or _spec.loader is None:
    print('ERROR: cannot locate triage-write.py', file=sys.stderr)
    sys.exit(1)
triage_write = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(triage_write)


def _import_script(filename: str, modname: str):
    path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot locate {filename}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


feeds = _import_script('feeds.py', '_feeds')
local_triage = _import_script('local-triage.py', '_local_triage')
level2_queue = _import_script('level2-queue.py', '_level2_queue')
openalex_impact = _import_script('openalex_impact.py', '_openalex_impact')


def _log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[{ts}] {msg}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 1 — fetch feeds. We call feeds.fetch_via_* directly instead of shelling
# out, so we get Python objects back without a JSON roundtrip.
# ---------------------------------------------------------------------------


def fetch_all_feeds(days: int) -> tuple[list[dict], int, list[dict]]:
    """Return (articles, feeds_checked, feed_errors).

    `articles` is the flat list of all articles across feeds, each stamped
    with `feed_name` + `feed_weight` (same shape feeds.py emits today).
    `feed_errors` is a list of {feed, error} for per-feed failures.
    """
    feeds_path = SCRIPT_DIR.parent / 'config' / 'feeds.yaml'
    if not feeds_path.is_file():
        _log(f'config/feeds.yaml missing at {feeds_path}; aborting')
        return [], 0, []

    import yaml
    with feeds_path.open() as f:
        config = yaml.safe_load(f) or {}
    feed_entries = config.get('feeds') or []

    articles: list[dict] = []
    feed_errors: list[dict] = []
    checked = 0

    for feed in feed_entries:
        checked += 1
        fetch_via = feed.get('fetch_via', 'rss')
        fetcher = feeds._FETCHERS.get(fetch_via)
        if fetcher is None:
            feed_errors.append({'feed': feed['name'], 'error': f'unknown fetch_via={fetch_via!r}'})
            continue
        try:
            fa, err = fetcher(feed, days=days)
        except Exception as e:  # noqa: BLE001 — per-feed isolation
            feed_errors.append({'feed': feed['name'], 'error': f'{type(e).__name__}: {e}'})
            continue
        if err:
            feed_errors.append({'feed': feed['name'], 'error': err})
            continue

        # Stamp with feed_name + feed_weight (mirrors feeds.py main()).
        feed_name = feed['name']
        feed_weight = feed.get('weight')
        category = feed.get('category', '')
        # Optional per-feed routing mode. 'high-prestige-gated' means: default
        # to Ignored unless the impact-check or inbox-keyword bypass fires.
        # See triage-rules.yaml:high_prestige_gated.
        triage_mode = feed.get('triage_mode')
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for a in fa:
            a['feed_name'] = feed_name
            if feed_weight is not None:
                a['feed_weight'] = feed_weight
            a['category'] = category
            a['source'] = 'rss'
            if triage_mode:
                a['triage_mode'] = triage_mode
            parsed = feeds.parse_date(a.get('date', ''))
            # Accept articles with unparseable or missing dates — we'd rather
            # evaluate a fresh-ish RSS item than drop it.
            if parsed is None:
                articles.append(a)
                continue
            normalized = parsed.replace(
                tzinfo=timezone.utc if parsed.tzinfo is None else parsed.tzinfo
            )
            if normalized >= cutoff:
                articles.append(a)

    return articles, checked, feed_errors


# ---------------------------------------------------------------------------
# Step 2 — dedup. Fast-path recycle resurfaces: append to Recycle.md and drop.
# ---------------------------------------------------------------------------


def dedup_and_recycle(
    vault: str,
    articles: list[dict],
) -> tuple[list[dict], dict[str, int]]:
    """Partition articles into (survivors, counts).

    Duplicates against vault notes are logged + appended to Recycle.md with
    tag `(duplicate)`. Duplicates against Recycle.md/archives (resurfaces)
    are NOT re-appended (avoids line accumulation) but tracked in counts.
    """
    recycled_urls = triage_write.build_recycle_index(vault)
    known_urls = triage_write.build_url_index(vault)

    recycle_path = Path(vault) / 'Curaitor' / 'Recycle.md'
    recycle_path.parent.mkdir(parents=True, exist_ok=True)

    survivors: list[dict] = []
    counts = {'new': 0, 'dup_note': 0, 'dup_recycle': 0, 'no_url': 0}

    for a in articles:
        url = (a.get('url') or '').strip()
        if not url or url in ('>-', '-'):
            counts['no_url'] += 1
            continue
        norm = triage_write.normalize_url(url)
        if norm in recycled_urls:
            # Already in Recycle — fast-path, don't even touch Gemma. No
            # re-append: the existing line stays authoritative.
            counts['dup_recycle'] += 1
            continue
        if norm in known_urls:
            # In a live vault folder. Recycle it.
            title = a.get('title') or url
            with recycle_path.open('a', encoding='utf-8') as rf:
                rf.write(f'- [{title}]({url}) (duplicate)\n')
            recycled_urls.add(norm)
            counts['dup_note'] += 1
            continue
        counts['new'] += 1
        survivors.append(a)

    return survivors, counts


# ---------------------------------------------------------------------------
# Step 3 — Gemma pre-pass via local-triage.py's functions. Avoid shelling
# out so we keep one Python process for the whole run.
# ---------------------------------------------------------------------------


def run_gemma_pass(articles: list[dict]) -> list[dict]:
    """Annotate each article with `_local` (may be an error payload)."""
    settings = local_triage.load_settings()
    cfg = local_triage.local_triage_config(settings)
    if not cfg['enabled']:
        _log('local_triage disabled in user-settings.yaml; routing all to pending-claude-review')
        return articles
    backend_cfg = local_triage.resolve_backend_config(cfg['raw'])
    for a in articles:
        a['_local'] = local_triage.triage_one(a, cfg, backend_cfg, local_triage.DEFAULT_SYSTEM)
    return articles


# ---------------------------------------------------------------------------
# Step 3.5 — high-prestige-gated impact-check helpers.
#
# Articles from feeds tagged `triage_mode: high-prestige-gated` (Nature, Science,
# NEJM, etc.) default to Ignored unless an impact bypass fires:
#   1. inbox_keyword_match — title or local-summary contains a substring from
#      triage-rules.yaml:inbox_title_keywords
#   2. in_news (citation impact) — OpenAlex FWCI for the article's DOI ≥ threshold
#   3. gemma_high_interest — Gemma already classified as high-interested + read-now
#      (we don't second-guess a confident Gemma signal)
# ---------------------------------------------------------------------------

import yaml as _yaml  # noqa: E402

_TRIAGE_RULES_PATH = SCRIPT_DIR.parent / 'config' / 'triage-rules.yaml'

# Cache for the keyword + config load so route() doesn't re-read every call.
_RULES_CACHE: dict | None = None


def _load_triage_rules() -> dict:
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    if not _TRIAGE_RULES_PATH.is_file():
        _RULES_CACHE = {}
        return _RULES_CACHE
    try:
        with _TRIAGE_RULES_PATH.open() as f:
            _RULES_CACHE = _yaml.safe_load(f) or {}
    except (OSError, _yaml.YAMLError) as e:
        _log(f'WARN: failed to load triage-rules.yaml: {e}')
        _RULES_CACHE = {}
    return _RULES_CACHE or {}


def _inbox_keyword_match(article: dict, keywords: list[str]) -> str | None:
    """Return the matched keyword (lowercased) or None.

    Checks article title + Gemma summary (if present) + RSS description against
    the inbox_title_keywords list. Match is case-insensitive substring.
    """
    if not keywords:
        return None
    haystack = ' '.join(filter(None, [
        article.get('title') or '',
        (article.get('_local') or {}).get('summary') or '',
        article.get('description') or '',
    ])).lower()
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower in haystack:
            return kw_lower
    return None


def _high_prestige_check(
    article: dict,
    keywords: list[str],
    fwci_threshold: float,
) -> tuple[bool, str | None, dict | None]:
    """Return (fired, signal_name, impact_payload).

    Order matters: keyword match is free (no API call), so check it first.
    Only fall through to OpenAlex if no keyword fires.
    """
    # 1. Keyword match — free, no API.
    matched_kw = _inbox_keyword_match(article, keywords)
    if matched_kw:
        return True, f'inbox_keyword:{matched_kw}', None

    # 2. OpenAlex FWCI — only run if we can extract a DOI from the URL.
    url = article.get('url') or ''
    doi = openalex_impact.extract_doi_from_url(url)
    if not doi:
        return False, None, None
    impact = openalex_impact.check_doi(doi, threshold=fwci_threshold)
    if impact.get('fired'):
        return True, 'in_news', impact
    return False, None, impact


# ---------------------------------------------------------------------------
# Step 4 — route. Produces two sets: (a) immediate writes, (b) pending-claude.
# ---------------------------------------------------------------------------


def route(articles: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (to_ignored_auto, to_inbox_auto, to_pending_claude).

    - to_ignored_auto: Gemma says high-not-interested OR uncertain+skip, OR
      feed_weight<=0.1 AND _local.verdict==uncertain. Also: high-prestige-gated
      articles whose impact-check + keyword-check both miss. Written with
      triage_source: local-model or high-prestige-default-ignored.
    - to_inbox_auto: Gemma says high-interested with verdict read-now/save-ref.
      Also: high-prestige-gated articles where keyword-match or OpenAlex
      impact-check fires. Written with triage_source: local-model-high-inbox
      or high-prestige-bypass-{signal}.
    - to_pending_claude: everything else. Written to Ignored with
      triage_source: pending-claude-review AND enqueued to level-2 so an
      interactive Claude can re-evaluate.
    """
    rules = _load_triage_rules()
    inbox_keywords = list(rules.get('inbox_title_keywords') or [])
    hp_block = rules.get('high_prestige_gated') or {}
    fwci_threshold = float(hp_block.get('in_news_threshold', 1.0))

    auto_ignored: list[dict] = []
    auto_inbox: list[dict] = []
    pending: list[dict] = []

    for a in articles:
        local = a.get('_local') or {}
        conf = local.get('confidence')
        verdict = local.get('verdict')
        weight = a.get('feed_weight')
        err = local.get('error')
        triage_mode = a.get('triage_mode')

        if err:
            # Gemma crashed on this article — default to pending-claude
            # (don't silently drop it).
            pending.append(a)
            continue

        # ── high-prestige-gated branch ───────────────────────────────────
        # Runs BEFORE the standard Gemma rules so a prestige feed can't
        # leak through on a Gemma "uncertain" verdict — we want the gate
        # to be the prior. Exception: a confidently-high-interested Gemma
        # call still wins, because that means the article matched our
        # topic prior on its own and we don't need the prestige bypass.
        if triage_mode == 'high-prestige-gated':
            if conf == 'high-interested' and verdict in ('read-now', 'save-reference'):
                # Gemma is confident this matches user interest. Trust it.
                a['_high_prestige_signal'] = 'gemma_high_interest'
                auto_inbox.append(a)
                continue
            fired, signal, impact = _high_prestige_check(
                a, inbox_keywords, fwci_threshold,
            )
            if fired:
                a['_high_prestige_signal'] = signal
                if impact:
                    a['_high_prestige_fwci'] = impact.get('fwci')
                    a['_high_prestige_cited_by_count'] = impact.get('cited_by_count')
                auto_inbox.append(a)
                continue
            # No bypass — force-route to Ignored regardless of Gemma's
            # uncertain-or-low-confidence call. The prestige-gate is the
            # default. Tag the signal as 'default' so the triage_source
            # downstream is recognizable.
            a['_high_prestige_signal'] = 'default-ignored'
            if impact:
                a['_high_prestige_fwci'] = impact.get('fwci')
            auto_ignored.append(a)
            continue

        # ── Standard (non-prestige-gated) routing ────────────────────────
        # Auto-skip rules (match local-triage.py decide_skip()).
        if conf == 'high-not-interested':
            auto_ignored.append(a)
            continue
        if verdict == 'skip' and conf == 'uncertain':
            auto_ignored.append(a)
            continue
        if weight is not None and float(weight) <= 0.1 and conf == 'uncertain':
            # Demoted feed + uncertain → straight to Ignored per curator policy.
            auto_ignored.append(a)
            continue
        if conf == 'high-interested' and verdict in ('read-now', 'save-reference'):
            auto_inbox.append(a)
            continue

        # Everything else (uncertain, high-interested-but-review, unknowns…)
        # → write Ignored with pending-claude-review flag + enqueue.
        pending.append(a)

    return auto_ignored, auto_inbox, pending


# ---------------------------------------------------------------------------
# Step 5 — write notes via triage-write.py's cmd_write, plus enqueue pending.
# ---------------------------------------------------------------------------


def _local_to_article_fields(a: dict, triage_source: str) -> dict:
    """Map _local.* into the fields triage-write.py expects."""
    local = a.get('_local') or {}
    fm = dict(a)
    # Prefer Gemma classifications but fall back to safe defaults.
    fm.setdefault('date_saved', date.today().isoformat())
    fm['category'] = local.get('category') or a.get('category') or 'general'
    fm['confidence'] = local.get('confidence') or 'uncertain'
    fm['verdict'] = local.get('verdict') or 'review'
    fm['tags'] = local.get('tags') or []
    summary = local.get('summary') or a.get('description') or ''
    fm['summary'] = summary
    fm['verdict_text'] = local.get('reason') or ''
    fm['slop_label'] = local.get('slop_label') or 'clean'
    fm['triage_source'] = triage_source
    if local.get('model'):
        fm['local_model'] = local['model']
    # High-prestige-gated articles override the generic triage_source with
    # the specific bypass signal (or "default-ignored") so we can audit
    # which gate decision the cron made for each article.
    hp_signal = a.get('_high_prestige_signal')
    if hp_signal:
        fm['triage_source'] = f'high-prestige-{hp_signal}'
        # Stamp the OpenAlex impact data when we have it.
        if a.get('_high_prestige_fwci') is not None:
            fm['fwci'] = a['_high_prestige_fwci']
        if a.get('_high_prestige_cited_by_count') is not None:
            fm['cited_by_count'] = a['_high_prestige_cited_by_count']
        # Force routing: bypass signals -> Inbox, default-ignored -> Ignored.
        if hp_signal == 'default-ignored':
            fm['confidence'] = 'high-not-interested'
        else:
            fm['confidence'] = 'high-interested'
            fm['verdict'] = local.get('verdict') if local.get('verdict') in ('read-now', 'save-reference') else 'save-reference'
    # Force the folder via confidence — except for pending-claude which
    # lands in Ignored regardless of _local.confidence.
    if triage_source == 'pending-claude-review':
        fm['confidence'] = 'high-not-interested'
    return fm


def write_batch(articles: list[dict], triage_source: str, *, generate_summaries: bool) -> dict:
    """Pipe articles through triage-write.py's cmd_write via subprocess."""
    if not articles:
        return {'written': 0, 'routing': {'inbox': 0, 'review': 0, 'ignored': 0}}

    payload = [_local_to_article_fields(a, triage_source) for a in articles]

    cmd = [sys.executable, str(SCRIPT_DIR / 'triage-write.py')]
    if generate_summaries:
        cmd.append('--generate-summaries')
    proc = subprocess.run(
        cmd,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _log(f'triage-write.py failed (rc={proc.returncode}): {proc.stderr[:400]}')
        return {'written': 0, 'error': proc.stderr[:400]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {'written': 0, 'error': 'unparseable stdout', 'raw': proc.stdout[:400]}


def enqueue_pending(articles: list[dict]) -> int:
    """Append pending-claude articles to the level-2 queue."""
    if not articles:
        return 0
    # level2-queue append reads from stdin; we call the python module.
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / 'level2-queue.py'), 'append',
         '--source', 'rss',
         '--enqueued-by', 'discover-cron',
         '--reason', 'pre-claude'],
        input=json.dumps(articles),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        _log(f'level2-queue append failed: {proc.stderr[:200]}')
        return 0
    try:
        out = json.loads(proc.stdout)
        return int(out.get('appended', len(articles)))
    except json.JSONDecodeError:
        return len(articles)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description='Headless /curaitor:discover for cron.')
    parser.add_argument('--days', type=int, default=7, help='Lookback window (default 7)')
    parser.add_argument('--dry-run', action='store_true', help='Do not write or enqueue anything; print plan')
    args = parser.parse_args()

    started = time.time()
    _log('discover-cron: starting')

    # Step 1 — fetch
    articles, feeds_checked, feed_errors = fetch_all_feeds(args.days)
    _log(f'fetched: {len(articles)} articles across {feeds_checked} feeds ({len(feed_errors)} errors)')

    # Step 2 — dedup (safe; read-only in dry-run because we skip write_batch below).
    # In dry-run we still populate Recycle.md for note-duplicates because
    # appending a single "(duplicate)" line is effectively idempotent — we
    # only want to avoid the *writes* to the vault's Inbox/Review/Ignored.
    vault = triage_write.find_vault()
    if args.dry_run:
        # Dry-run: compute dedup without mutating Recycle.md.
        recycled_urls = triage_write.build_recycle_index(vault)
        known_urls = triage_write.build_url_index(vault)
        survivors = []
        dedup_counts = {'new': 0, 'dup_note': 0, 'dup_recycle': 0, 'no_url': 0}
        for a in articles:
            url = (a.get('url') or '').strip()
            if not url:
                dedup_counts['no_url'] += 1
                continue
            norm = triage_write.normalize_url(url)
            if norm in recycled_urls:
                dedup_counts['dup_recycle'] += 1
            elif norm in known_urls:
                dedup_counts['dup_note'] += 1
            else:
                dedup_counts['new'] += 1
                survivors.append(a)
    else:
        survivors, dedup_counts = dedup_and_recycle(vault, articles)
    _log(
        f'dedup: {dedup_counts.get("new", len(survivors))} new, '
        f'{dedup_counts.get("dup_note", 0)} duplicates, '
        f'{dedup_counts.get("dup_recycle", 0)} resurfaced from Recycle'
    )

    # Step 3 — Gemma pre-pass (runs in dry-run too; it's read-only).
    survivors = run_gemma_pass(survivors)

    # Step 4 — route
    auto_ignored, auto_inbox, pending = route(survivors)
    _log(
        f'route: auto_ignored={len(auto_ignored)}, auto_inbox={len(auto_inbox)}, '
        f'pending_claude={len(pending)}'
    )

    if args.dry_run:
        print(json.dumps({
            'dry_run': True,
            'fetched': len(articles),
            'survivors': len(survivors),
            'auto_ignored': len(auto_ignored),
            'auto_inbox': len(auto_inbox),
            'pending_claude': len(pending),
            'feed_errors': feed_errors,
        }, indent=2))
        return 0

    # Step 5a — write auto-ignored (no summaries needed for Ignored)
    ign_res = write_batch(auto_ignored, 'local-model', generate_summaries=False)

    # Step 5b — write auto-inbox (pre-generate summaries)
    inbox_res = write_batch(auto_inbox, 'local-model-high-inbox', generate_summaries=True)

    # Step 5c — write pending to Ignored AND enqueue
    pending_res = write_batch(pending, 'pending-claude-review', generate_summaries=False)
    enqueued = enqueue_pending(pending)

    elapsed = round(time.time() - started, 1)
    summary = {
        'fetched': len(articles),
        'feeds_checked': feeds_checked,
        'feed_errors': feed_errors,
        'dedup': dedup_counts,
        'auto_ignored': ign_res.get('routing', {}).get('ignored', 0),
        'auto_inbox': inbox_res.get('routing', {}).get('inbox', 0),
        'pending_claude_written': pending_res.get('routing', {}).get('ignored', 0),
        'pending_claude_enqueued': enqueued,
        'elapsed_s': elapsed,
    }
    _log(f'done in {elapsed}s: ' + ', '.join(f'{k}={v}' for k, v in summary.items() if k != 'feed_errors'))
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    # Force CURAITOR_CRON=1 semantics regardless of whether cron actually set it.
    # This tells downstream scripts (summarize-inbox.py) we're in non-interactive
    # mode — they'll skip interactive-only behaviors.
    os.environ.setdefault('CURAITOR_CRON', '1')
    raise SystemExit(main())
