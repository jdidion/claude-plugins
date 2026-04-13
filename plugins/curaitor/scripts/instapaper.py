#!/usr/bin/env python3
"""Instapaper API client for curaitor.

Usage:
    python scripts/instapaper.py list [--limit N] [--folder archive|unread]
    python scripts/instapaper.py text BOOKMARK_ID
    python scripts/instapaper.py archive BOOKMARK_ID [BOOKMARK_ID ...]
    python scripts/instapaper.py archive-all  (archives all unread)

Output is JSON to stdout. Errors go to stderr.
"""

import json
import os
import sys
import html
import re

from requests_oauthlib import OAuth1Session


def load_credentials():
    for path in ['.env', os.path.expanduser('~/.instapaper-credentials')]:
        if os.path.exists(path):
            creds = {}
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        creds[k] = v
            if 'INSTAPAPER_CONSUMER_KEY' in creds:
                return creds
    print("No credentials found in .env or ~/.instapaper-credentials", file=sys.stderr)
    sys.exit(1)


def get_session(creds):
    return OAuth1Session(
        creds['INSTAPAPER_CONSUMER_KEY'],
        client_secret=creds['INSTAPAPER_CONSUMER_SECRET'],
        resource_owner_key=creds.get('INSTAPAPER_ACCESS_TOKEN', ''),
        resource_owner_secret=creds.get('INSTAPAPER_ACCESS_SECRET', ''),
    )


def list_bookmarks(session, limit=500, folder=None):
    data = {'limit': limit}
    if folder:
        data['folder_id'] = folder
    resp = session.post('https://www.instapaper.com/api/1/bookmarks/list', data=data)
    if resp.status_code != 200:
        print(f"API error: {resp.status_code} {resp.text[:200]}", file=sys.stderr)
        sys.exit(1)
    bookmarks = json.loads(resp.text)
    articles = []
    for b in bookmarks:
        if b.get('type') != 'bookmark':
            continue
        articles.append({
            'bookmark_id': b['bookmark_id'],
            'title': html.unescape(b.get('title', '')),
            'url': b.get('url', ''),
            'description': html.unescape(b.get('description', '')),
            'time': b.get('time', 0),
        })
    return articles


def get_text(session, bookmark_id):
    resp = session.post(
        'https://www.instapaper.com/api/1/bookmarks/get_text',
        data={'bookmark_id': bookmark_id}
    )
    if resp.status_code != 200:
        return {'bookmark_id': bookmark_id, 'text': '', 'error': f'{resp.status_code}'}
    raw = resp.text
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = re.sub(r'\s+', ' ', text).strip()
    return {'bookmark_id': bookmark_id, 'text': text[:5000], 'html_length': len(raw)}


def archive_bookmarks(session, bookmark_ids):
    results = []
    for bid in bookmark_ids:
        resp = session.post(
            'https://www.instapaper.com/api/1/bookmarks/archive',
            data={'bookmark_id': bid}
        )
        results.append({
            'bookmark_id': bid,
            'status': 'ok' if resp.status_code == 200 else f'error:{resp.status_code}'
        })
    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    creds = load_credentials()
    session = get_session(creds)

    if cmd == 'list':
        limit = 500
        folder = None
        args = sys.argv[2:]
        while args:
            if args[0] == '--limit' and len(args) > 1:
                limit = int(args[1])
                args = args[2:]
            elif args[0] == '--folder' and len(args) > 1:
                folder = args[1]
                args = args[2:]
            else:
                args = args[1:]
        articles = list_bookmarks(session, limit, folder)
        json.dump(articles, sys.stdout, indent=2)

    elif cmd == 'text':
        if len(sys.argv) < 3:
            print("Usage: instapaper.py text BOOKMARK_ID", file=sys.stderr)
            sys.exit(1)
        result = get_text(session, sys.argv[2])
        json.dump(result, sys.stdout, indent=2)

    elif cmd == 'archive':
        ids = sys.argv[2:]
        if not ids:
            print("Usage: instapaper.py archive ID [ID ...]", file=sys.stderr)
            sys.exit(1)
        results = archive_bookmarks(session, ids)
        json.dump(results, sys.stdout, indent=2)

    elif cmd == 'archive-all':
        articles = list_bookmarks(session)
        ids = [str(a['bookmark_id']) for a in articles]
        if not ids:
            json.dump({'archived': 0}, sys.stdout)
        else:
            results = archive_bookmarks(session, ids)
            ok = sum(1 for r in results if r['status'] == 'ok')
            json.dump({'archived': ok, 'total': len(ids), 'results': results}, sys.stdout, indent=2)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
