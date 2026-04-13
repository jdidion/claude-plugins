#!/usr/bin/env python3
"""Import RSS feeds from an OPML file into config/feeds.yaml.

Usage:
    python scripts/import-opml.py OPML_FILE [--folder FOLDER_NAME] [--append]

Options:
    --folder NAME   Only import feeds from this folder/outline (case-insensitive)
    --append        Append to existing feeds.yaml instead of overwriting

Examples:
    python scripts/import-opml.py ~/Downloads/feedly-export.opml
    python scripts/import-opml.py ~/Downloads/feedly-export.opml --folder Science
    python scripts/import-opml.py ~/Downloads/export.opml --folder Tech --append
"""

import os
import sys
import xml.etree.ElementTree as ET

import yaml


def parse_opml(path, folder_filter=None):
    """Parse OPML file and return list of feeds."""
    tree = ET.parse(path)
    root = tree.getroot()
    body = root.find('body')
    if body is None:
        print("Invalid OPML: no <body> element", file=sys.stderr)
        sys.exit(1)

    feeds = []
    folders_found = []

    for outline in body.findall('outline'):
        folder_name = outline.get('title', outline.get('text', ''))
        folders_found.append(f"{folder_name} ({len(outline.findall('outline'))} feeds)")

        if folder_filter and folder_name.lower() != folder_filter.lower():
            continue

        # Check if this outline is a feed itself (no children)
        if outline.get('xmlUrl'):
            feeds.append({
                'name': outline.get('title', outline.get('text', '')),
                'url': outline.get('xmlUrl'),
                'category': 'uncategorized',
            })
            continue

        # Otherwise it's a folder — get child feeds
        category = folder_name.lower().replace(' ', '-')
        for feed in outline.findall('outline'):
            xml_url = feed.get('xmlUrl')
            if xml_url:
                feeds.append({
                    'name': feed.get('title', feed.get('text', '')),
                    'url': xml_url,
                    'category': category,
                })

    return feeds, folders_found


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    opml_path = sys.argv[1]
    folder_filter = None
    append = False

    args = sys.argv[2:]
    while args:
        if args[0] == '--folder' and len(args) > 1:
            folder_filter = args[1]
            args = args[2:]
        elif args[0] == '--append':
            append = True
            args = args[1:]
        else:
            print(f"Unknown argument: {args[0]}", file=sys.stderr)
            args = args[1:]

    if not os.path.exists(opml_path):
        print(f"File not found: {opml_path}", file=sys.stderr)
        sys.exit(1)

    feeds, folders = parse_opml(opml_path, folder_filter)

    if not feeds:
        print("No feeds found.", file=sys.stderr)
        if folder_filter:
            print(f"Available folders: {', '.join(folders)}", file=sys.stderr)
        sys.exit(1)

    # Load existing feeds if appending
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'feeds.yaml')
    existing = []
    if append and os.path.exists(config_path):
        with open(config_path) as f:
            data = yaml.safe_load(f)
        existing = data.get('feeds', []) if data else []
        existing_urls = {f['url'] for f in existing}
        feeds = [f for f in feeds if f['url'] not in existing_urls]

    all_feeds = existing + feeds

    # Write
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, 'w') as f:
        f.write('# RSS feeds for /cu:discover\n')
        f.write(f'# Imported from {os.path.basename(opml_path)}\n\n')
        yaml.dump({'feeds': all_feeds}, f, default_flow_style=False, sort_keys=False)

    action = "appended" if append else "wrote"
    print(f"{action} {len(feeds)} feeds to config/feeds.yaml ({len(all_feeds)} total)")
    for feed in feeds:
        print(f"  [{feed['category']}] {feed['name']}")


if __name__ == '__main__':
    main()
