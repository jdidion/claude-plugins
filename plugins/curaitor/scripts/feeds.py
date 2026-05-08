#!/usr/bin/env python3
"""Fetch and parse feeds for curaitor.

Usage:
    python scripts/feeds.py [--days N] [--category CAT] [--feed NAME]

Reads config/feeds.yaml, fetches each feed, and outputs JSON to stdout.

Per-feed `fetch_via` dispatches to one of two backends:
  - rss      (default) — direct RSS/Atom/RDF over HTTP via stdlib urllib
  - openalex — OpenAlex /works by ISSN; unlocks ex-BMC journals now behind
               Springer auth redirects

The short-lived `feedly` backend was removed 2026-05-08 — it depended on a
browser-scraped FEEDLY_TOKEN with unpredictable expiry, and the two gated
journals it unlocked (Annual Review of Genomics, Briefings in Bioinformatics)
weren't worth the operational friction. Cloudflare-JS-challenge-gated sources
that aren't reachable via RSS or OpenAlex are now just dropped from feeds.yaml.
"""

import json
import os
import sys
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ssl_util import build_ssl_context

_SSL_CONTEXT = build_ssl_context()

_POLITE_UA = 'curaitor/1.0 (mailto:johnpaul@didion.net)'


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


def _to_rfc2822(dt):
    """Format a datetime as RFC 2822, which parse_date() already handles."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime('%a, %d %b %Y %H:%M:%S %z')


# ---------------------------------------------------------------------------
# Backend: RSS / Atom / RDF (default)
# ---------------------------------------------------------------------------

def fetch_via_rss(feed, days=None, timeout=30):
    """Fetch and parse an RSS/Atom feed, return (articles, error)."""
    url = feed['url']
    user_agent = feed.get('user_agent') or 'Mozilla/5.0 (compatible; curaitor/1.0)'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': user_agent})
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
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


# ---------------------------------------------------------------------------
# Backend: OpenAlex /works
# ---------------------------------------------------------------------------

def _reconstitute_abstract(inverted_index):
    """OpenAlex returns abstracts as {word: [positions]}; rebuild to a string."""
    if not inverted_index:
        return ''
    positions = {}
    for word, pos_list in inverted_index.items():
        for p in pos_list:
            positions[p] = word
    return ' '.join(positions[i] for i in sorted(positions))


def fetch_via_openalex(feed, days=7, timeout=30):
    """Fetch articles via OpenAlex /works filtered by ISSN. feeds.yaml needs `issn`."""
    issn = feed.get('issn')
    if not issn:
        return [], 'openalex: feed entry missing required `issn` field'

    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%d')
    qs = urllib.parse.urlencode({
        'filter': f'primary_location.source.issn:{issn},from_publication_date:{from_date}',
        'sort': 'publication_date:desc',
        'per-page': '100',
        'select': 'id,title,publication_date,doi,primary_location,abstract_inverted_index',
    })
    url = f'https://api.openalex.org/works?{qs}'
    req = urllib.request.Request(url, headers={'User-Agent': _POLITE_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            raw = resp.read().decode()
    except Exception as e:
        return [], f'openalex: {e}'

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], f'openalex: invalid JSON: {e}'

    articles = []
    for work in payload.get('results', []):
        title = (work.get('title') or '').strip()
        doi = work.get('doi') or ''
        if doi.startswith('https://doi.org/'):
            link = doi
        elif doi:
            link = f'https://doi.org/{doi}'
        else:
            primary = work.get('primary_location') or {}
            link = (primary.get('landing_page_url') or work.get('id') or '')
        desc = _reconstitute_abstract(work.get('abstract_inverted_index')).strip()[:500]
        pub_date = work.get('publication_date') or ''
        if pub_date:
            try:
                dt = datetime.strptime(pub_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                date = _to_rfc2822(dt)
            except ValueError:
                date = pub_date
        else:
            date = ''
        articles.append({
            'title': title,
            'url': link,
            'description': desc,
            'date': date,
        })
    return articles, None


# ---------------------------------------------------------------------------
# Dispatch table + main
# ---------------------------------------------------------------------------

_FETCHERS = {
    'rss': fetch_via_rss,
    'openalex': fetch_via_openalex,
}


def main():
    days = 7
    category_filter = None
    feed_filter = None
    args = sys.argv[1:]
    while args:
        if args[0] == '--days' and len(args) > 1:
            days = int(args[1])
            args = args[2:]
        elif args[0] == '--category' and len(args) > 1:
            category_filter = args[1]
            args = args[2:]
        elif args[0] == '--feed' and len(args) > 1:
            feed_filter = args[1]
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
        if feed_filter and feed.get('name') != feed_filter:
            continue

        fetch_via = feed.get('fetch_via', 'rss')
        fetcher = _FETCHERS.get(fetch_via)
        if fetcher is None:
            results.append({
                'feed': feed['name'],
                'error': f'unknown fetch_via={fetch_via!r}',
                'articles': [],
            })
            continue

        articles, error = fetcher(feed, days=days)
        if error:
            results.append({
                'feed': feed['name'],
                'error': error,
                'articles': [],
            })
            continue

        # Stamp every article with its origin feed so downstream scripts
        # (local-triage.py, triage-write.py, accuracy-metrics.py) can route
        # and aggregate by feed without re-plumbing the parent scope.
        feed_name = feed['name']
        feed_weight = feed.get('weight')
        for a in articles:
            a['feed_name'] = feed_name
            if feed_weight is not None:
                a['feed_weight'] = feed_weight

        recent = []
        for a in articles:
            parsed = parse_date(a['date'])
            if parsed is None or parsed.replace(tzinfo=timezone.utc if parsed.tzinfo is None else parsed.tzinfo) >= cutoff:
                recent.append(a)

        results.append({
            'feed': feed['name'],
            'category': feed.get('category', ''),
            'weight': feed_weight,
            'fetch_via': fetch_via,
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
