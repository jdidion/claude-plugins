#!/usr/bin/env python3
"""Bench the local-LLM backend on a realistic curaitor triage payload.

Ports the TTFT bench pattern from `local-models/turboquant-test/bench_omlx_ttft.py`
but swaps the WDL prefix for a concatenated batch of curaitor Ignored/ notes
(representative of the ~42-article bulk-dump shape). Streams the response so
we measure time-to-first-token, not total wall-clock — TTFT is the metric
that reflects prefix-cache hits.

For each of N questions the script reports cold/warm TTFT, prompt tokens, and
cached tokens; final line reports the cold→warm speedup.

Usage:
  # Bench oMLX (the high-performance backend):
  python3 scripts/bench-local-llm.py --backend omlx --model gemma-4-26B-A4B-it-MLX-4bit

  # Bench Ollama for comparison (when a suitable model is available):
  python3 scripts/bench-local-llm.py --backend ollama --model <tag>

  # Override defaults:
  python3 scripts/bench-local-llm.py \
      --base-url http://127.0.0.1:8000 \
      --article-count 20 \
      --article-bytes-each 2000

Prerequisites:
  - Backend running and reachable (omlx: /health returns 200; ollama: /api/tags)
  - Model loaded / pullable
  - A curaitor vault with Curaitor/Ignored/ populated (for the prefix payload)
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_client import resolve_backend_config  # noqa: E402


SYSTEM = (
    "You are curaitor's bulk-triage QA bot. Answer questions about the "
    "article batch tersely. One sentence per answer. No preamble."
)

QUESTIONS = [
    "How many articles in the batch mention genomics or sequencing?",
    "Which article appears first in the batch, by title?",
    "Name one non-human-organism article from the batch.",
]


def load_vault():
    """Reuse triage-write's find_vault() — same vault-resolution policy."""
    # Dynamic import to tolerate the hyphen in the filename.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'tw', Path(__file__).resolve().parent / 'triage-write.py'
    )
    tw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tw)
    return tw.find_vault()


def build_article_prefix(vault, article_count, bytes_each):
    """Concat `article_count` ignored notes as a single prefix. Returns
    (prefix_text, article_titles)."""
    ignored = Path(vault) / 'Curaitor' / 'Ignored'
    if not ignored.is_dir():
        raise SystemExit(f"No Curaitor/Ignored/ under {vault}")
    # Take the most recent N notes — matches the "current batch" shape.
    notes = sorted(ignored.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
    notes = notes[:article_count]
    if len(notes) < article_count:
        print(
            f"Warning: only {len(notes)} Ignored notes available "
            f"(wanted {article_count})",
            file=sys.stderr,
        )
    parts = []
    titles = []
    for p in notes:
        text = p.read_text(encoding='utf-8')[:bytes_each]
        title = p.stem
        titles.append(title)
        parts.append(f"--- Article: {title} ---\n{text}\n")
    return '\n'.join(parts) + '\n---\n\n', titles


def stream_openai_chat(base_url, api_key, model, messages, max_tokens, is_omlx):
    """Stream via OpenAI-compat `/v1/chat/completions` (both Ollama and oMLX
    expose this endpoint). Return dict: ttft_s, wall_s, text, usage."""
    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.0,
        'max_tokens': max_tokens,
        'stream': True,
    }
    if is_omlx:
        payload['stream_options'] = {'include_usage': True}
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    endpoint = f'{base_url.rstrip("/")}/v1/chat/completions'
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    t_start = time.perf_counter()
    t_first = None
    chunks = []
    last_usage = {}
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            if not raw.strip():
                continue
            line = raw.decode().strip()
            if not line.startswith('data: '):
                continue
            data = line[6:]
            if data == '[DONE]':
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get('choices') or []
            if choices:
                delta = choices[0].get('delta') or {}
                content = delta.get('content')
                if content:
                    if t_first is None:
                        t_first = time.perf_counter() - t_start
                    chunks.append(content)
            if chunk.get('usage'):
                last_usage = chunk['usage']
    wall = time.perf_counter() - t_start
    return {
        'ttft_s': t_first,
        'wall_s': wall,
        'text': ''.join(chunks),
        'usage': last_usage,
    }


