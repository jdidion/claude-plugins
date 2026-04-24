#!/usr/bin/env python3
"""Summary cache + pre-generation for curaitor articles.

Caches generated summaries at `~/.curaitor/summary-cache/<hash>.md` so
/cu:read (and /cu:review's Inbox-routing verdicts) can render instantly
instead of regenerating a structured summary for every article.

Layers:
  - Layer 1 (this script): cache read/write + atomic rename.
  - Layer 2 (this script): --stream walks the live Inbox, generating
    missing/stale entries in order. Intended to run in the background
    while /cu:read interacts with the user.
  - Layer 3 (this script): --one-url for cron triage/discover to
    pre-generate at add-time; --drain for the queue pattern.

URL normalization matches scripts/triage-write.py's normalize_url so
cache keys align with dedup keys.

Usage:
    python3 scripts/summarize-inbox.py --stream
    python3 scripts/summarize-inbox.py --one-url <URL>
    python3 scripts/summarize-inbox.py --drain
    python3 scripts/summarize-inbox.py --regenerate <URL>
    python3 scripts/summarize-inbox.py --list
    python3 scripts/summarize-inbox.py --gc

Exit 0 on success or no-op. Exit 1 on hard errors (vault not found,
cache dir not writable). Per-article failures are logged but don't
abort the run.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import yaml

CACHE_DIR = Path.home() / '.curaitor' / 'summary-cache'
QUEUE_PATH = Path.home() / '.curaitor' / 'summary-queue.txt'
SETTINGS_PATH = Path(__file__).resolve().parent.parent / 'config' / 'user-settings.yaml'
OLLAMA_DEFAULT = 'http://localhost:11434'
GENERATOR_VERSION = 'cu-summarize v1'


# --- URL normalization (must match triage-write.py) ---

def normalize_url(url):
    url = url.strip().rstrip('/').lower()
    url = url.split('?')[0]
    if url.startswith('https://'):
        url = url[8:]
    elif url.startswith('http://'):
        url = url[7:]
    if url.startswith('www.'):
        url = url[4:]
    return url


def cache_key(url):
    return hashlib.sha256(normalize_url(url).encode('utf-8')).hexdigest()[:16]


def cache_path(url):
    return CACHE_DIR / f'{cache_key(url)}.md'


# --- Vault discovery (mirrors triage-write.py) ---

VAULT_PATHS = [
    os.path.expanduser('~/Obsidian'),
    os.path.expanduser('~/Documents/Obsidian'),
]


def find_vault():
    candidates = []
    config_path = os.path.expanduser('~/Library/Application Support/obsidian/obsidian.json')
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        for v in config.get('vaults', {}).values():
            p = v.get('path', '')
            if os.path.isdir(p):
                candidates.append(p)
    candidates.extend(p for p in VAULT_PATHS if os.path.isdir(p))

    markers = ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']
    best, best_score = None, 0
    for p in candidates:
        score = sum(1 for m in markers if os.path.isdir(os.path.join(p, m)))
        if score > best_score:
            best, best_score = p, score
    if best:
        return best
    if candidates:
        return candidates[0]
    print('Could not find Obsidian vault', file=sys.stderr)
    sys.exit(1)


# --- Config ---

def load_settings():
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        with SETTINGS_PATH.open() as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def summary_config(settings):
    cfg = settings.get('summarize') or {}
    # Fallback to local_triage model if summarize isn't configured — any
    # local model is better than failing, but the plan notes summarization
    # is a stronger task and a non-local default may be preferable later.
    default_model = (settings.get('local_triage') or {}).get('model') or 'huihui_ai/gemma-4-abliterated:e4b'
    return {
        'model': cfg.get('model', default_model),
        'ollama_host': cfg.get('ollama_host', OLLAMA_DEFAULT),
        'temperature': float(cfg.get('temperature', 0.2)),
    }


# --- Note parsing ---

def parse_frontmatter(text):
    if not text.startswith('---'):
        return {}, text
    end = text.find('---', 3)
    if end == -1:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 3:].strip()
    fm = {}
    for line in fm_text.split('\n'):
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        k, v = k.strip(), v.strip()
        if v.startswith('[') and v.endswith(']'):
            fm[k] = [t.strip().strip('"').strip("'") for t in v[1:-1].split(',') if t.strip()]
        else:
            fm[k] = v.strip('"').strip("'")
    return fm, body


def iter_inbox_notes(vault):
    inbox = Path(vault) / 'Curaitor' / 'Inbox'
    if not inbox.is_dir():
        return []
    return sorted(inbox.glob('*.md'))


# --- Cache I/O ---

def cache_read(url):
    p = cache_path(url)
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None


def cache_write_atomic(url, title, body_md, source_mtime_iso):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = cache_path(url)
    header = (
        '---\n'
        f'url: {url}\n'
        f'title: {title!r}\n'
        f'generated_at: {datetime.now(timezone.utc).isoformat(timespec="seconds")}\n'
        f'generator: {GENERATOR_VERSION}\n'
        f'source_mtime: {source_mtime_iso}\n'
        '---\n\n'
    )
    fd, tmp = tempfile.mkstemp(prefix=p.name + '.', dir=str(p.parent), text=True)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(header)
            fh.write(body_md.strip() + '\n')
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def is_cache_fresh(url, source_mtime_iso):
    """True if a cache entry exists and its source_mtime is >= the note's current mtime."""
    text = cache_read(url)
    if not text:
        return False
    fm, _ = parse_frontmatter(text)
    cached_mtime = fm.get('source_mtime', '')
    return bool(cached_mtime) and cached_mtime >= source_mtime_iso


