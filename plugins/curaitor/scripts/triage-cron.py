#!/usr/bin/env python3
"""Headless /curaitor:triage orchestrator for cron.

Replaces `claude -p "/curaitor:triage"` so scheduled triage runs don't depend on
Claude auth. Mirrors the discover-cron.py architecture; key differences:

  - Source is Instapaper (not RSS), fetched via scripts/instapaper.py.
  - Gemma's classification uses the article's FULL EXTRACTED TEXT from
    Instapaper's /bookmarks/get_text endpoint, not the bookmark title +
    short description. Richer signal than discover.
  - Some triage actions can't be done headlessly (obsolescence check on
    ai-tooling, LinkedIn link-mining + comment inspection, video/podcast
    transcript handling). Articles that trigger those actions route to
    Ignored with `triage_source: pending-claude-review` frontmatter AND
    enqueue to level-2 so interactive Claude finishes the work on drain.
  - After writing a note, the bookmark is archived in Instapaper (same
    success contract Claude followed).

Usage:
    CURAITOR_CRON=1 python3 scripts/triage-cron.py [--dry-run]
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
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))


def _import_hyphenated(filename: str, modname: str):
    path = SCRIPT_DIR / filename
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot locate {filename}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


triage_write = _import_hyphenated('triage-write.py', '_triage_write')
local_triage = _import_hyphenated('local-triage.py', '_local_triage')


def _log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[{ts}] {msg}', file=sys.stderr)


# ---------------------------------------------------------------------------
# Step 1 — fetch unread Instapaper bookmarks via the existing client.
# ---------------------------------------------------------------------------


def fetch_bookmarks() -> list[dict]:
    """Shell out to scripts/instapaper.py list — it already has the OAuth path."""
    proc = subprocess.run(
        ['python3', str(SCRIPT_DIR / 'instapaper.py'), 'list', '--limit', '500'],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        _log(f'instapaper list failed (rc={proc.returncode}): {proc.stderr[:400]}')
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        _log(f'instapaper list: unparseable output ({len(proc.stdout)} bytes)')
        return []


# ---------------------------------------------------------------------------
# Pre-Gemma hard-route: LinkedIn / video / podcast URLs bypass Gemma and
# route straight to pending-claude-review, because Gemma only sees the
# Instapaper-extracted text which:
#   - For LinkedIn posts, contains the post body but NOT the outbound links
#     in the post or in comments (links frequently hide in comments).
#   - For YouTube/Vimeo, contains the player page text, which is useless —
#     a human (or Claude with transcript access) needs the actual transcript.
#   - For podcasts, contains show-notes HTML but variable quality.
# ---------------------------------------------------------------------------

_LINKEDIN_HOSTS = frozenset({'linkedin.com', 'lnkd.in'})
_VIDEO_HOSTS = frozenset({
    'youtube.com', 'youtu.be', 'vimeo.com', 'loom.com',
    'tiktok.com', 'twitch.tv',
})
_PODCAST_HINTS = (
    'overcast.fm', 'castro.fm', 'pca.st', 'spotify.com/episode',
    'spotify.com/show', 'podcasts.apple.com', 'podbean.com',
    'simplecast.com', 'buzzsprout.com', 'transistor.fm',
    'acast.com', 'substack.com/podcast', 'megaphone.fm',
)


def hard_route_reason(url: str) -> str | None:
    """Return a short reason string if the URL should skip Gemma entirely."""
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    if host.startswith('www.'):
        host = host[4:]
    if host in _LINKEDIN_HOSTS:
        return 'linkedin'
    if host in _VIDEO_HOSTS:
        return 'video'
    for hint in _PODCAST_HINTS:
        if hint in url.lower():
            return 'podcast'
    return None


# ---------------------------------------------------------------------------
# Step 2 — dedup (reuses triage-write internals).
# ---------------------------------------------------------------------------


def dedup_and_recycle(
    vault: str, bookmarks: list[dict],
) -> tuple[list[dict], list[int], dict[str, int]]:
    """Return (survivors, archive_ids, counts).

    Source-aware routing for Instapaper bookmarks:
      - URL in Recycle.md (no live note): drop + archive the bookmark.
        Recycle is authoritative. Print stderr warning so the drop is visible.
      - URL in Curaitor/Ignored/: PASS THROUGH as survivor with marker so
        triage-write.py's rescue path moves it to Inbox (Instapaper save is
        a fresh user signal; the old Ignored decision was pre-save).
      - URL in Curaitor/Inbox/ or Curaitor/Review/: skip + archive. The article
        is already in a live queue the user is tracking. No Recycle line.
      - URL in a terminal folder (Library, Topics) or elsewhere live: append
        one Recycle line + archive. Legacy "already filed" behavior.
      - No match: survivor (normal Gemma / pending-claude flow).

    `archive_ids` includes every bookmark we've decided not to write a fresh
    note for (including the rescue path — triage-write.py moves the note; the
    bookmark is still consumed).
    """
    recycled_urls = triage_write.build_recycle_index(vault)
    url_to_note = triage_write.build_url_to_note_index(vault)

    recycle_path = Path(vault) / 'Curaitor' / 'Recycle.md'
    recycle_path.parent.mkdir(parents=True, exist_ok=True)

    survivors: list[dict] = []
    archive_ids: list[int] = []
    counts = {
        'new': 0, 'dup_note': 0, 'dup_recycle': 0,
        'rescued_from_ignored': 0, 'skipped_in_inbox_or_review': 0,
        'no_url': 0,
    }

    for b in bookmarks:
        url = (b.get('url') or '').strip()
        if not url:
            counts['no_url'] += 1
            continue
        norm = triage_write.normalize_url(url)
        bid = b.get('bookmark_id')
        existing_note = url_to_note.get(norm)  # (folder_rel, filename) or None

        if norm in recycled_urls and not existing_note:
            # Instapaper save hit a Recycle entry with no live note. Recycle is
            # authoritative; drop with a warning.
            print(
                f'WARN: Instapaper save dropped — URL is in Recycle: {url}',
                file=sys.stderr,
            )
            counts['dup_recycle'] += 1
            if bid:
                archive_ids.append(bid)
            continue

        if existing_note:
            folder_rel = existing_note[0]
            # Instapaper save over an Ignored note: pass through for rescue.
            # triage-write.py (cmd_write) will do the folder move + frontmatter
            # stamp. We mark the bookmark here so run_gemma_pass() skips it —
            # we don't want Gemma reclassifying a rescued article; the rescue
            # flag means "user wants this, period."
            if folder_rel.endswith('Ignored'):
                b['_rescue_from_ignored'] = True
                counts['rescued_from_ignored'] += 1
                survivors.append(b)
                continue
            # Already in Inbox/Review (or other live non-Ignored folder). User
            # is tracking it; archive the bookmark and move on without touching
            # the note or the Recycle log.
            if folder_rel.endswith(('Inbox', 'Review')):
                counts['skipped_in_inbox_or_review'] += 1
                if bid:
                    archive_ids.append(bid)
                continue
            # Terminal folder (Library, Topics): legacy duplicate behavior.
            title = b.get('title') or url
            with recycle_path.open('a', encoding='utf-8') as rf:
                rf.write(f'- [{title}]({url}) (duplicate)\n')
            recycled_urls.add(norm)
            counts['dup_note'] += 1
            if bid:
                archive_ids.append(bid)
            continue

        counts['new'] += 1
        survivors.append(b)

    return survivors, archive_ids, counts


# ---------------------------------------------------------------------------
# Step 3 — fetch article text + hard-route LinkedIn/video/podcast.
# ---------------------------------------------------------------------------


def fetch_text(bookmark_id: int) -> tuple[str, int]:
    """Return (plain_text, html_length). Best-effort; empty string on failure."""
    proc = subprocess.run(
        ['python3', str(SCRIPT_DIR / 'instapaper.py'), 'text', str(bookmark_id)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return '', 0
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return '', 0
    if payload.get('error'):
        return '', 0
    return payload.get('text') or '', int(payload.get('html_length') or 0)


def enrich_and_hard_route(
    bookmarks: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (gemma_candidates, hard_routed, rescue_candidates).

    For each bookmark:
      - set `source: instapaper`, `date_saved` from `time` if present
      - if `_rescue_from_ignored` was set by dedup_and_recycle, divert to
        rescue_candidates and skip text-fetch + classification entirely
        (the existing Ignored note is moved to Inbox as-is)
      - if the URL is LinkedIn/video/podcast, divert to hard_routed with a
        `media_type` / `hard_route_reason` tag and skip Gemma
      - otherwise fetch full text and attach it to the bookmark as
        `description` so Gemma's USER_TEMPLATE picks it up (truncated to 500
        chars in local-triage.py anyway — the point is to get the actual
        article prose instead of the bookmark's 1-line user-entered note)
    """
    gemma_candidates: list[dict] = []
    hard_routed: list[dict] = []
    rescue_candidates: list[dict] = []
    for b in bookmarks:
        url = (b.get('url') or '').strip()
        b['source'] = 'instapaper'
        # Convert Instapaper's `time` epoch to ISO date for date_saved.
        t = b.get('time')
        if t:
            try:
                b['date_saved'] = date.fromtimestamp(int(t)).isoformat()
            except (TypeError, ValueError, OSError):
                pass

        if b.get('_rescue_from_ignored'):
            rescue_candidates.append(b)
            continue

        reason = hard_route_reason(url)
        if reason:
            b['hard_route_reason'] = reason
            if reason == 'linkedin':
                b['media_type'] = 'linkedin-post'
            elif reason == 'video':
                b['media_type'] = 'video'
            elif reason == 'podcast':
                b['media_type'] = 'podcast'
            hard_routed.append(b)
            continue

        # Real article — fetch the extracted text for Gemma.
        bid = b.get('bookmark_id')
        if bid:
            text, _ = fetch_text(bid)
            if text:
                # `description` is what local-triage.py's USER_TEMPLATE prefers
                # over bookmark's title-line-only description. Truncate the
                # article text conservatively to keep the local-model prompt
                # bounded — Gemma slices to 500 chars internally but the raw
                # network payload can be 100s of KB.
                b['description'] = text[:5000]
        gemma_candidates.append(b)

    return gemma_candidates, hard_routed, rescue_candidates


