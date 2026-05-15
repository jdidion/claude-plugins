#!/usr/bin/env python3
"""Write triage results to Obsidian from minimal LLM JSON output.

The LLM only needs to produce evaluation results (summary, category, verdict, tags).
This script handles: deduplication, folder routing, frontmatter templating, filename
sanitization, and writing — saving tokens on boilerplate generation.

Usage:
    # Pipe LLM evaluation JSON:
    echo '[{...}]' | python3 scripts/triage-write.py

    # Or from file:
    python3 scripts/triage-write.py < /tmp/evaluations.json

    # Dedup-only mode (check which URLs already exist):
    python3 scripts/triage-write.py --dedup-only --urls url1 url2 ...
    python3 scripts/triage-write.py --dedup-only --urls-file /tmp/urls.txt

Input JSON: array of objects, each with:
  - title (str, required)
  - url (str, required)
  - summary (str, required) — 2-3 sentences
  - category (str) — ai-tooling|genomics|methods|general
  - confidence (str) — high-interested|uncertain|high-not-interested
  - verdict (str) — read-now|save-reference|review|skip|obsolete
  - tags (list[str]) — semantic tags
  - verdict_text (str) — one-line verdict explanation
  - takeaways (list[str]) — key bullet points (optional)
  - source (str) — instapaper|rss|chrome-reading|etc.
  - bookmark_id (int) — Instapaper bookmark ID (optional)
  - feed_name (str) — RSS feed name (optional)
  - feed_weight (float) — probationary weight from feeds.yaml; 0.6 for
    established feeds, 0.3 for probationary, 0.1 for demoted (optional)
  - date_saved (str) — YYYY-MM-DD (optional, defaults to today)

Output: JSON summary to stdout.
"""

import json
import os
import re
import sys
import urllib.parse
from datetime import date

import yaml

# --- Vault discovery ---

VAULT_PATHS = [
    os.path.expanduser("~/Obsidian"),
    os.path.expanduser("~/Documents/Obsidian"),
]


