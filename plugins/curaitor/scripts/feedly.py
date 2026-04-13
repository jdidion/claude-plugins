#!/usr/bin/env python3
"""Feedly integration for curaitor — mark discovered articles as read.

Usage:
    python scripts/feedly.py profile                        # test auth
    python scripts/feedly.py list STREAM_ID [--unread-only] # list entries
    python scripts/feedly.py mark-read STREAM_ID --urls-file FILE
    python scripts/feedly.py mark-read STREAM_ID --urls URL1 URL2 ...
    echo URL | python scripts/feedly.py mark-read STREAM_ID

Auth: set FEEDLY_TOKEN in .env or environment.
Get a developer token at https://feedly.com/v3/auth/dev (must be logged in).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FEEDLY_API = "https://cloud.feedly.com"


def load_token():
    """Load Feedly token from .env or environment."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if line.startswith('FEEDLY_TOKEN='):
                    return line.strip().split('=', 1)[1]
    return os.environ.get('FEEDLY_TOKEN')


def api_request(method, path, token, data=None):
    """Make authenticated request to Feedly API."""
    url = f"{FEEDLY_API}{path}"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def cmd_profile(args):
    """Test authentication."""
    token = load_token()
    if not token:
        print("No FEEDLY_TOKEN found. Add to .env or set in environment.", file=sys.stderr)
        print("Get a token at: https://feedly.com/v3/auth/dev", file=sys.stderr)
        sys.exit(1)
    profile = api_request('GET', '/v3/profile', token)
    print(f"Authenticated as: {profile.get('fullName', profile.get('email', 'unknown'))}")
    print(f"User ID: {profile.get('id')}")


def cmd_list(args):
    """List entries in a stream/collection."""
    token = load_token()
    if not token:
        print("No FEEDLY_TOKEN found", file=sys.stderr)
        sys.exit(1)

    stream_id = args.stream_id
    params = {'count': str(args.count)}
    if args.unread_only:
        params['unreadOnly'] = 'true'
    qs = urllib.parse.urlencode({'streamId': stream_id, **params})

    result = api_request('GET', f'/v3/streams/contents?{qs}', token)
    entries = result.get('items', [])

    if args.urls_only:
        for entry in entries:
            alts = entry.get('alternate', [])
            url = alts[0].get('href', '') if alts else ''
            if url:
                print(url)
    else:
        for entry in entries:
            title = entry.get('title', 'No title')[:80]
            alts = entry.get('alternate', [])
            url = alts[0].get('href', '') if alts else ''
            unread = entry.get('unread', True)
            status = '*' if unread else ' '
            print(f"[{status}] {title}")
            if url:
                print(f"    {url}")

    print(f"\n{len(entries)} entries", file=sys.stderr)


def cmd_mark_read(args):
    """Mark specific entries as read by URL."""
    token = load_token()
    if not token:
        print("No FEEDLY_TOKEN found", file=sys.stderr)
        sys.exit(1)

    # Collect target URLs
    if args.urls_file:
        with open(args.urls_file) as f:
            target_urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.urls:
        target_urls = args.urls
    else:
        target_urls = [line.strip() for line in sys.stdin if line.strip()]

    if not target_urls:
        print("No URLs provided", file=sys.stderr)
        sys.exit(1)

    # Normalize URLs for matching
    def normalize(url):
        url = url.rstrip('/').lower()
        # Strip all query parameters (rss=1, utm_*, etc.)
        url = url.split('?')[0]
        # Strip protocol
        if url.startswith('https://'):
            url = url[8:]
        elif url.startswith('http://'):
            url = url[7:]
        # Strip www.
        if url.startswith('www.'):
            url = url[4:]
        return url

    target_set = {normalize(u): u for u in target_urls}

    # Fetch all unread entries from the stream (paginate)
    stream_id = args.stream_id
    all_entries = []
    continuation = None
    while True:
        params = {'count': '1000', 'unreadOnly': 'true'}
        if continuation:
            params['continuation'] = continuation
        qs = urllib.parse.urlencode({'streamId': stream_id, **params})
        result = api_request('GET', f'/v3/streams/contents?{qs}', token)
        entries = result.get('items', [])
        all_entries.extend(entries)
        continuation = result.get('continuation')
        if not continuation or not entries:
            break

    print(f"Fetched {len(all_entries)} unread entries from Feedly", file=sys.stderr)

    # Match
    matched = []
    for entry in all_entries:
        alts = entry.get('alternate', [])
        entry_url = alts[0].get('href', '') if alts else ''
        if not entry_url:
            continue
        norm = normalize(entry_url)
        if norm in target_set:
            matched.append((entry['id'], entry.get('title', entry_url)[:80], target_set[norm]))
            del target_set[norm]

    if not matched:
        print(f"No matches found for {len(target_urls)} URLs among {len(all_entries)} unread entries")
        return

    # Mark as read in batches of 100
    entry_ids = [m[0] for m in matched]
    for i in range(0, len(entry_ids), 100):
        batch = entry_ids[i:i+100]
        api_request('POST', '/v3/markers', token, {
            "action": "markAsRead",
            "type": "entries",
            "entryIds": batch,
        })

    print(f"Marked {len(matched)} articles as read:")
    for _, title, orig_url in matched:
        print(f"  + {title}")

    remaining = len(target_urls) - len(matched)
    if remaining > 0:
        print(f"\n{remaining} URLs not found in Feedly (may be from Instapaper or already read)")


def main():
    parser = argparse.ArgumentParser(description='Feedly integration for curaitor')
    sub = parser.add_subparsers(dest='command')

    sub.add_parser('profile', help='Test authentication')

    p_list = sub.add_parser('list', help='List entries in a stream')
    p_list.add_argument('stream_id')
    p_list.add_argument('--count', type=int, default=100)
    p_list.add_argument('--unread-only', action='store_true')
    p_list.add_argument('--urls-only', action='store_true')

    p_mark = sub.add_parser('mark-read', help='Mark articles as read by URL')
    p_mark.add_argument('stream_id')
    p_mark.add_argument('--urls', nargs='+', help='URLs to mark as read')
    p_mark.add_argument('--urls-file', help='File with URLs, one per line')

    args = parser.parse_args()

    if args.command == 'profile':
        cmd_profile(args)
    elif args.command == 'list':
        cmd_list(args)
    elif args.command == 'mark-read':
        cmd_mark_read(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
