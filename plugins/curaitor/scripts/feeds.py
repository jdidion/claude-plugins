#!/usr/bin/env python3
"""Fetch and parse RSS feeds for curaitor.

Usage:
    python scripts/feeds.py [--days N] [--category CAT]

Reads config/feeds.yaml, fetches each feed, parses articles,
and outputs JSON to stdout.
"""

import json
import os
import sys
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import yaml


def parse_date(date_str):
    """Best-effort parse of RSS date strings."""
    if not date_str:
        return None
    for fmt in [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S %Z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d',
    ]:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def fetch_feed(url, timeout=30, user_agent=None):
    """Fetch and parse an RSS/Atom feed, return list of articles."""
    try:
        ua = user_agent or 'Mozilla/5.0 (compatible; curaitor/1.0)'
        req = urllib.request.Request(url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
    except Exception as e:
        return [], str(e)

    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return [], f"XML parse error: {e}"

    articles = []
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'rss1': 'http://purl.org/rss/1.0/',
        'content': 'http://purl.org/rss/1.0/modules/content/',
    }

    # RSS 1.0 (RDF)
    for item in root.findall('.//rss1:item', ns):
        title = (item.findtext('rss1:title', namespaces=ns) or '').strip()
        link = (item.findtext('rss1:link', namespaces=ns) or '').strip()
        desc = (item.findtext('rss1:description', namespaces=ns) or
                item.findtext('content:encoded', namespaces=ns) or '').strip()
        date = item.findtext('dc:date', namespaces=ns) or ''
        desc = re.sub(r'<[^>]+>', ' ', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()[:500]
        articles.append({
            'title': title,
            'url': link,
            'description': desc,
            'date': date.strip(),
        })

    # RSS 2.0
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        desc = (item.findtext('description') or '').strip()
        date = item.findtext('pubDate') or item.findtext('dc:date', namespaces=ns) or ''
        # Strip HTML from description
        desc = re.sub(r'<[^>]+>', ' ', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()[:500]
        articles.append({
            'title': title,
            'url': link,
            'description': desc,
            'date': date.strip(),
        })

    # Atom
    for entry in root.findall('.//atom:entry', ns):
        title = (entry.findtext('atom:title', namespaces=ns) or '').strip()
        link_el = entry.find('atom:link[@rel="alternate"]', ns) or entry.find('atom:link', ns)
        link = link_el.get('href', '') if link_el is not None else ''
        desc = (entry.findtext('atom:summary', namespaces=ns) or
                entry.findtext('atom:content', namespaces=ns) or '').strip()
        desc = re.sub(r'<[^>]+>', ' ', desc)
        desc = re.sub(r'\s+', ' ', desc).strip()[:500]
        date = (entry.findtext('atom:published', namespaces=ns) or
                entry.findtext('atom:updated', namespaces=ns) or '')
        articles.append({
            'title': title,
            'url': link,
            'description': desc,
            'date': date.strip(),
        })

    return articles, None


def main():
    days = 7
    category_filter = None
    args = sys.argv[1:]
    while args:
        if args[0] == '--days' and len(args) > 1:
            days = int(args[1])
            args = args[2:]
        elif args[0] == '--category' and len(args) > 1:
            category_filter = args[1]
            args = args[2:]
        else:
            args = args[1:]

    feeds_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'feeds.yaml')
    if not os.path.exists(feeds_path):
        print(json.dumps({'error': 'config/feeds.yaml not found', 'feeds': []}))
        sys.exit(1)

    with open(feeds_path) as f:
        config = yaml.safe_load(f)

    feeds = config.get('feeds', [])
    if not feeds:
        print(json.dumps({'error': 'No feeds configured', 'feeds': []}))
        sys.exit(0)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    results = []

    for feed in feeds:
        if category_filter and feed.get('category') != category_filter:
            continue

        articles, error = fetch_feed(feed['url'], user_agent=feed.get('user_agent'))
        if error:
            results.append({
                'feed': feed['name'],
                'error': error,
                'articles': [],
            })
            continue

        # Filter by date
        recent = []
        for a in articles:
            parsed = parse_date(a['date'])
            if parsed is None or parsed.replace(tzinfo=timezone.utc if parsed.tzinfo is None else parsed.tzinfo) >= cutoff:
                recent.append(a)

        results.append({
            'feed': feed['name'],
            'category': feed.get('category', ''),
            'total': len(articles),
            'recent': len(recent),
            'articles': recent,
        })

    total_articles = sum(r.get('recent', 0) for r in results)
    print(json.dumps({
        'feeds_checked': len(results),
        'total_articles': total_articles,
        'days': days,
        'results': results,
    }, indent=2))


if __name__ == '__main__':
    main()