def find_vault():
    """Find the Obsidian vault that contains curaitor folders."""
    candidates = []
    config_path = os.path.expanduser("~/Library/Application Support/obsidian/obsidian.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        for v in config.get('vaults', {}).values():
            p = v.get('path', '')
            if os.path.isdir(p):
                candidates.append(p)
    candidates.extend(p for p in VAULT_PATHS if os.path.isdir(p))

    # Prefer the vault with the most curaitor folders
    curaitor_markers = ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']
    best, best_score = None, 0
    for p in candidates:
        score = sum(1 for m in curaitor_markers if os.path.isdir(os.path.join(p, m)))
        if score > best_score:
            best, best_score = p, score
    if best:
        return best
    if candidates:
        return candidates[0]
    print("Could not find Obsidian vault", file=sys.stderr)
    sys.exit(1)


# --- URL normalization ---
#
# Goal: collapse alternate URL forms of the same article to the same dedup key.
# The old behavior stripped ALL query params, which broke for URLs where the
# article id lives in the query string (e.g. YouTube `?v=...`, PubMed `?id=...`).
# The new behavior strips only known tracking params and applies per-host
# canonical rewrites for the heavy-hitter RSS sources (arxiv, biorxiv, medrxiv).

# Tracking query params to strip. Covers most analytics/referral juice.
_TRACKING_PARAMS = frozenset({
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_name', 'utm_reader', 'fbclid', 'gclid', 'msclkid',
    'mc_cid', 'mc_eid', 'ref', 'referrer', 'source', 'campaign',
    '_hsenc', '_hsmi', 'hsCtaTracking', 'hsa_acc', 'hsa_cam',
})

# arxiv path: optional 'abs' or 'pdf' segment, then the id with optional vN suffix
# and optional .pdf extension. Canonical form is /abs/<id> (no version, no ext).
_ARXIV_PATH = re.compile(
    r'^/(?:abs|pdf|html)/(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?(?:\.pdf)?/?$'
)

# biorxiv/medrxiv path: /content/10.1101/<id>[v<N>][.full[.pdf]]
# Canonical form is /content/10.1101/<id> (no version, no .full, no .pdf).
_BIORXIV_PATH = re.compile(
    r'^/content/(10\.1101/[\w\-\.]+?)(?:v\d+)?(?:\.full)?(?:\.pdf)?/?$'
)


def _canonicalize_host_path(host, path):
    """Apply per-host path rewrites to canonicalize alternate article URL forms."""
    # arxiv.org/abs/2404.12345 ≡ arxiv.org/pdf/2404.12345 ≡ arxiv.org/abs/2404.12345v2
    if host == 'arxiv.org':
        m = _ARXIV_PATH.match(path)
        if m:
            return f'/abs/{m.group(1)}'
    # biorxiv.org / medrxiv.org alternate forms
    if host in ('biorxiv.org', 'medrxiv.org'):
        m = _BIORXIV_PATH.match(path)
        if m:
            return f'/content/{m.group(1)}'
    return path


def normalize_url(url):
    url = url.strip()
    if not url:
        return url
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        # Malformed URL — fall back to naive lowercase+rstrip so we at least
        # don't crash the dedup pass.
        return url.rstrip('/').lower()

    host = parsed.netloc.lower()
    if host.startswith('www.'):
        host = host[4:]

    path = parsed.path or '/'
    path = _canonicalize_host_path(host, path)
    # Normalize trailing slash only on non-root paths.
    if len(path) > 1 and path.endswith('/'):
        path = path.rstrip('/')

    # Strip tracking params; keep everything else (YouTube ?v=, PubMed ?id=, …).
    if parsed.query:
        kept = [
            (k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in _TRACKING_PARAMS
        ]
        query = urllib.parse.urlencode(sorted(kept))  # sort for stable ordering
    else:
        query = ''

    # Drop scheme and fragment. host+path+query is the canonical dedup key.
    canonical = host + path
    if query:
        canonical += '?' + query
    return canonical.lower()


# --- Deduplication ---

# Matches Recycle.md lines: "- [title](url) ..." (url may be bare or surrounded by <>)
_RECYCLE_LINE = re.compile(r'^\s*-\s+\[[^\]]*\]\(\s*<?([^)\s>]+)>?\s*\)')

_FRONTMATTER_END = '---'
_URL_LINE = re.compile(r'^url:\s*(.+)$', re.MULTILINE)


def read_frontmatter_only(path):
    """Return the text up to (and including) the closing frontmatter `---`.

    Falls back to the first 500 bytes if no closing delimiter is found. Used
    by dedup to avoid reading the full note body — 5-20x I/O reduction on
    larger notes, which matters on Google-Drive-backed vaults.
    """
    try:
        with open(path, encoding='utf-8') as fh:
            first = fh.readline()
            if not first.startswith(_FRONTMATTER_END):
                return first  # no frontmatter; only the first line is header-ish
            buf = [first]
            for line in fh:
                buf.append(line)
                if line.startswith(_FRONTMATTER_END):
                    break
                if len(buf) > 200:  # pathological frontmatter; bail
                    break
            return ''.join(buf)
    except (OSError, UnicodeDecodeError):
        return ''


def _parse_recycle(recycle_path):
    """Return normalized URLs from a Curaitor/Recycle.md file."""
    urls = set()
    if not os.path.isfile(recycle_path):
        return urls
    try:
        with open(recycle_path, encoding='utf-8') as fh:
            for line in fh:
                m = _RECYCLE_LINE.match(line)
                if m:
                    urls.add(normalize_url(m.group(1)))
    except (OSError, UnicodeDecodeError):
        pass
    return urls


# Most-recent N recycle archives included in the dedup set. Bounds dedup
# scan cost as the Recycle archive grows month-over-month. Default 3;
# override via `recycle_archive_window` in user-settings.yaml — lower if
# dedup becomes a bottleneck, higher to catch older re-surfacings.
def _recycle_archive_window():
    try:
        import importlib.util
        mod_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recycle-rollover.py')
        spec = importlib.util.spec_from_file_location('_rr', mod_path)
        if spec is None or spec.loader is None:
            return 3
        rr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rr)
        return rr.load_archive_window()
    except Exception:
        return 3


def dedup_sources(vault):
    """Return the list of (kind, path) dedup should scan for a vault.

    Centralizes the "where do we look for known URLs?" policy. Callers walk
    the returned list instead of hardcoding folders.

    Returns a list of dicts:
      {'kind': 'folder', 'path': <abs dir>}      — walk .md notes, frontmatter only
      {'kind': 'recycle', 'path': <abs file>}    — parse Recycle.md-style lines
    """
    folders = [
        'Inbox', 'Review', 'Ignored', 'Library',
        'Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored',
        'Topics',
    ]
    sources = []
    for folder in folders:
        p = os.path.join(vault, folder)
        if os.path.isdir(p):
            sources.append({'kind': 'folder', 'path': p})

    # Live recycle log
    live_recycle = os.path.join(vault, 'Curaitor', 'Recycle.md')
    if os.path.isfile(live_recycle):
        sources.append({'kind': 'recycle', 'path': live_recycle})

    # Most-recent N monthly archives (Curaitor/Archive/Recycle-YYYY-MM.md)
    archive_dir = os.path.join(vault, 'Curaitor', 'Archive')
    if os.path.isdir(archive_dir):
        archives = sorted(
            (f for f in os.listdir(archive_dir) if f.startswith('Recycle-') and f.endswith('.md')),
            reverse=True,
        )
        for name in archives[:_recycle_archive_window()]:
            sources.append({'kind': 'recycle', 'path': os.path.join(archive_dir, name)})

    return sources


def build_url_index(vault):
    """Scan all dedup sources and build a set of normalized URLs.

    Includes live note folders, the live Recycle.md, and the most recent
    monthly recycle archives. See `dedup_sources()` for the canonical list.

    Uses `.curaitor/recycle-index.tsv` as a fast-path for the recycle portion
    when it exists and is in sync with the markdown sources. Falls back to
    line-by-line parse when the TSV is stale or missing.
    """
    known = set()
    # Try the recycle fast-path once for all recycle sources. If it hits, we
    # can skip per-file recycle parsing entirely.
    cached_recycle = _load_recycle_tsv(vault)
    for src in dedup_sources(vault):
        if src['kind'] == 'folder':
            for f in os.listdir(src['path']):
                if not f.endswith('.md') or f.startswith('.'):
                    continue
                head = read_frontmatter_only(os.path.join(src['path'], f))
                m = _URL_LINE.search(head)
                if m:
                    url = m.group(1).strip().strip('"').strip("'")
                    known.add(normalize_url(url))
        elif src['kind'] == 'recycle' and cached_recycle is None:
            # Only fall back to parsing markdown if the TSV wasn't usable.
            # If we took the fast-path, cached_recycle already includes every
            # recycle source's URLs (the TSV is built from the same file list).
            known |= _parse_recycle(src['path'])
    if cached_recycle is not None:
        known |= cached_recycle
    return known


_RECYCLE_TSV_REL = os.path.join('.curaitor', 'recycle-index.tsv')


def _recycle_tsv_path(vault):
    return os.path.join(vault, _RECYCLE_TSV_REL)


def _recycle_sources_checksum(vault):
    """SHA-256 over Recycle.md + archive files included in dedup. Must match
    the `_content_checksum` the reindex script writes, so keep it byte-exact.
    """
    import hashlib
    h = hashlib.sha256()
    for src in dedup_sources(vault):
        if src['kind'] != 'recycle':
            continue
        try:
            with open(src['path'], 'rb') as fh:
                h.update(fh.read())
        except OSError:
            h.update(b'__MISSING__')
    return h.hexdigest()


def _load_recycle_tsv(vault):
    """Load URLs from the TSV fast-path if it's valid.

    Returns a set of normalized URLs on success, or None if:
      - TSV doesn't exist
      - TSV header checksum doesn't match current Recycle.md + archives
      - TSV is malformed
    Callers fall back to the line-by-line markdown parse on None and
    schedule a background reindex so next run is fast.
    """
    path = _recycle_tsv_path(vault)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            first = fh.readline()
            if not first.startswith('# recycle-index v1 checksum='):
                return None
            stored_checksum = first.strip().split('checksum=', 1)[1]
            if stored_checksum != _recycle_sources_checksum(vault):
                return None  # markdown edited since last reindex; fall back
            header = fh.readline()  # consume "url_normalized\t..." header
            if not header.startswith('url_normalized\t'):
                return None
            urls = set()
            for line in fh:
                # First column is the normalized URL; tabs may appear in titles
                # (we strip them on write, but be defensive on read).
                tab = line.find('\t')
                if tab <= 0:
                    continue
                urls.add(line[:tab])
            return urls
    except (OSError, UnicodeDecodeError):
        return None


def _rebuild_recycle_tsv_in_background(vault):
    """Fire-and-forget background rebuild of the recycle TSV. Best-effort; a
    failed rebuild is harmless because the fallback path works without it.

    Runs async so a triage batch doesn't wait on the rebuild.
    """
    try:
        import subprocess
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recycle-reindex.py')
        if not os.path.isfile(script):
            return
        subprocess.Popen(
            ['python3', script, '--vault', vault],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, ImportError):
        pass  # best-effort


def build_recycle_index(vault):
    """Return the set of normalized URLs in Recycle.md + most-recent archives.

    Prefers the `.curaitor/recycle-index.tsv` fast-path when it exists and its
    checksum matches the live markdown sources. Falls back to the line-by-line
    markdown parse on a miss AND schedules a background rebuild so the next
    call hits the fast path. The fallback is always correct; the fast-path is
    just an optimization that scales as the Recycle log grows.

    See `scripts/recycle-reindex.py` for how the TSV is built / rebuilt.
    """
    cached = _load_recycle_tsv(vault)
    if cached is not None:
        return cached
    # Fallback: parse markdown sources. Also kick off a rebuild so next run
    # is fast (harmless if it races with another rebuilder; last-writer-wins
    # via atomic tmp+rename in recycle-reindex.py).
    _rebuild_recycle_tsv_in_background(vault)
    urls = set()
    for src in dedup_sources(vault):
        if src['kind'] == 'recycle':
            urls |= _parse_recycle(src['path'])
    return urls


def build_url_to_note_index(vault):
    """Map normalized URL → (folder_relpath, filename) for every live vault note.

    Used by the Instapaper-overrides-Ignored rescue path so we can locate the
    existing note and move it to Inbox without creating a duplicate. Only live
    note folders are indexed — Recycle.md entries are intentionally excluded
    (Recycle is authoritative: an Instapaper save over a recycled URL is dropped
    with a stderr warning, not un-recycled).
    """
    index = {}
    for src in dedup_sources(vault):
        if src['kind'] != 'folder':
            continue
        folder_rel = os.path.relpath(src['path'], vault)
        for f in os.listdir(src['path']):
            if not f.endswith('.md') or f.startswith('.'):
                continue
            head = read_frontmatter_only(os.path.join(src['path'], f))
            m = _URL_LINE.search(head)
            if not m:
                continue
            url = m.group(1).strip().strip('"').strip("'")
            norm = normalize_url(url)
            # First-match-wins. If the same URL appears in multiple folders
            # (shouldn't happen, but defensive), prefer whichever we see first.
            index.setdefault(norm, (folder_rel, f))
    return index


# --- Filename sanitization ---

def sanitize_filename(title, max_len=80):
    """Create a safe filename from an article title."""
    # Remove/replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', '', title)
    name = re.sub(r'[\n\r\t]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    # Truncate
    if len(name) > max_len:
        name = name[:max_len].rsplit(' ', 1)[0]
    return name


# --- Note construction ---

CONFIDENCE_TO_FOLDER = {
    'high-interested': 'Curaitor/Inbox',
    'uncertain': 'Curaitor/Review',
    'high-not-interested': 'Curaitor/Ignored',
}

VERDICT_LABELS = {
    'read-now': 'Read Now',
    'save-reference': 'Save Reference',
    'review': 'Review',
    'skip': 'Skip',
    'obsolete': 'Obsolete',
}


def build_note(article):
    """Construct frontmatter and markdown body from evaluation data."""
    today = date.today().isoformat()

    # Frontmatter
    fm = {
        'title': article['title'],
        'url': article['url'],
        'source': article.get('source', 'unknown'),
        'date_triaged': today,
        'category': article.get('category', 'general'),
        'confidence': article.get('confidence', 'uncertain'),
        'verdict': article.get('verdict', 'review'),
        'tags': article.get('tags', []),
    }
    if article.get('bookmark_id'):
        fm['bookmark_id'] = article['bookmark_id']
    if article.get('feed_name'):
        fm['feed_name'] = article['feed_name']
    if article.get('feed_weight') is not None:
        fm['feed_weight'] = article['feed_weight']
    if article.get('date_saved'):
        fm['date_saved'] = article['date_saved']
    if article.get('autonomy_level') is not None:
        fm['autonomy_level'] = article['autonomy_level']
    if article.get('media_type'):
        fm['media_type'] = article['media_type']
    if article.get('triage_source'):
        fm['triage_source'] = article['triage_source']
    if article.get('local_model'):
        fm['local_model'] = article['local_model']
    if article.get('slop_label'):
        fm['slop_label'] = article['slop_label']

    # Body
    parts = []
    summary = article.get('summary', '')
    if summary:
        parts.append(f"## Summary\n{summary}")

    verdict_text = article.get('verdict_text', '')
    verdict_label = VERDICT_LABELS.get(article.get('verdict', ''), article.get('verdict', 'Review'))
    if verdict_text:
        parts.append(f"## Verdict: {verdict_label}\n{verdict_text}")

    takeaways = article.get('takeaways', [])
    if takeaways:
        bullets = '\n'.join(f'- {t}' for t in takeaways)
        parts.append(f"## Key takeaways\n{bullets}")

    body = '\n\n'.join(parts)
    return fm, body


def write_note(vault, folder, filename, frontmatter, body):
    """Write note to vault."""
    path = os.path.join(vault, folder, f"{filename}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    parts = ['---']
    parts.append(yaml.dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True).strip())
    parts.append('---')
    parts.append('')
    parts.append(body)

    with open(path, 'w') as f:
        f.write('\n'.join(parts))
    return os.path.relpath(path, vault)


# --- Main ---

def _pregenerate_summaries(urls):
    """Pre-generate summaries for freshly-added Inbox articles.

    Runs scripts/summarize-inbox.py --one-url for each URL. Failures are
    tolerated — pre-generation is an optimization; a miss just means
    /curaitor:read will hit the inline fallback.

    Returns a dict with per-URL status for the triage output JSON.
    """
    import subprocess
    this_dir = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(this_dir, 'summarize-inbox.py')
    if not os.path.isfile(script):
        return {'status': 'script-missing', 'queued': len(urls)}

    per_url = {}
    for url in urls:
        try:
            proc = subprocess.run(
                ['python3', script, '--one-url', url],
                capture_output=True, text=True, timeout=180,
            )
            try:
                per_url[url] = json.loads(proc.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                per_url[url] = {'status': 'unparseable', 'info': (proc.stderr or '')[:200]}
        except subprocess.TimeoutExpired:
            per_url[url] = {'status': 'timeout'}
        except (OSError, subprocess.SubprocessError) as e:
            per_url[url] = {'status': 'error', 'info': str(e)}
    return per_url


def maybe_rollover_recycle(vault):
    """Best-effort auto-rotation of Recycle.md when it crosses the threshold.

    Runs before dedup scans so the live file stays small and the archive
    picks up the old entries (dedup_sources() also scans recent archives
    so coverage is preserved).

    Silent on all failures — rollover is an optimization, not a hard
    requirement for triage correctness.
    """
    try:
        import importlib.util
        mod_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recycle-rollover.py')
        spec = importlib.util.spec_from_file_location('_rr', mod_path)
        if spec is None or spec.loader is None:
            return
        rr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rr)
        threshold = rr.load_threshold()
        if rr.needs_rotation(os.path.join(vault, 'Curaitor', 'Recycle.md'), threshold):
            result = rr.rotate(vault, threshold, apply=True)
            if result.get('rotated'):
                print(f"Recycle.md rolled over to {result['archive_path']}", file=sys.stderr)
    except Exception:
        pass


def _rescue_note_ignored_to_inbox(old_path, new_path, article):
    """Move an Ignored note to Inbox, stamping provenance in the frontmatter.

    Rewrites the note's YAML frontmatter to:
      - set `source: instapaper` (the rescue trigger)
      - set `rescued_from_ignored: true` + `rescued_at: <today>`
      - leave all other fields (title, url, summary, date_saved, etc.) intact

    Body is preserved. The old file is unlinked atomically after the new
    file is written, so a mid-run crash leaves at most the original note in
    place (worst case: we retry and rescue again, which is idempotent).
    """
    with open(old_path, encoding='utf-8') as f:
        content = f.read()
    # Parse frontmatter block. Note must start with `---` per our write_note
    # contract; if it doesn't we fall back to writing an empty frontmatter.
    fm_data = {}
    body = content
    if content.startswith('---\n'):
        end = content.find('\n---', 4)
        if end != -1:
            fm_text = content[4:end]
            body = content[end + len('\n---'):].lstrip('\n')
            try:
                fm_data = yaml.safe_load(fm_text) or {}
            except yaml.YAMLError:
                fm_data = {}
    # Apply rescue overrides.
    fm_data['source'] = 'instapaper'
    fm_data['rescued_from_ignored'] = True
    fm_data['rescued_at'] = date.today().isoformat()
    # Overwrite the old (now stale) classification so future dedup / routing
    # passes don't confuse an Inbox note with a "high-not-interested" verdict.
    # Preserve the prior values under `prior_*` keys so the audit trail survives.
    for key in ('confidence', 'verdict', 'category'):
        if key in fm_data:
            fm_data[f'prior_{key}'] = fm_data[key]
    # Fresh classification — Instapaper saves are explicit user interest and
    # the note lands in Inbox, so `high-interested` / `save-reference` is the
    # correct default. Callers can still override via the incoming article.
    fm_data['confidence'] = article.get('confidence', 'high-interested')
    fm_data['verdict'] = article.get('verdict', 'save-reference')
    if article.get('category'):
        fm_data['category'] = article['category']
    # If the incoming bookmark has a bookmark_id, stamp it too (useful for later
    # cross-reference against Instapaper archive events).
    if article.get('bookmark_id'):
        fm_data['bookmark_id'] = article['bookmark_id']
    # Reserialize.
    parts = ['---']
    parts.append(yaml.dump(fm_data, default_flow_style=False, sort_keys=False, allow_unicode=True).strip())
    parts.append('---')
    parts.append('')
    parts.append(body)
    with open(new_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(parts))
    # Unlink the old copy. If new_path == old_path (shouldn't happen given we
    # moved folders) this would blow away our write; guard anyway.
    if os.path.abspath(new_path) != os.path.abspath(old_path):
        try:
            os.remove(old_path)
        except OSError:
            pass  # best-effort; the new Inbox note is authoritative now


def cmd_write(args):
    """Write triage results to Obsidian."""
    vault = find_vault()
    maybe_rollover_recycle(vault)
    recycled_urls = build_recycle_index(vault)
    known_urls = build_url_index(vault)  # includes recycled + vault notes
    # URL → (folder_relpath, filename) for every live vault note. Needed by
    # the Instapaper-overrides-Ignored rescue path; built once up front so
    # the per-article loop stays cheap.
    url_to_note = build_url_to_note_index(vault)

    articles = json.load(sys.stdin)
    if not isinstance(articles, list):
        articles = [articles]

    written = 0
    recycled_dup_note = 0
    recycled_dup_recycle = 0
    rescued_from_ignored = 0
    instapaper_dropped_recycle = 0
    skipped_nourl = 0
    errors = 0
    results = {'inbox': [], 'review': [], 'ignored': []}
    inbox_urls_for_summary = []
    rescued_urls = []  # URLs we moved Ignored → Inbox (caller should archive in Instapaper)

    # Recycle file for duplicates
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    os.makedirs(os.path.dirname(recycle_path), exist_ok=True)

    for article in articles:
        url = article.get('url', '').strip()
        if not url or url in ('>-', '-'):
            skipped_nourl += 1
            continue

        norm = normalize_url(url)
        if norm in known_urls:
            source = (article.get('source') or '').lower()
            title = article.get('title', url)
            from_recycle = norm in recycled_urls
            existing_note = url_to_note.get(norm)  # (folder_rel, filename) or None

            # Instapaper-overrides-Ignored rescue path. An Instapaper save is
            # explicit user intent ("I want to read this"). If the URL is sitting
            # in Curaitor/Ignored/ from a prior RSS-era routing decision, honor
            # the fresh Instapaper signal by moving the note to Inbox rather
            # than dropping the save or re-recycling it. See memory file
            # feedback_instapaper_overrides_rss.md for the 2026-05-10 incident
            # this fixes.
            if source == 'instapaper' and existing_note and existing_note[0].endswith('Ignored'):
                folder_rel, filename = existing_note
                old_path = os.path.join(vault, folder_rel, filename)
                new_folder = 'Curaitor/Inbox'
                new_path = os.path.join(vault, new_folder, filename)
                try:
                    os.makedirs(os.path.dirname(new_path), exist_ok=True)
                    _rescue_note_ignored_to_inbox(old_path, new_path, article)
                except (OSError, ValueError) as e:
                    print(f"Error rescuing {title}: {e}", file=sys.stderr)
                    errors += 1
                    continue
                rescued_from_ignored += 1
                rescued_urls.append(url)
                results['inbox'].append(title)
                # The URL is still in known_urls from the pre-scan so no
                # intra-batch re-rescue is possible. No Recycle line written.
                continue

            # Instapaper save but URL is in Recycle (no live note). Recycle is
            # authoritative ("user definitively rejected this previously"); drop
            # the save with a stderr warning so the caller knows not to create
            # a note. Caller should still archive the bookmark in Instapaper so
            # it doesn't reappear next cron.
            if source == 'instapaper' and from_recycle:
                print(
                    f"WARN: Instapaper save dropped — URL is in Recycle: {url}",
                    file=sys.stderr,
                )
                instapaper_dropped_recycle += 1
                continue

            # Default dedup path (RSS hit, or Instapaper hit against Inbox/Review
            # which we leave alone): append one Recycle line if not already
            # recorded. Do NOT create a note.
            tag = '(duplicate from Recycle)' if from_recycle else '(duplicate)'
            if not from_recycle:
                with open(recycle_path, 'a', encoding='utf-8') as rf:
                    rf.write(f"- [{title}]({url}) {tag}\n")
                recycled_urls.add(norm)  # prevent intra-batch re-appends
            if from_recycle:
                recycled_dup_recycle += 1
            else:
                recycled_dup_note += 1
            continue

        try:
            fm, body = build_note(article)
            confidence = article.get('confidence', 'uncertain')
            folder = CONFIDENCE_TO_FOLDER.get(confidence, 'Curaitor/Review')
            filename = sanitize_filename(article['title'])
            write_note(vault, folder, filename, fm, body)
            known_urls.add(norm)  # prevent self-duplicates within batch
            written += 1

            bucket = folder.split('/')[-1].lower()
            results[bucket].append(article['title'])

            # Queue for summary pre-generation if the article lands in Inbox.
            # Note: we queue instead of call inline so cmd_write stays snappy —
            # each summary call is ~6s and we don't want triage blocked on it.
            if args.generate_summaries and folder == 'Curaitor/Inbox':
                inbox_urls_for_summary.append(article['url'])
        except Exception as e:
            print(f"Error writing {article.get('title', '?')}: {e}", file=sys.stderr)
            errors += 1

    output = {
        'vault': vault,
        'written': written,
        'recycled_duplicate': recycled_dup_note + recycled_dup_recycle,
        'recycled_duplicate_from_note': recycled_dup_note,
        'recycled_duplicate_from_recycle': recycled_dup_recycle,
        'rescued_from_ignored': rescued_from_ignored,
        'rescued_urls': rescued_urls,
        'instapaper_dropped_recycle': instapaper_dropped_recycle,
        'skipped_no_url': skipped_nourl,
        'errors': errors,
        'total_input': len(articles),
        'routing': {k: len(v) for k, v in results.items()},
    }
    if args.generate_summaries and inbox_urls_for_summary:
        output['summary_queue'] = _pregenerate_summaries(inbox_urls_for_summary)
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)


def cmd_dedup(args):
    """Check which URLs already exist in the vault or Recycle.md."""
    vault = find_vault()
    recycled_urls = build_recycle_index(vault)
    known_urls = build_url_index(vault)  # includes recycled

    # Collect input URLs
    if args.urls_file:
        with open(args.urls_file) as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    elif args.urls:
        urls = args.urls
    else:
        urls = [line.strip() for line in sys.stdin if line.strip()]

    new_urls = []
    dup_note_urls = []
    dup_recycle_urls = []
    for url in urls:
        norm = normalize_url(url)
        if norm in recycled_urls:
            dup_recycle_urls.append(url)
        elif norm in known_urls:
            dup_note_urls.append(url)
        else:
            new_urls.append(url)

    output = {
        'total': len(urls),
        'new': len(new_urls),
        'duplicate': len(dup_note_urls) + len(dup_recycle_urls),
        'duplicate_from_note': len(dup_note_urls),
        'duplicate_from_recycle': len(dup_recycle_urls),
        'new_urls': new_urls,
    }
    json.dump(output, sys.stdout, indent=2)
    print(file=sys.stdout)
    print(
        f"{len(new_urls)} new, "
        f"{len(dup_note_urls)} duplicates (existing notes), "
        f"{len(dup_recycle_urls)} duplicates (from Recycle.md), "
        f"out of {len(urls)}",
        file=sys.stderr,
    )


def cmd_add_to_recycle(args):
    """Append a single entry to Curaitor/Recycle.md, skipping if the URL is
    already recorded there or in an archived Recycle-YYYY-MM.md.

    This is the dedup-safe replacement for the review/read skills' manual
    `mcp__obsidian__write_note --mode append` pattern, which had no awareness
    of existing entries and produced duplicates like the 2026-04-26 session's
    double-append of the direct-RNA paper.

    Exits 0 and prints a JSON status line on both the "appended" and "skipped"
    paths — callers should parse the JSON, not rely on exit codes alone.
    """
    vault = find_vault()
    url = (args.url or '').strip()
    title = (args.title or '').strip() or url
    if not url:
        print(json.dumps({'status': 'error', 'error': 'missing --url'}))
        sys.exit(2)

    norm = normalize_url(url)
    recycled_urls = build_recycle_index(vault)
    if norm in recycled_urls:
        print(json.dumps({
            'status': 'skipped',
            'reason': 'already in recycle (live or archive)',
            'url': url,
            'normalized': norm,
        }))
        return

    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    os.makedirs(os.path.dirname(recycle_path), exist_ok=True)
    line = f"- [{title}]({url})"
    if args.tag:
        line += f" {args.tag}"
    line += '\n'
    with open(recycle_path, 'a', encoding='utf-8') as rf:
        rf.write(line)
    print(json.dumps({
        'status': 'appended',
        'recycle_path': recycle_path,
        'url': url,
        'normalized': norm,
    }))


_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'user-settings.yaml'
)