# ---------------------------------------------------------------------------
# Step 4 — Gemma pre-pass + route.
# ---------------------------------------------------------------------------


def run_gemma_pass(articles: list[dict]) -> list[dict]:
    """Annotate each article with `_local`. Pass-through if local_triage disabled."""
    settings = local_triage.load_settings()
    cfg = local_triage.local_triage_config(settings)
    if not cfg['enabled']:
        _log('local_triage disabled; routing all survivors to pending-claude-review')
        return articles
    backend_cfg = local_triage.resolve_backend_config(cfg['raw'])
    for a in articles:
        a['_local'] = local_triage.triage_one(a, cfg, backend_cfg, local_triage.DEFAULT_SYSTEM)
    return articles


def route(
    articles: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Partition Gemma-classified articles. Same matrix as discover-cron.py
    plus one extra rule: ai-tooling articles always go to pending-claude so
    Claude can do the obsolescence check on drain.
    """
    auto_ignored: list[dict] = []
    auto_inbox: list[dict] = []
    pending: list[dict] = []

    for a in articles:
        local = a.get('_local') or {}
        conf = local.get('confidence')
        verdict = local.get('verdict')
        category = local.get('category') or a.get('category')
        err = local.get('error')

        if err:
            pending.append(a)
            continue

        if conf == 'high-not-interested':
            auto_ignored.append(a)
            continue
        if verdict == 'skip' and conf == 'uncertain':
            auto_ignored.append(a)
            continue
        if conf == 'high-interested' and verdict in ('read-now', 'save-reference'):
            # ai-tooling still goes to pending — the obsolescence check is a
            # Claude-only step we can't replicate headlessly.
            if category == 'ai-tooling':
                pending.append(a)
            else:
                auto_inbox.append(a)
            continue

        pending.append(a)

    return auto_ignored, auto_inbox, pending


# ---------------------------------------------------------------------------
# Step 5 — write notes, enqueue pending, archive bookmarks.
# ---------------------------------------------------------------------------


def _to_article_fields(a: dict, triage_source: str, *, force_ignored: bool) -> dict:
    """Map bookmark + _local into triage-write.py's expected fields."""
    local = a.get('_local') or {}
    fm = dict(a)
    fm.setdefault('date_saved', date.today().isoformat())
    fm['category'] = local.get('category') or a.get('category') or 'general'
    fm['confidence'] = local.get('confidence') or 'uncertain'
    fm['verdict'] = local.get('verdict') or 'review'
    fm['tags'] = local.get('tags') or []
    fm['summary'] = (
        local.get('summary')
        or (a.get('description') or '')[:400]  # bookmark description fallback
    )
    fm['verdict_text'] = local.get('reason') or ''
    fm['slop_label'] = local.get('slop_label') or 'clean'
    fm['triage_source'] = triage_source
    if local.get('model'):
        fm['local_model'] = local['model']
    if force_ignored:
        fm['confidence'] = 'high-not-interested'
    return fm


def write_batch(
    articles: list[dict], triage_source: str, *,
    generate_summaries: bool, force_ignored: bool,
) -> dict:
    if not articles:
        return {'written': 0, 'routing': {'inbox': 0, 'review': 0, 'ignored': 0}}
    payload = [_to_article_fields(a, triage_source, force_ignored=force_ignored)
               for a in articles]
    cmd = ['python3', str(SCRIPT_DIR / 'triage-write.py')]
    if generate_summaries:
        cmd.append('--generate-summaries')
    proc = subprocess.run(
        cmd, input=json.dumps(payload),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        _log(f'triage-write.py failed (rc={proc.returncode}): {proc.stderr[:400]}')
        return {'written': 0, 'error': proc.stderr[:400]}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {'written': 0, 'error': 'unparseable stdout', 'raw': proc.stdout[:400]}


def enqueue_pending(articles: list[dict]) -> int:
    if not articles:
        return 0
    proc = subprocess.run(
        ['python3', str(SCRIPT_DIR / 'level2-queue.py'), 'append',
         '--source', 'instapaper',
         '--enqueued-by', 'triage-cron',
         '--reason', 'pre-claude'],
        input=json.dumps(articles), capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        _log(f'level2-queue append failed: {proc.stderr[:200]}')
        return 0
    try:
        return int(json.loads(proc.stdout).get('appended', len(articles)))
    except json.JSONDecodeError:
        return len(articles)


def archive_bookmarks(bookmark_ids: list[int]) -> dict:
    """Archive in Instapaper. Returns {archived: N, total: M, failures: [...]}."""
    if not bookmark_ids:
        return {'archived': 0, 'total': 0, 'failures': []}
    archived = 0
    failures: list[dict] = []
    # One archive call per bookmark (Instapaper API only supports single-id).
    # scripts/instapaper.py accepts a space-separated list and does one call
    # per id, so we can batch through it.
    proc = subprocess.run(
        ['python3', str(SCRIPT_DIR / 'instapaper.py'), 'archive',
         *(str(i) for i in bookmark_ids)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        _log(f'instapaper archive failed (rc={proc.returncode}): {proc.stderr[:400]}')
        return {'archived': 0, 'total': len(bookmark_ids),
                'failures': [{'error': proc.stderr[:200]}]}
    try:
        results = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {'archived': 0, 'total': len(bookmark_ids),
                'failures': [{'error': 'unparseable instapaper output'}]}
    for r in results:
        if r.get('status') == 'ok':
            archived += 1
        else:
            failures.append(r)
    return {'archived': archived, 'total': len(bookmark_ids), 'failures': failures}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description='Headless /curaitor:triage for cron.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Dedup + Gemma but skip writes, enqueue, and archive.')
    args = parser.parse_args()

    started = time.time()
    _log('triage-cron: starting')

    bookmarks = fetch_bookmarks()
    _log(f'fetched: {len(bookmarks)} unread bookmarks')
    if not bookmarks:
        _log('nothing to triage')
        summary = {'fetched': 0, 'dedup': {}, 'auto_ignored': 0, 'auto_inbox': 0,
                   'hard_routed': 0, 'pending_claude_enqueued': 0,
                   'archived': 0, 'elapsed_s': round(time.time() - started, 1)}
        print(json.dumps(summary))
        return 0

    vault = triage_write.find_vault()
    if args.dry_run:
        # Dry-run dedup without mutating Recycle.md.
        recycled_urls = triage_write.build_recycle_index(vault)
        known_urls = triage_write.build_url_index(vault)
        survivors = []
        archive_after = []
        dedup_counts = {'new': 0, 'dup_note': 0, 'dup_recycle': 0, 'no_url': 0}
        for b in bookmarks:
            url = (b.get('url') or '').strip()
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
                survivors.append(b)
    else:
        survivors, archive_after, dedup_counts = dedup_and_recycle(vault, bookmarks)

    _log(f'dedup: {dedup_counts.get("new", 0)} new, '
         f'{dedup_counts.get("dup_note", 0)} duplicates, '
         f'{dedup_counts.get("dup_recycle", 0)} resurfaced from Recycle')

    # Enrich text + hard-route non-text sources + pull out rescues.
    gemma_candidates, hard_routed, rescue_candidates = enrich_and_hard_route(survivors)
    _log(
        f'hard-routed: {len(hard_routed)} (linkedin/video/podcast -> pending-claude); '
        f'rescues: {len(rescue_candidates)} (Instapaper save over Ignored note)'
    )

    # Gemma on everything except rescues (rescue path bypasses all classification).
    gemma_candidates = run_gemma_pass(gemma_candidates)

    auto_ignored, auto_inbox, pending = route(gemma_candidates)
    _log(
        f'route: auto_ignored={len(auto_ignored)}, auto_inbox={len(auto_inbox)}, '
        f'pending_claude={len(pending)} (+ {len(hard_routed)} hard-routed, '
        f'{len(rescue_candidates)} rescues)'
    )

    if args.dry_run:
        print(json.dumps({
            'dry_run': True,
            'fetched': len(bookmarks),
            'survivors': len(survivors),
            'hard_routed': len(hard_routed),
            'rescues': len(rescue_candidates),
            'auto_ignored': len(auto_ignored),
            'auto_inbox': len(auto_inbox),
            'pending_claude': len(pending),
            'dedup': dedup_counts,
        }, indent=2))
        return 0

    # Step 5a: auto-ignored
    ign_res = write_batch(auto_ignored, 'local-model',
                          generate_summaries=False, force_ignored=False)
    # Step 5b: auto-inbox
    inbox_res = write_batch(auto_inbox, 'local-model-high-inbox',
                            generate_summaries=True, force_ignored=False)
    # Step 5c: pending (Gemma-uncertain) -> Ignored + enqueue
    pending_res = write_batch(pending, 'pending-claude-review',
                              generate_summaries=False, force_ignored=True)
    # Step 5d: hard-routed (LinkedIn/video/podcast) -> Ignored + enqueue
    hard_res = write_batch(hard_routed, 'pending-claude-review-hard-route',
                           generate_summaries=False, force_ignored=True)
    # Step 5e: rescues (Instapaper over Ignored) — triage-write.py's rescue
    # branch moves the existing Ignored note to Inbox and stamps
    # rescued_from_ignored: true. The note body is preserved so the user sees
    # whatever summary was there before; we don't generate a new summary.
    rescue_res = write_batch(rescue_candidates, 'instapaper-rescued-from-ignored',
                             generate_summaries=False, force_ignored=False)
    enqueued = enqueue_pending(pending) + enqueue_pending(hard_routed)

    # Collect ALL the bookmark_ids that got written (ignored auto, inbox auto,
    # pending, hard_routed, rescues, dup_note, dup_recycle) + archive in
    # Instapaper. The three dup/skip categories are already in archive_after
    # from dedup_and_recycle; now add survivors + rescues.
    for a in auto_ignored + auto_inbox + pending + hard_routed + rescue_candidates:
        bid = a.get('bookmark_id')
        if bid:
            archive_after.append(int(bid))
    arch_res = archive_bookmarks(archive_after)

    elapsed = round(time.time() - started, 1)
    summary = {
        'fetched': len(bookmarks),
        'dedup': dedup_counts,
        'hard_routed': len(hard_routed),
        'auto_ignored': ign_res.get('routing', {}).get('ignored', 0),
        'auto_inbox': inbox_res.get('routing', {}).get('inbox', 0),
        'pending_claude_written': (
            pending_res.get('routing', {}).get('ignored', 0)
            + hard_res.get('routing', {}).get('ignored', 0)
        ),
        'pending_claude_enqueued': enqueued,
        'rescued_from_ignored': rescue_res.get('rescued_from_ignored', 0),
        'rescued_urls': rescue_res.get('rescued_urls', []),
        'archived': arch_res,
        'elapsed_s': elapsed,
    }
    _log('done in %.1fs' % elapsed)
    print(json.dumps(summary))
    return 0


if __name__ == '__main__':
    os.environ.setdefault('CURAITOR_CRON', '1')
    raise SystemExit(main())
