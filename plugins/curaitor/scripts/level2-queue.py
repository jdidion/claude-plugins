#!/usr/bin/env python3
"""Persistent queue for level-2 (Claude) triage work that didn't complete.

When Gemma 4 (local level-1 triage) forwards an article as `uncertain` or
`high-interested`, the Claude supervisor is supposed to finalize the
decision. If Claude fails — most commonly auth expiry in cron context —
the forwarded articles would be lost. This queue captures them so the
next interactive session (the user is already authed there) can finish
the work before doing anything else.

Queue file: ~/.curaitor/level2-pending.json
Schema: {
  "version": 1,
  "updated_at": "2026-04-25T13:00:00Z",
  "articles": [
    {
      "url": "...",
      "title": "...",
      "source": "rss" | "instapaper",
      "feed_name": "...",
      "summary": "...",
      "_local": {...},  # output from local-triage.py
      "enqueued_at": "2026-04-25T12:00:00Z",
      "enqueued_by": "cu:discover" | "cu:triage",
      "reason": "auth-expired" | "timeout" | "crash" | "unknown"
    },
    ...
  ]
}

Usage:
  # Cron: before calling Claude, enqueue articles
  cat articles.json | python3 scripts/level2-queue.py append \
      --source rss --enqueued-by cu:discover --reason pre-claude

  # Cron: after successful Claude completion, clear matched URLs
  python3 scripts/level2-queue.py ack --urls-file /tmp/processed-urls.txt

  # Interactive: check + drain
  python3 scripts/level2-queue.py status      # count + age
  python3 scripts/level2-queue.py drain       # print articles as JSON, clear queue
  python3 scripts/level2-queue.py peek        # print without clearing
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

QUEUE_PATH = Path.home() / '.curaitor' / 'level2-pending.json'
SCHEMA_VERSION = 1


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _load():
    if not QUEUE_PATH.is_file():
        return {'version': SCHEMA_VERSION, 'updated_at': _now_iso(), 'articles': []}
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or 'articles' not in data:
            return {'version': SCHEMA_VERSION, 'updated_at': _now_iso(), 'articles': []}
        return data
    except (OSError, json.JSONDecodeError):
        return {'version': SCHEMA_VERSION, 'updated_at': _now_iso(), 'articles': []}


def _save(data):
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data['updated_at'] = _now_iso()
    data['version'] = SCHEMA_VERSION
    fd, tmp = tempfile.mkstemp(prefix=QUEUE_PATH.name + '.', dir=str(QUEUE_PATH.parent), text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
            fh.write('\n')
        os.replace(tmp, QUEUE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_append(args):
    """Append articles from stdin to the queue, dedup by URL."""
    articles_in = json.load(sys.stdin)
    if not isinstance(articles_in, list):
        articles_in = [articles_in]
    data = _load()
    existing = {a.get('url', '') for a in data['articles']}
    added = 0
    for a in articles_in:
        url = a.get('url', '').strip()
        if not url or url in existing:
            continue
        entry = {
            **a,
            'enqueued_at': _now_iso(),
            'enqueued_by': args.enqueued_by or 'unknown',
            'reason': args.reason or 'unknown',
        }
        data['articles'].append(entry)
        existing.add(url)
        added += 1
    _save(data)
    print(json.dumps({'added': added, 'total': len(data['articles'])}))


def cmd_ack(args):
    """Remove URLs from the queue (call after Claude successfully processes them)."""
    if args.urls_file:
        with open(args.urls_file) as f:
            urls = {line.strip() for line in f if line.strip() and not line.startswith('#')}
    elif args.urls:
        urls = set(args.urls)
    else:
        urls = {line.strip() for line in sys.stdin if line.strip()}
    if not urls:
        print(json.dumps({'acked': 0, 'remaining': None, 'reason': 'no-urls-provided'}))
        return
    data = _load()
    before = len(data['articles'])
    data['articles'] = [a for a in data['articles'] if a.get('url', '') not in urls]
    _save(data)
    print(json.dumps({
        'acked': before - len(data['articles']),
        'remaining': len(data['articles']),
    }))


def cmd_status(args):
    data = _load()
    articles = data.get('articles', [])
    oldest = min((a.get('enqueued_at', '') for a in articles), default=None)
    by_source = {}
    by_reason = {}
    for a in articles:
        by_source[a.get('source', 'unknown')] = by_source.get(a.get('source', 'unknown'), 0) + 1
        by_reason[a.get('reason', 'unknown')] = by_reason.get(a.get('reason', 'unknown'), 0) + 1
    print(json.dumps({
        'pending': len(articles),
        'oldest_enqueued_at': oldest,
        'by_source': by_source,
        'by_reason': by_reason,
    }, indent=2))


def cmd_drain(args):
    """Print articles as JSON array, then clear the queue (atomic)."""
    data = _load()
    articles = data.get('articles', [])
    json.dump(articles, sys.stdout, indent=2)
    sys.stdout.write('\n')
    # Only clear if we actually read something
    if articles:
        _save({'version': SCHEMA_VERSION, 'updated_at': _now_iso(), 'articles': []})


def cmd_peek(args):
    data = _load()
    json.dump(data.get('articles', []), sys.stdout, indent=2)
    sys.stdout.write('\n')


def main():
    parser = argparse.ArgumentParser(description='Level-2 Claude triage pending queue')
    sub = parser.add_subparsers(dest='cmd', required=True)

    p_append = sub.add_parser('append', help='Append articles from stdin')
    p_append.add_argument('--source', help='Source hint: rss|instapaper (recorded per article if missing)')
    p_append.add_argument('--enqueued-by', help='Caller tag: cu:discover|cu:triage|manual')
    p_append.add_argument('--reason', help='Why queued: pre-claude|auth-expired|timeout|crash')

    p_ack = sub.add_parser('ack', help='Remove URLs from queue')
    p_ack.add_argument('--urls', nargs='+', help='URLs to ack')
    p_ack.add_argument('--urls-file', help='File with URLs, one per line')

    sub.add_parser('status', help='Print queue depth + oldest entry age')
    sub.add_parser('drain', help='Print articles as JSON, then clear queue')
    sub.add_parser('peek', help='Print articles as JSON without clearing')

    args = parser.parse_args()
    dispatch = {
        'append': cmd_append,
        'ack': cmd_ack,
        'status': cmd_status,
        'drain': cmd_drain,
        'peek': cmd_peek,
    }
    dispatch[args.cmd](args)


if __name__ == '__main__':
    main()