def _load_settings():
    if not os.path.isfile(_SETTINGS_PATH):
        return {}
    try:
        with open(_SETTINGS_PATH) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _topic_roots():
    """Obsidian topic folders to scan. Configurable via
    user-settings.yaml:topic_roots; defaults to the two historical locations.
    """
    roots = (_load_settings() or {}).get('topic_roots')
    if isinstance(roots, list) and roots:
        return [str(r) for r in roots]
    return ['Personal/Topics', 'Topics']


def _extract_urls(text):
    """Return normalized URLs found in `text`. Matches Obsidian `[t](url)`
    markdown links and bare URLs.
    """
    url_pat = re.compile(r'https?://[^\s)\]<>"]+', re.IGNORECASE)
    return {normalize_url(m.group(0).rstrip(').,;:')) for m in url_pat.finditer(text)}


def _urls_in_section(content, heading):
    """Return normalized URLs found under a specific `## Heading` section of a
    markdown file. Scan stops at the next heading of equal or higher level.
    """
    if not heading:
        return _extract_urls(content)
    # Find the heading line (loose match — "## Related Articles" matches any hash level)
    pat = re.compile(r'^(#+)\s+' + re.escape(heading) + r'\s*$', re.MULTILINE)
    m = pat.search(content)
    if not m:
        return set()
    start_level = len(m.group(1))
    start = m.end()
    # Find the next heading at or above start_level
    rest = content[start:]
    end_pat = re.compile(r'^(#{1,' + str(start_level) + r'})\s+\S', re.MULTILINE)
    end_m = end_pat.search(rest)
    section = rest if not end_m else rest[:end_m.start()]
    return _extract_urls(section)