# --- LLM call ---

PROMPT_SYSTEM = """You generate structured article summaries for a curaitor Inbox. Output is reused during deep reading sessions, so be thorough and faithful to the article's content. Do NOT speculate beyond what's in the provided text.

Output format — exact markdown sections in this order, no preamble, no trailing commentary:

## Summary
3-5 sentences covering the article's key contribution, method, and headline result.

## Key findings
- Bullet points of the main results (3-6 bullets).

## Methods
- Brief description of the approach (2-4 bullets).

## Relevance
One paragraph on how this connects to the reader's work. Reader focus: human clinical/translational genomics (cfDNA, variant calling, CNV, aneuploidy, MCED), bioinformatics pipelines, AI tooling for dev workflows, cross-disciplinary methods applicable to human genomics.
"""


def llm_summarize(cfg, title, note_body):
    user = f"""Article title: {title}

Article content (from the Obsidian note body):
{note_body[:8000]}

Produce the structured summary now."""

    req = Request(
        f'{cfg["ollama_host"]}/api/chat',
        data=json.dumps({
            'model': cfg['model'],
            'messages': [
                {'role': 'system', 'content': PROMPT_SYSTEM},
                {'role': 'user', 'content': user},
            ],
            'stream': False,
            'options': {
                'temperature': cfg['temperature'],
                'repeat_penalty': 1.1,
            },
            'think': False,
        }).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    t0 = time.perf_counter()
    with urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read())
    latency = time.perf_counter() - t0
    content = body.get('message', {}).get('content', '').strip()
    # Strip fences if the model wraps output
    content = re.sub(r'^```(?:markdown|md)?\s*|\s*```$', '', content, flags=re.MULTILINE).strip()
    return content, latency


# --- Commands ---

def summarize_note_file(path, cfg, force=False):
    """Generate summary for a single note file and write to cache.

    Returns (status, info) where status is one of:
      'fresh'      — already cached and up-to-date, skipped
      'generated'  — ran the LLM and wrote to cache
      'skipped'    — no URL in frontmatter or other non-error skip
      'error'      — LLM call failed
    """
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        return 'error', f'read: {e}'
    fm, body = parse_frontmatter(text)
    url = fm.get('url', '')
    title = fm.get('title', path.stem)
    if not url:
        return 'skipped', 'no URL in frontmatter'

    source_mtime_iso = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(timespec='seconds')
    if not force and is_cache_fresh(url, source_mtime_iso):
        return 'fresh', str(cache_path(url))

    try:
        summary_md, latency = llm_summarize(cfg, title, body)
    except (HTTPError, URLError, TimeoutError) as e:
        return 'error', f'llm: {e}'
    cp = cache_write_atomic(url, title, summary_md, source_mtime_iso)
    return 'generated', f'{cp} ({latency:.1f}s)'


def summarize_by_url(url, title, body, cfg, force=False):
    """Generate summary for an arbitrary URL + body (used by --one-url / review hand-off).

    source_mtime is stamped 'now' since there's no file backing this call.
    """
    now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not force and is_cache_fresh(url, now_iso):
        return 'fresh', str(cache_path(url))
    try:
        summary_md, latency = llm_summarize(cfg, title, body)
    except (HTTPError, URLError, TimeoutError) as e:
        return 'error', f'llm: {e}'
    cp = cache_write_atomic(url, title, summary_md, now_iso)
    return 'generated', f'{cp} ({latency:.1f}s)'


def cmd_stream(args):
    cfg = summary_config(load_settings())
    vault = find_vault()
    notes = iter_inbox_notes(vault)
    if not notes:
        print(json.dumps({'vault': vault, 'total': 0, 'generated': 0, 'fresh': 0, 'errors': 0}))
        return

    generated = fresh = skipped = errors = 0
    for i, note in enumerate(notes, 1):
        status, info = summarize_note_file(note, cfg, force=args.regenerate)
        if status == 'generated':
            generated += 1
        elif status == 'fresh':
            fresh += 1
        elif status == 'skipped':
            skipped += 1
        else:
            errors += 1
        print(f'[{i}/{len(notes)}] {status}: {note.name} — {info}', file=sys.stderr)

    print(json.dumps({
        'vault': vault,
        'total': len(notes),
        'generated': generated,
        'fresh': fresh,
        'skipped': skipped,
        'errors': errors,
    }, indent=2))


