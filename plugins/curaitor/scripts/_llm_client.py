"""Shared local-LLM client for curaitor.

Abstracts over two backends:
  - `ollama` — the current Ollama `/api/chat` endpoint (default).
  - `omlx`   — oMLX's Anthropic-compatible `/v1/messages` endpoint on Apple
               Silicon, which gives us prefix-cache hits on repeat triage
               prompts (validated to ~94% cache hit, 0.75s warm TTFT).

Both callers (`local-triage.py`, `summarize-inbox.py`) use the same
`system + single user turn, JSON-ish output` pattern, so the abstraction
only needs to round-trip a messages list and return the model's content
string plus wall-clock latency.

Config resolution (highest precedence first):
  1. CURAITOR_LOCAL_BACKEND / CURAITOR_LOCAL_BASE_URL /
     CURAITOR_LOCAL_API_KEY_PATH / CURAITOR_LOCAL_MODEL env vars
  2. user-settings.yaml `local_triage.{backend,base_url,api_key_path,model}`
  3. Legacy yaml `local_triage.ollama_host` (for backwards compatibility
     when `backend=ollama`)
  4. Built-in defaults (ollama, http://localhost:11434, huihui Gemma E4B)
"""

import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen


DEFAULT_BACKEND = 'ollama'
OLLAMA_DEFAULT_BASE = 'http://localhost:11434'
OMLX_DEFAULT_BASE = 'http://127.0.0.1:8000'
OMLX_DEFAULT_API_KEY_PATH = '~/.omlx/settings.json'


def resolve_backend_config(settings_cfg):
    """Resolve which backend + model + base_url + api_key to use.

    `settings_cfg` is the already-loaded `local_triage` (or similar) dict
    from user-settings.yaml. Returns a dict with keys: backend, base_url,
    api_key, model, timeout.
    """
    cfg = dict(settings_cfg or {})

    backend = (
        os.environ.get('CURAITOR_LOCAL_BACKEND')
        or cfg.get('backend')
        or DEFAULT_BACKEND
    ).lower()

    model = (
        os.environ.get('CURAITOR_LOCAL_MODEL')
        or cfg.get('model')
    )

    base_url = os.environ.get('CURAITOR_LOCAL_BASE_URL') or cfg.get('base_url')
    if not base_url:
        # Fall back to legacy `ollama_host` if present, else per-backend default.
        if backend == 'omlx':
            base_url = OMLX_DEFAULT_BASE
        else:
            base_url = cfg.get('ollama_host') or OLLAMA_DEFAULT_BASE

    api_key = None
    if backend == 'omlx':
        api_key_path = (
            os.environ.get('CURAITOR_LOCAL_API_KEY_PATH')
            or cfg.get('api_key_path')
            or OMLX_DEFAULT_API_KEY_PATH
        )
        api_key = _load_omlx_api_key(api_key_path)

    return {
        'backend': backend,
        'base_url': base_url.rstrip('/'),
        'api_key': api_key,
        'model': model,
        'timeout': cfg.get('timeout', 120),
    }


def _load_omlx_api_key(api_key_path):
    """Read api_key from oMLX settings.json; return None if missing."""
    path = Path(os.path.expanduser(api_key_path))
    if not path.is_file():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        return (data.get('auth') or {}).get('api_key')
    except (OSError, json.JSONDecodeError):
        return None


def call_local_model(cfg, messages, *, max_tokens=None, temperature=0.0, json_mode=False):
    """Dispatch to the configured backend. Returns (content_str, latency_s).

    `messages` is an OpenAI-style list: [{'role': 'system'|'user'|'assistant',
    'content': '...'}, ...]. Both backends treat the first `system` message
    specially (Ollama flattens system+user; oMLX/Anthropic uses the top-level
    `system` parameter).

    `json_mode` — when True, request JSON-only output (Ollama supports
    `format: 'json'`; oMLX/Anthropic ignores it — callers should still
    defensively re-parse).
    """
    backend = cfg['backend']
    if backend == 'ollama':
        return _call_ollama(cfg, messages, max_tokens, temperature, json_mode)
    if backend == 'omlx':
        return _call_omlx(cfg, messages, max_tokens, temperature)
    raise ValueError(f'unknown local LLM backend: {backend!r}')


def _call_ollama(cfg, messages, max_tokens, temperature, json_mode):
    payload = {
        'model': cfg['model'],
        'messages': messages,
        'stream': False,
        'options': {
            'temperature': temperature,
            'repeat_penalty': 1.1,
        },
        'think': False,
    }
    if json_mode:
        payload['format'] = 'json'
    if max_tokens is not None:
        payload['options']['num_predict'] = max_tokens

    req = Request(
        f'{cfg["base_url"]}/api/chat',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    t0 = time.perf_counter()
    with urlopen(req, timeout=cfg['timeout']) as resp:
        body = json.loads(resp.read())
    latency = time.perf_counter() - t0
    content = (body.get('message') or {}).get('content', '') or ''
    return content, latency


def _call_omlx(cfg, messages, max_tokens, temperature):
    # Anthropic-compat API splits `system` into a top-level parameter.
    system_parts = [m['content'] for m in messages if m.get('role') == 'system']
    non_system = [m for m in messages if m.get('role') != 'system']
    # Anthropic requires the last message to be `user`. Our callers always
    # send a single user turn after the system, so this is a safe reshape.
    payload = {
        'model': cfg['model'],
        'messages': non_system,
        'max_tokens': max_tokens if max_tokens is not None else 1024,
        'temperature': temperature,
    }
    if system_parts:
        payload['system'] = '\n\n'.join(system_parts)

    headers = {
        'Content-Type': 'application/json',
        'anthropic-version': '2023-06-01',
    }
    if cfg.get('api_key'):
        headers['x-api-key'] = cfg['api_key']

    req = Request(
        f'{cfg["base_url"]}/v1/messages',
        data=json.dumps(payload).encode(),
        headers=headers,
        method='POST',
    )
    t0 = time.perf_counter()
    with urlopen(req, timeout=cfg['timeout']) as resp:
        body = json.loads(resp.read())
    latency = time.perf_counter() - t0
    # Anthropic response: content is a list of blocks; we want the text of
    # the first `text` block. Tool-use blocks are irrelevant for our
    # JSON-returning triage/summarize prompts.
    content = ''
    for block in body.get('content') or []:
        if block.get('type') == 'text':
            content = block.get('text', '') or ''
            break
    return content, latency
