#!/usr/bin/env python3
"""Zotero integration for curaitor.

Usage:
    python scripts/zotero.py check                          # check if Zotero is running
    python scripts/zotero.py collections                    # list collections
    python scripts/zotero.py save URL [--title T] [--tags t1,t2] [--collection C1]
    python scripts/zotero.py add-note ITEM_KEY NOTE_HTML    # add a child note
    python scripts/zotero.py search QUERY                   # search for items

Uses Zotero's local connector API (localhost:23119).
"""

import json
import os
import sys
import urllib.request
import urllib.error

ZOTERO_URL = "http://localhost:23119"


def load_config():
    for path in ['config/zotero.yaml', os.path.expanduser('config/zotero.yaml')]:
        if os.path.exists(path):
            import yaml
            with open(path) as f:
                return yaml.safe_load(f)
    return {'enabled': True, 'api': 'local', 'collection_id': '', 'auto_tag': True, 'save_notes': True}


def zotero_request(path, data=None, method=None):
    """Make a request to the Zotero local API."""
    url = f"{ZOTERO_URL}{path}"
    headers = {"Content-Type": "application/json"}

    if data is not None:
        body = json.dumps(data).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers=headers, method=method or 'POST')
    else:
        req = urllib.request.Request(url, headers=headers, method=method or 'GET')

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.URLError as e:
        return {'error': str(e)}
    except json.JSONDecodeError:
        return {'ok': True}


def check():
    """Check if Zotero is running and local API is enabled."""
    result = zotero_request("/connector/getSelectedCollection", data={})
    if 'error' in result:
        return {'running': False, 'error': result['error']}
    return {
        'running': True,
        'libraryID': result.get('libraryID'),
        'selected_collection': result.get('id'),
    }


def list_collections():
    """List available Zotero collections."""
    result = zotero_request("/connector/getSelectedCollection", data={})
    if 'error' in result:
        return {'error': result['error']}

    targets = result.get('targets', [])
    collections = []
    for t in targets:
        collections.append({
            'id': t.get('id', ''),
            'name': t.get('name', ''),
            'level': t.get('level', 0),
        })
    return {'collections': collections}


def save_item(url, title=None, tags=None, collection_id=None):
    """Save a URL to Zotero via connector."""
    config = load_config()
    target_id = collection_id or config.get('collection_id', '')

    # Save via connector
    payload = {
        'url': url,
        'title': title or '',
    }
    if target_id:
        payload['targetID'] = target_id

    result = zotero_request("/connector/saveSnapshot", data=payload)

    # Try to find the item and add tags
    if tags and config.get('auto_tag', True):
        import time
        time.sleep(1)  # wait for Zotero to process
        search_result = search_items(title[:30] if title else url)
        if search_result.get('items'):
            item_key = search_result['items'][0].get('key', '')
            if item_key:
                tag_list = [{'tag': t} for t in tags]
                tag_list.append({'tag': 'curaitor'})
                zotero_request(
                    f"/api/users/0/items/{item_key}",
                    data={'tags': tag_list},
                    method='PATCH'
                )
                return {'saved': True, 'item_key': item_key, 'tags_added': len(tag_list)}

    return {'saved': True, 'item_key': None}


def add_note(item_key, note_html):
    """Add a child note to an existing Zotero item."""
    result = zotero_request("/api/users/0/items", data=[{
        'itemType': 'note',
        'parentItem': item_key,
        'note': note_html,
        'tags': [{'tag': 'curaitor'}],
    }])
    return result


def search_items(query):
    """Search for items in the library."""
    try:
        url = f"{ZOTERO_URL}/api/users/0/items?q={urllib.parse.quote(query)}&limit=5"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            items = json.loads(resp.read().decode('utf-8'))
            return {'items': [{'key': i.get('key', ''), 'title': i.get('data', {}).get('title', '')} for i in items]}
    except Exception as e:
        return {'error': str(e)}


def main():
    import urllib.parse

    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'check':
        json.dump(check(), sys.stdout, indent=2)

    elif cmd == 'collections':
        json.dump(list_collections(), sys.stdout, indent=2)

    elif cmd == 'save':
        if len(sys.argv) < 3:
            print("Usage: zotero.py save URL [--title T] [--tags t1,t2] [--collection C1]", file=sys.stderr)
            sys.exit(1)
        url = sys.argv[2]
        title = None
        tags = None
        collection = None
        args = sys.argv[3:]
        while args:
            if args[0] == '--title' and len(args) > 1:
                title = args[1]; args = args[2:]
            elif args[0] == '--tags' and len(args) > 1:
                tags = args[1].split(','); args = args[2:]
            elif args[0] == '--collection' and len(args) > 1:
                collection = args[1]; args = args[2:]
            else:
                args = args[1:]
        json.dump(save_item(url, title, tags, collection), sys.stdout, indent=2)

    elif cmd == 'add-note':
        if len(sys.argv) < 4:
            print("Usage: zotero.py add-note ITEM_KEY NOTE_HTML", file=sys.stderr)
            sys.exit(1)
        json.dump(add_note(sys.argv[2], sys.argv[3]), sys.stdout, indent=2)

    elif cmd == 'search':
        if len(sys.argv) < 3:
            print("Usage: zotero.py search QUERY", file=sys.stderr)
            sys.exit(1)
        json.dump(search_items(sys.argv[2]), sys.stdout, indent=2)

    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