def cmd_one_url(args):
    cfg = summary_config(load_settings())
    vault = find_vault()
    # Find the note with matching URL so we have title + body
    notes = iter_inbox_notes(vault)
    target_norm = normalize_url(args.url)
    for note in notes:
        fm, body = parse_frontmatter(note.read_text(encoding='utf-8'))
        if normalize_url(fm.get('url', '')) == target_norm:
            status, info = summarize_note_file(note, cfg, force=args.regenerate)
            print(json.dumps({'url': args.url, 'status': status, 'info': info}))
            return
    print(json.dumps({'url': args.url, 'status': 'not-found', 'info': 'no Inbox note with matching URL'}))


def cmd_drain(args):
    if not QUEUE_PATH.is_file():
        print(json.dumps({'drained': 0, 'reason': 'no-queue-file'}))
        return
    # Read + atomically truncate. Any URLs added between read and rename
    # end up in the new queue file; we just miss them this drain cycle.
    lines = QUEUE_PATH.read_text(encoding='utf-8').splitlines()
    urls = [u.strip() for u in lines if u.strip() and not u.startswith('#')]
    QUEUE_PATH.write_text('', encoding='utf-8')

    cfg = summary_config(load_settings())
    vault = find_vault()
    notes = iter_inbox_notes(vault)
    by_url = {}
    for note in notes:
        fm, _ = parse_frontmatter(note.read_text(encoding='utf-8'))
        url = fm.get('url', '')
        if url:
            by_url[normalize_url(url)] = note

    generated = errors = 0
    for url in urls:
        note = by_url.get(normalize_url(url))
        if not note:
            print(f'queue: no Inbox note for {url}', file=sys.stderr)
            continue
        status, info = summarize_note_file(note, cfg, force=args.regenerate)
        if status == 'generated':
            generated += 1
        elif status == 'error':
            errors += 1
        print(f'queue[{url}]: {status} — {info}', file=sys.stderr)
    print(json.dumps({'drained': len(urls), 'generated': generated, 'errors': errors}))


def cmd_list(args):
    if not CACHE_DIR.is_dir():
        print('[]')
        return
    out = []
    for p in sorted(CACHE_DIR.glob('*.md')):
        try:
            fm, _ = parse_frontmatter(p.read_text(encoding='utf-8'))
            out.append({
                'path': str(p),
                'url': fm.get('url', ''),
                'title': fm.get('title', ''),
                'generated_at': fm.get('generated_at', ''),
                'source_mtime': fm.get('source_mtime', ''),
            })
        except (OSError, UnicodeDecodeError):
            continue
    print(json.dumps(out, indent=2))


def cmd_gc(args):
    if not CACHE_DIR.is_dir():
        print(json.dumps({'deleted': 0, 'kept': 0, 'reason': 'no-cache-dir'}))
        return
    vault = find_vault()
    # Collect live URLs from all curaitor folders + recycle entries
    live = set()
    for folder in ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored', 'Library', 'Topics']:
        d = Path(vault) / folder
        if not d.is_dir():
            continue
        for p in d.glob('*.md'):
            fm, _ = parse_frontmatter(p.read_text(encoding='utf-8', errors='replace'))
            url = fm.get('url', '')
            if url:
                live.add(cache_key(url))

    deleted = kept = 0
    for p in CACHE_DIR.glob('*.md'):
        key = p.stem
        if key in live:
            kept += 1
        else:
            if args.apply:
                p.unlink()
            deleted += 1
    print(json.dumps({
        'apply': bool(args.apply),
        'kept': kept,
        'deleted': deleted if args.apply else 0,
        'would_delete': 0 if args.apply else deleted,
    }, indent=2))


def main():
    parser = argparse.ArgumentParser(description='Curaitor article summary cache + pre-generation')
    sub = parser.add_mutually_exclusive_group(required=True)
    sub.add_argument('--stream', action='store_true', help='Walk Inbox, generate missing/stale summaries in order')
    sub.add_argument('--one-url', help='Generate a single URL')
    sub.add_argument('--drain', action='store_true', help='Process ~/.curaitor/summary-queue.txt')
    sub.add_argument('--regenerate-url', help='Force-regenerate a single URL')
    sub.add_argument('--list', action='store_true', help='List cache entries as JSON')
    sub.add_argument('--gc', action='store_true', help='Delete cache entries with no matching vault note')
    parser.add_argument('--apply', action='store_true', help='For --gc: actually delete (default: dry-run)')
    parser.add_argument('--regenerate', action='store_true', help='Force regenerate even when fresh')

    args = parser.parse_args()

    if args.stream:
        cmd_stream(args)
    elif args.one_url:
        args.url = args.one_url
        cmd_one_url(args)
    elif args.regenerate_url:
        args.url = args.regenerate_url
        args.regenerate = True
        cmd_one_url(args)
    elif args.drain:
        cmd_drain(args)
    elif args.list:
        cmd_list(args)
    elif args.gc:
        cmd_gc(args)


if __name__ == '__main__':
    main()