def bench(backend_cfg, prefix, is_omlx):
    # Warm-up so we measure cache behavior, not first-load behavior.
    print('  warming model (short dummy)…', flush=True)
    stream_openai_chat(
        backend_cfg['base_url'], backend_cfg.get('api_key'),
        backend_cfg['model'],
        [{'role': 'user', 'content': 'Say OK.'}],
        max_tokens=4,
        is_omlx=is_omlx,
    )
    print('  done warming.', flush=True)

    results = []
    for i, q in enumerate(QUESTIONS):
        messages = [
            {'role': 'system', 'content': SYSTEM},
            {'role': 'user', 'content': prefix + q},
        ]
        r = stream_openai_chat(
            backend_cfg['base_url'], backend_cfg.get('api_key'),
            backend_cfg['model'], messages, max_tokens=80, is_omlx=is_omlx,
        )
        u = r['usage']
        pt = u.get('prompt_tokens', 0)
        ct = u.get('completion_tokens', 0)
        cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
        hit_pct = (cached / pt * 100) if pt else 0.0
        tag = 'COLD' if i == 0 else f'WARM{i}'
        ttft = f"{r['ttft_s']:6.2f}s" if r['ttft_s'] else '  N/A '
        print(
            f"  {tag}  ttft={ttft} wall={r['wall_s']:6.2f}s  "
            f"prompt={pt} completion={ct} cached={cached} ({hit_pct:5.1f}%)",
            flush=True,
        )
        print(f"        Q: {q!r}", flush=True)
        print(f"        A: {r['text'][:120]!r}", flush=True)
        results.append(r)

    valid = [r for r in results if r['ttft_s']]
    if len(valid) >= 2:
        cold = valid[0]['ttft_s']
        warm = [r['ttft_s'] for r in valid[1:]]
        avg_warm = sum(warm) / len(warm)
        print(
            f"  --> TTFT speedup: {cold/avg_warm:.1f}x  "
            f"(cold {cold:.2f}s → avg warm {avg_warm:.2f}s)",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--backend', choices=['ollama', 'omlx'], default='omlx')
    parser.add_argument('--model')
    parser.add_argument('--base-url')
    parser.add_argument('--article-count', type=int, default=20,
                        help='Articles to concat for the prefix (default 20)')
    parser.add_argument('--article-bytes-each', type=int, default=2000,
                        help='Max bytes per article (default 2000 ≈ realistic note size)')
    args = parser.parse_args()

    # Push CLI flags into env so the shared resolver picks them up.
    if args.backend:
        os.environ['CURAITOR_LOCAL_BACKEND'] = args.backend
    if args.model:
        os.environ['CURAITOR_LOCAL_MODEL'] = args.model
    if args.base_url:
        os.environ['CURAITOR_LOCAL_BASE_URL'] = args.base_url

    backend_cfg = resolve_backend_config({})
    if not backend_cfg['model']:
        raise SystemExit(
            'No model resolved — pass --model or set CURAITOR_LOCAL_MODEL'
        )

    vault = load_vault()
    prefix, titles = build_article_prefix(
        vault, args.article_count, args.article_bytes_each,
    )
    bytes_len = len(prefix)
    word_estimate = len(prefix.split())
    print(
        f'Prefix: {len(titles)} articles, ~{word_estimate} words '
        f'(~{bytes_len / 4:.0f} tokens est.) + trailing question.',
    )
    print(
        f'Backend: {backend_cfg["backend"]}  base_url={backend_cfg["base_url"]}  '
        f'model={backend_cfg["model"]}',
    )

    is_omlx = backend_cfg['backend'] == 'omlx'
    bench(backend_cfg, prefix, is_omlx)


if __name__ == '__main__':
    main()