def cmd_attach_to_topic(args):
    """Append a `[title](url)` link under a heading in a Topic note, skipping
    if the URL is already linked anywhere in that section.

    Dedup-safe replacement for the skills' bare `mcp__obsidian__patch_note`
    pattern that doesn't check for existing links. Mirrors --add-to-recycle's
    JSON-status contract.

    Looks up the topic file by matching `<topic>.md` under each path in
    user-settings.yaml:topic_roots (defaults: Personal/Topics, Topics). If
    multiple match, the first found wins. If none match, --create-if-missing
    picks the first topic_root.
    """
    vault = find_vault()
    url = (args.url or '').strip()
    title = (args.title or '').strip() or url
    topic = (args.topic or '').strip()
    section = (args.section or 'Related Articles').strip()
    if not url or not topic:
        print(json.dumps({'status': 'error', 'error': 'need --url and --topic'}))
        sys.exit(2)

    # Locate the topic file
    topic_file = f'{topic}.md'
    topic_path = None
    roots = _topic_roots()
    for root in roots:
        candidate = os.path.join(vault, root, topic_file)
        if os.path.isfile(candidate):
            topic_path = candidate
            break
    if topic_path is None:
        if not args.create_if_missing:
            print(json.dumps({
                'status': 'error',
                'error': 'topic not found',
                'topic': topic,
                'searched': roots,
            }))
            sys.exit(1)
        topic_path = os.path.join(vault, roots[0], topic_file)
        os.makedirs(os.path.dirname(topic_path), exist_ok=True)
        with open(topic_path, 'w', encoding='utf-8') as f:
            f.write(f'# {topic}\n\n## {section}\n\n')

    with open(topic_path, encoding='utf-8') as f:
        content = f.read()

    norm = normalize_url(url)
    existing = _urls_in_section(content, section)
    if norm in existing:
        print(json.dumps({
            'status': 'skipped',
            'reason': f'already linked under ## {section}',
            'topic_path': os.path.relpath(topic_path, vault),
            'url': url,
        }))
        return

    # Find the section heading; append under it. If section missing, append at EOF.
    heading_pat = re.compile(r'^(#+)\s+' + re.escape(section) + r'\s*$', re.MULTILINE)
    m = heading_pat.search(content)
    new_entry = f'- [{title}]({url})'
    if args.description:
        new_entry += f' — {args.description}'
    new_entry += '\n'

    if not m:
        # Append section + entry
        if not content.endswith('\n'):
            content += '\n'
        content += f'\n## {section}\n\n{new_entry}'
    else:
        # Insert directly after the heading line (and any immediately-following blank line)
        insert_at = m.end()
        if insert_at < len(content) and content[insert_at] == '\n':
            insert_at += 1
        if insert_at < len(content) and content[insert_at] == '\n':
            insert_at += 1
        content = content[:insert_at] + new_entry + content[insert_at:]

    with open(topic_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(json.dumps({
        'status': 'appended',
        'topic_path': os.path.relpath(topic_path, vault),
        'section': section,
        'url': url,
    }))


def cmd_add_to_catalog(args):
    """Append an entry to a vault-root catalog file (Tools & Projects.md,
    Bookmarks.md, or any other). Skips if the URL already appears under the
    target category (or anywhere in the file if --category is omitted).

    Used by the /curaitor:review and /curaitor:read `c` (Clip) and `b` (Bookmark)
    verdicts. Mirrors --add-to-recycle's JSON-status contract.
    """
    vault = find_vault()
    url = (args.url or '').strip()
    title = (args.title or '').strip() or url
    catalog = (args.catalog or '').strip()
    category = (args.category or '').strip() or None
    description = (args.description or '').strip() or None
    if not url or not catalog:
        print(json.dumps({'status': 'error', 'error': 'need --url and --catalog'}))
        sys.exit(2)

    catalog_path = os.path.join(vault, catalog)
    if not os.path.isfile(catalog_path):
        if not args.create_if_missing:
            print(json.dumps({
                'status': 'error',
                'error': 'catalog not found',
                'catalog_path': catalog_path,
            }))
            sys.exit(1)
        with open(catalog_path, 'w', encoding='utf-8') as f:
            f.write(f'# {os.path.splitext(os.path.basename(catalog))[0]}\n\n')

    with open(catalog_path, encoding='utf-8') as f:
        content = f.read()

    norm = normalize_url(url)
    existing = _urls_in_section(content, category) if category else _extract_urls(content)
    if norm in existing:
        print(json.dumps({
            'status': 'skipped',
            'reason': f'already in {category or "file"}',
            'catalog_path': os.path.relpath(catalog_path, vault),
            'url': url,
        }))
        return

    new_entry = f'- [{title}]({url})'
    if description:
        new_entry += f' — {description}'
    new_entry += '\n'

    if category:
        heading_pat = re.compile(r'^(#+)\s+' + re.escape(category) + r'\s*$', re.MULTILINE)
        m = heading_pat.search(content)
        if not m:
            if not content.endswith('\n'):
                content += '\n'
            content += f'\n## {category}\n\n{new_entry}'
        else:
            insert_at = m.end()
            if insert_at < len(content) and content[insert_at] == '\n':
                insert_at += 1
            if insert_at < len(content) and content[insert_at] == '\n':
                insert_at += 1
            content = content[:insert_at] + new_entry + content[insert_at:]
    else:
        if not content.endswith('\n'):
            content += '\n'
        content += new_entry

    with open(catalog_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print(json.dumps({
        'status': 'appended',
        'catalog_path': os.path.relpath(catalog_path, vault),
        'category': category,
        'url': url,
    }))


def cmd_find_leftovers(args):
    """Scan Curaitor/Inbox and Curaitor/Review for notes whose URL is already
    present in a Topic note (Personal/Topics/*.md or Topics/*.md), the
    Tools & Projects catalog, or the Bookmarks list.

    These are "leftover" Inbox/Review notes — the user already made a
    disposition decision (attached to topic, clipped to Tools, bookmarked)
    but the source note wasn't deleted afterward. The /curaitor:review and
    /curaitor:read skills should delete the source note after every t/c/b verdict,
    but manual-edit paths and some past versions didn't.

    Prints JSON listing each leftover with the topic/catalog it's already in.
    Safe to run at the start of every interactive session as a pre-flight.
    """
    del args  # unused; kept for dispatch-signature consistency
    vault = find_vault()
    # Gather URLs from topics / tools / bookmarks, keyed so we can report where
    # the match came from.
    curated_sources = []
    for folder in _topic_roots():
        p = os.path.join(vault, folder)
        if os.path.isdir(p):
            curated_sources.append(('topic', folder, p))
    for catalog_name in ('Tools & Projects.md', 'Bookmarks.md'):
        p = os.path.join(vault, catalog_name)
        if os.path.isfile(p):
            curated_sources.append(('catalog', catalog_name, p))

    # URL-in-content regex: matches Obsidian markdown links [text](url) and
    # bare URLs. We only need the URL; titles are captured separately.
    url_pat = re.compile(r'https?://[^\s)\]<>"]+', re.IGNORECASE)

    url_to_source = {}  # norm_url -> [(kind, name, file_rel, raw_url), ...]
    for kind, name, path in curated_sources:
        files = []
        if os.path.isdir(path):
            for root, _, names in os.walk(path):
                for f in names:
                    if f.endswith('.md') and not f.startswith('.'):
                        files.append(os.path.join(root, f))
        else:
            files.append(path)
        for fpath in files:
            try:
                with open(fpath, encoding='utf-8') as fh:
                    content = fh.read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in url_pat.finditer(content):
                raw = m.group(0).rstrip(').,;:')
                norm = normalize_url(raw)
                url_to_source.setdefault(norm, []).append({
                    'kind': kind,
                    'name': name,
                    'file': os.path.relpath(fpath, vault),
                    'raw_url': raw,
                })

    # Now walk Inbox/Review and check each note's frontmatter URL.
    leftovers = []
    scan_folders = ['Curaitor/Inbox', 'Curaitor/Review']
    for folder in scan_folders:
        p = os.path.join(vault, folder)
        if not os.path.isdir(p):
            continue
        for f in sorted(os.listdir(p)):
            if not f.endswith('.md') or f.startswith('.'):
                continue
            note_path = os.path.join(p, f)
            head = read_frontmatter_only(note_path)
            urlm = _URL_LINE.search(head)
            if not urlm:
                continue
            raw_note_url = urlm.group(1).strip().strip('"').strip("'")
            norm = normalize_url(raw_note_url)
            if norm in url_to_source:
                leftovers.append({
                    'note': os.path.relpath(note_path, vault),
                    'url': raw_note_url,
                    'normalized': norm,
                    'matches': url_to_source[norm],
                })

    json.dump({
        'vault': vault,
        'scanned_folders': scan_folders,
        'curated_sources': [{'kind': k, 'name': n} for (k, n, _) in curated_sources],
        'leftover_count': len(leftovers),
        'leftovers': leftovers,
    }, sys.stdout, indent=2)
    print(file=sys.stdout)


def cmd_stamp_reviewed(args):
    """Mark an Inbox note as 'previously reviewed and kept'.

    Finds the note in Curaitor/Inbox/ whose frontmatter `url` matches
    --url, then rewrites its frontmatter to add:
      - review_status: kept-after-review
      - reviewed_at: <YYYY-MM-DD> (latest review date; overwrites on each call)
      - reviewed_count: N (incremented on each stamp — so we can distinguish
        a note reviewed once from one reviewed repeatedly)

    Body is preserved verbatim. Idempotent — calling twice in the same day
    just bumps the count.

    Used by /curaitor:read's `skip` verdict and /curaitor:review's `y`/`r` verdicts to
    flag articles the user explicitly chose to keep in Inbox after seeing
    them. /curaitor:read's startup then surfaces these in a "Previously reviewed"
    section so the user can distinguish fresh arrivals from items they've
    already seen once.

    Prints JSON status: {status: stamped|not-found|error, ...}.
    """
    vault = find_vault()
    url = (args.url or '').strip()
    if not url:
        print(json.dumps({'status': 'error', 'error': 'missing --url'}))
        sys.exit(2)

    norm = normalize_url(url)
    inbox_dir = os.path.join(vault, 'Curaitor', 'Inbox')
    if not os.path.isdir(inbox_dir):
        print(json.dumps({'status': 'error', 'error': f'Inbox dir not found: {inbox_dir}'}))
        sys.exit(1)

    match_path = None
    for f in os.listdir(inbox_dir):
        if not f.endswith('.md') or f.startswith('.'):
            continue
        p = os.path.join(inbox_dir, f)
        head = read_frontmatter_only(p)
        m = _URL_LINE.search(head)
        if not m:
            continue
        note_url = m.group(1).strip().strip('"').strip("'")
        if normalize_url(note_url) == norm:
            match_path = p
            break

    if match_path is None:
        print(json.dumps({
            'status': 'not-found',
            'url': url,
            'normalized': norm,
            'hint': 'URL not in Curaitor/Inbox/',
        }))
        return

    # Parse + rewrite frontmatter. Same atomic-tmp+replace approach used by
    # the rescue path and cmd_dedup_recycle.
    with open(match_path, encoding='utf-8') as fh:
        content = fh.read()
    if not content.startswith('---\n'):
        print(json.dumps({
            'status': 'error',
            'error': 'note has no YAML frontmatter',
            'path': os.path.relpath(match_path, vault),
        }))
        sys.exit(1)
    end = content.find('\n---', 4)
    if end == -1:
        print(json.dumps({
            'status': 'error',
            'error': 'unterminated frontmatter',
            'path': os.path.relpath(match_path, vault),
        }))
        sys.exit(1)
    fm_text = content[4:end]
    body = content[end + len('\n---'):].lstrip('\n')
    try:
        fm_data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        print(json.dumps({
            'status': 'error', 'error': f'yaml parse: {e}',
            'path': os.path.relpath(match_path, vault),
        }))
        sys.exit(1)

    fm_data['review_status'] = 'kept-after-review'
    fm_data['reviewed_at'] = date.today().isoformat()
    fm_data['reviewed_count'] = int(fm_data.get('reviewed_count') or 0) + 1

    new_fm = yaml.dump(fm_data, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
    new_content = '---\n' + new_fm + '\n---\n\n' + body
    tmp = match_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.write(new_content)
    os.replace(tmp, match_path)

    print(json.dumps({
        'status': 'stamped',
        'path': os.path.relpath(match_path, vault),
        'reviewed_count': fm_data['reviewed_count'],
        'reviewed_at': fm_data['reviewed_at'],
    }))


def cmd_list_reviewed(args):
    """List Inbox notes with review_status: kept-after-review.

    Used by /curaitor:read's startup to surface previously-reviewed articles in a
    distinct section before the fresh-arrivals queue. Returns JSON array,
    sorted by reviewed_at descending (most-recently-re-reviewed first).
    """
    del args  # unused; kept for dispatch-signature consistency
    vault = find_vault()
    inbox_dir = os.path.join(vault, 'Curaitor', 'Inbox')
    if not os.path.isdir(inbox_dir):
        json.dump({'vault': vault, 'reviewed': []}, sys.stdout)
        sys.stdout.write('\n')
        return

    reviewed = []
    for f in sorted(os.listdir(inbox_dir)):
        if not f.endswith('.md') or f.startswith('.'):
            continue
        p = os.path.join(inbox_dir, f)
        head = read_frontmatter_only(p)
        # Simple check first — avoid YAML parse for the vast majority of notes
        # that haven't been reviewed.
        if 'review_status: kept-after-review' not in head:
            continue
        try:
            # Extract frontmatter YAML for the full details.
            if not head.startswith('---\n'):
                continue
            end = head.find('\n---', 4)
            if end == -1:
                continue
            fm = yaml.safe_load(head[4:end]) or {}
        except yaml.YAMLError:
            continue
        if fm.get('review_status') != 'kept-after-review':
            continue
        reviewed.append({
            'path': os.path.relpath(p, vault),
            'title': fm.get('title', ''),
            'url': fm.get('url', ''),
            'reviewed_at': str(fm.get('reviewed_at', '')),
            'reviewed_count': int(fm.get('reviewed_count') or 1),
            'category': fm.get('category', ''),
            'tags': fm.get('tags', []),
        })

    reviewed.sort(key=lambda r: r['reviewed_at'], reverse=True)
    json.dump({
        'vault': vault,
        'count': len(reviewed),
        'reviewed': reviewed,
    }, sys.stdout, indent=2)
    sys.stdout.write('\n')


def cmd_dedup_recycle(args):
    """Collapse duplicate lines in Curaitor/Recycle.md by normalized URL.

    Accumulating duplicate recycle lines breaks `patch_note` disambiguation
    (one URL with 5 entries can't be edited cleanly). Run this when the file
    gets messy. Idempotent and safe to re-run.
    """
    vault = find_vault()
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    if not os.path.isfile(recycle_path):
        print(f"No Recycle.md at {recycle_path}", file=sys.stderr)
        return

    with open(recycle_path, encoding='utf-8') as fh:
        original = fh.readlines()

    seen = set()
    kept = []
    dropped = 0
    non_entry_lines = 0
    for line in original:
        m = _RECYCLE_LINE.match(line)
        if not m:
            # Non-entry line (heading, blank, freeform note) — keep verbatim
            kept.append(line)
            non_entry_lines += 1
            continue
        norm = normalize_url(m.group(1))
        if norm in seen:
            dropped += 1
            continue
        seen.add(norm)
        kept.append(line)

    if args.dry_run:
        print(json.dumps({
            'vault': vault,
            'recycle_path': recycle_path,
            'total_lines': len(original),
            'entry_lines': len(original) - non_entry_lines,
            'unique_urls': len(seen),
            'would_drop': dropped,
        }, indent=2))
        return

    if dropped == 0:
        print(f"Recycle.md already dedup'd ({len(seen)} unique URLs)", file=sys.stderr)
        return

    # Write-replace with atomic-ish swap via a temp file
    tmp = recycle_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        fh.writelines(kept)
    os.replace(tmp, recycle_path)

    print(json.dumps({
        'vault': vault,
        'recycle_path': recycle_path,
        'before_lines': len(original),
        'after_lines': len(kept),
        'dropped': dropped,
        'unique_urls': len(seen),
    }, indent=2))


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Write triage results to Obsidian')
    parser.add_argument('--dedup-only', action='store_true',
                        help='Only check for duplicates, do not write notes')
    parser.add_argument('--dedup-recycle', action='store_true',
                        help='Collapse duplicate lines in Curaitor/Recycle.md (one-time cleanup)')
    parser.add_argument('--add-to-recycle', action='store_true',
                        help='Append a single entry to Curaitor/Recycle.md, skipping if '
                             'the URL is already present in the live file or recent archives. '
                             'Requires --url; --title and --tag optional.')
    parser.add_argument('--find-leftovers', action='store_true',
                        help='Scan Inbox/Review for notes whose URL is already present '
                             'in a Topic note, Tools & Projects, or Bookmarks.md. These '
                             'indicate a missed delete after a t/c/b verdict.')
    parser.add_argument('--stamp-reviewed', action='store_true',
                        help='Find the Inbox note matching --url and mark its frontmatter '
                             'with review_status: kept-after-review, reviewed_at, and '
                             'incremented reviewed_count. Used by /curaitor:read skip and '
                             '/curaitor:review y/r verdicts to flag "previously reviewed" notes.')
    parser.add_argument('--list-reviewed', action='store_true',
                        help='List Inbox notes with review_status: kept-after-review, '
                             'sorted by reviewed_at descending. Used by /curaitor:read startup.')
    parser.add_argument('--attach-to-topic', action='store_true',
                        help='Append a [title](url) link under a heading in a Topic note, '
                             'skipping if the URL is already linked there. '
                             'Requires --url and --topic; --title, --section, --description, '
                             '--create-if-missing optional.')
    parser.add_argument('--add-to-catalog', action='store_true',
                        help='Append a [title](url) line to a vault-root catalog file '
                             '(Tools & Projects.md, Bookmarks.md, etc.), skipping if the URL '
                             'is already listed. Requires --url and --catalog; --category, '
                             '--title, --description, --create-if-missing optional.')
    parser.add_argument('--url', help='URL (used with --add-to-recycle / --attach-to-topic / --add-to-catalog)')
    parser.add_argument('--title', help='Link title (used with the append commands)')
    parser.add_argument('--tag', help='Optional suffix tag like "(duplicate)" (used with --add-to-recycle)')
    parser.add_argument('--topic', help='Topic name without .md (used with --attach-to-topic)')
    parser.add_argument('--section', help='Section heading in the topic (default "Related Articles")')
    parser.add_argument('--catalog', help='Catalog filename relative to vault root (used with --add-to-catalog)')
    parser.add_argument('--category', help='Section heading within the catalog (used with --add-to-catalog)')
    parser.add_argument('--description', help='Optional " — description" suffix on the appended line')
    parser.add_argument('--create-if-missing', action='store_true',
                        help='Create the topic or catalog file if it does not exist')
    parser.add_argument('--dry-run', action='store_true',
                        help='With --dedup-recycle: report without modifying the file')
    parser.add_argument('--urls', nargs='+', help='URLs to check (dedup mode)')
    parser.add_argument('--urls-file', help='File with URLs (dedup mode)')
    parser.add_argument('--generate-summaries', action='store_true',
                        help='After writing Inbox notes, pre-generate their summaries '
                             'into the cache (calls summarize-inbox.py --one-url per URL). '
                             'Intended for cron use; adds ~6s per Inbox-bound article.')
    args = parser.parse_args()

    if args.dedup_recycle:
        cmd_dedup_recycle(args)
    elif args.add_to_recycle:
        cmd_add_to_recycle(args)
    elif args.attach_to_topic:
        cmd_attach_to_topic(args)
    elif args.add_to_catalog:
        cmd_add_to_catalog(args)
    elif args.find_leftovers:
        cmd_find_leftovers(args)
    elif args.stamp_reviewed:
        cmd_stamp_reviewed(args)
    elif args.list_reviewed:
        cmd_list_reviewed(args)
    elif args.dedup_only:
        cmd_dedup(args)
    else:
        cmd_write(args)


if __name__ == '__main__':
    main()
