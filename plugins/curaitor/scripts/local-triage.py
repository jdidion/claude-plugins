#!/usr/bin/env python3
"""Local-model first-round triage pass for curaitor.

Reads a JSON array of articles from stdin, runs each through an
Ollama-hosted local model with an explicit-negatives triage prompt,
and writes an augmented JSON array to stdout.

For each article the output adds:
  - `_local.confidence`   — high-interested | uncertain | high-not-interested
  - `_local.verdict`      — read-now | save-reference | review | skip | obsolete
  - `_local.category`     — ai-tooling | genomics | methods | general
  - `_local.slop_label`   — clean | mild | slop | heavy-slop
  - `_local.tags`         — list of tags
  - `_local.summary`      — 1-2 sentence local-generated summary
  - `_local.model`        — ollama model tag
  - `_local.latency_s`    — request latency
  - `_local.skip`         — true if the local model and the escalation
                            rule agree this article is safe to auto-ignore

Escalation rules:
  strict (default)  — skip when either signal is strong enough to auto-ignore:
                      (a) `confidence == high-not-interested`, or
                      (b) `verdict == skip` AND `confidence == uncertain`
                          — the classifier prompt only emits `verdict=skip`
                          for HARD IGNORES, so a hedged (uncertain, skip)
                          is the model under-reporting confidence on a skip.
                      Everything else falls through to Claude.
  permissive        — same as strict, plus auto-route `high-interested` items
                      to Inbox without Claude review. Not recommended until
                      the local model has a longer agreement track record.

Usage:
  cat articles.json | python3 scripts/local-triage.py [--model TAG] [--mode strict|permissive]

Disabled-safe: if `user-settings.yaml:local_triage.enabled` is false (default),
the script exits 0 and prints the input unchanged (idempotent pass-through)
unless `--force` is set.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _llm_client import call_local_model, resolve_backend_config  # noqa: E402

SETTINGS_PATH = Path(__file__).resolve().parent.parent / 'config' / 'user-settings.yaml'


DEFAULT_SYSTEM = """You are curaitor's first-round triage classifier. You route RSS articles based on the user's reading preferences. Be SKEPTICAL — the typical RSS article is NOT interesting to this user.

USER FOCUS (high-interested only if clearly matches):
- HUMAN clinical/translational genomics: cfDNA, variant calling, CNV, aneuploidy, UPD, methylation, fragmentation, liquid biopsy, MCED
- Bioinformatics pipelines and data formats (Nextflow, WDL, FASTQ/VCF/BED processing, cloud-native genomics)
- AI tooling for dev workflows (Claude Code, CLI-native agents, formal verification, agent memory/harness design)
- Protein language models and ML methods applicable to human genomics
- Novel sequencing tech with clinical relevance (duplex, UMI, basecalling, peptide-to-DNA)

HARD IGNORES (always high-not-interested, verdict=skip):
- Non-human organism genomics: plants, insects, fish, birds, mammals-not-human, yeast, bacteria, fungi, non-human cell biology.
- Business/market news: M&A, FDA approvals, earnings, corporate PR, GenomeWeb news items.
- Generic biology/cell biology without a human genomics or computational angle.
- Metamaterials, physics, unrelated chemistry, agricultural biotech.

UNCERTAIN (confidence=uncertain, verdict=review):
- Articles at the edge: AI/ML methods that COULD apply but aren't explicitly about human genomics,
  spatial omics with unclear clinical link, MCED/liquid biopsy business news, cross-disciplinary methods.

OUTPUT STRICT JSON ONLY (no prose, no fences):
{"category": "ai-tooling"|"genomics"|"methods"|"general", "confidence": "high-interested"|"uncertain"|"high-not-interested", "verdict": "read-now"|"save-reference"|"review"|"skip"|"obsolete", "slop_label": "clean"|"mild"|"slop"|"heavy-slop", "tags": ["..."], "summary": "1-2 sentences"}

EXAMPLES:
Input: A Seychelles warbler genomic toolkit (bioRxiv, about birds)
Output: {"category":"general","confidence":"high-not-interested","verdict":"skip","slop_label":"clean","tags":["non-human-genomics"],"summary":"Bird genomics toolkit — non-human species, no clinical application."}

Input: cfDNA fragment length and methylation patterns for early cancer detection (Nature Methods)
Output: {"category":"genomics","confidence":"high-interested","verdict":"read-now","slop_label":"clean","tags":["cfdna","mced","methylation","early-detection"],"summary":"cfDNA-based MCED method — core user interest."}

Input: Q1 Danaher Life Sciences Sales Rise (GenomeWeb)
Output: {"category":"general","confidence":"high-not-interested","verdict":"skip","slop_label":"clean","tags":["business-news"],"summary":"Corporate earnings news — not technical content."}
"""


USER_TEMPLATE = """Article:
Title: {title}
Source: {source} ({feed_name})
URL: {url}
Summary: {summary}

Classify."""


def load_settings():
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        with SETTINGS_PATH.open() as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def local_triage_config(settings):
    cfg = settings.get('local_triage') or {}
    # Defer backend/model/base_url resolution to the shared client (which
    # applies env-var precedence and backend-appropriate defaults). We only
    # carry `enabled` + `escalation_mode` at this layer.
    return {
        'enabled': bool(cfg.get('enabled', False)),
        'escalation_mode': cfg.get('escalation_mode', 'strict'),
        'raw': cfg,  # Passed through to resolve_backend_config.
    }


def parse_response(content):
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', content or '', flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


def decide_skip(local, mode):
    conf = local.get('confidence')
    verdict = local.get('verdict')
    # Primary signal: confidence is explicitly high-not-interested.
    if conf == 'high-not-interested':
        return True
    # Secondary signal: the model hedges confidence as `uncertain` but still
    # picks `verdict=skip`. Per the classifier prompt, `verdict=skip` is only
    # emitted for HARD IGNORES (non-human genomics, business news, etc.), so a
    # hedged (uncertain, skip) pair is the model telling us it's a skip while
    # under-reporting confidence. Trust verdict here. Explicitly excluded:
    # `verdict=skip` paired with `high-interested` (internally contradictory —
    # don't trust) — we let it escalate to Claude to avoid false positives on
    # genuinely-interesting articles the model flagged incorrectly.
    if verdict == 'skip' and conf == 'uncertain':
        return True
    if mode == 'permissive' and conf == 'high-interested':
        # Permissive mode trusts high-interested to bypass Claude too.
        # Reserved for post-drift-monitor calibration; not a today-default.
        return False  # Still hand to Claude via the existing pipeline
    return False


# ---------------------------------------------------------------------------
# Consistency validation — Gemma-4 at batch=1 produces internally contradictory
# classifications (e.g. confidence=high-not-interested paired with verdict=review,
# or summary="highly relevant" paired with verdict=skip). The downstream router
# reads confidence only, so these contradictions silently misroute articles.
#
# We validate here and re-prompt once on inconsistency. If the re-prompt still
# contradicts, flag as `error: contradiction_unresolved` so the upstream
# orchestrator routes the article to pending-claude-review rather than trusting
# a non-deterministic output.
# ---------------------------------------------------------------------------

# The pairs we consider consistent. Any (confidence, verdict) combination NOT
# in this set triggers a re-prompt.
_CONSISTENT_PAIRS = {
    ('high-not-interested', 'skip'),
    ('high-not-interested', 'obsolete'),  # obsoletes are a form of skip
    ('high-interested', 'read-now'),
    ('high-interested', 'save-reference'),
    ('uncertain', 'review'),
    ('uncertain', 'skip'),       # hedged-skip — handled specially in decide_skip
    ('uncertain', 'read-now'),   # rare but technically valid: edge-of-interest
    ('uncertain', 'save-reference'),  # same
}


def _is_consistent(local):
    """True if (confidence, verdict) is a known-consistent pair."""
    conf = local.get('confidence')
    verdict = local.get('verdict')
    if not conf or not verdict:
        return False  # missing field — always re-prompt
    return (conf, verdict) in _CONSISTENT_PAIRS


def validate_and_repair(local, messages, backend_cfg):
    """Return a possibly-corrected classification + audit metadata.

    If `local` is self-consistent, returns it unchanged (audit stays empty).
    Otherwise re-prompts the model once with the contradiction called out. If
    the re-prompt is still inconsistent, stamps an error so the upstream
    orchestrator routes the article to pending-claude-review instead of
    trusting an unreliable output.

    Adds three audit keys to `local`:
      - consistency_ok: bool (final state after possible re-prompt)
      - consistency_retried: bool (did we re-prompt at least once?)
      - consistency_tiebreaker: str (only if re-prompt failed; always
        'pending-claude' in the current contract — kept as a field so later
        policies can set 'prefer-verdict' / 'prefer-confidence' without a
        schema change)
    """
    local['consistency_retried'] = False
    local['consistency_ok'] = _is_consistent(local)
    if local['consistency_ok']:
        return local

    # First-pass contradiction. Re-prompt once with a specific call-out.
    prior_conf = local.get('confidence')
    prior_verdict = local.get('verdict')
    repair_note = (
        f"Your previous classification was internally inconsistent: "
        f"confidence='{prior_conf}' but verdict='{prior_verdict}'. "
        "These are incompatible. Per the schema, high-not-interested must pair "
        "with verdict='skip'; high-interested must pair with 'read-now' or "
        "'save-reference'; 'uncertain' pairs with 'review' or 'skip'. "
        "Re-classify with a consistent (confidence, verdict) pair and output "
        "STRICT JSON only (no prose, no fences)."
    )
    repair_messages = messages + [
        {'role': 'assistant', 'content': json.dumps({k: v for k, v in local.items() if k not in ('model','backend','latency_s','skip','consistency_retried','consistency_ok')})},
        {'role': 'user', 'content': repair_note},
    ]
    try:
        content, latency = call_local_model(
            backend_cfg, repair_messages, json_mode=True, temperature=0.0,
        )
    except (HTTPError, URLError, TimeoutError) as e:
        local['consistency_retried'] = True
        local['consistency_ok'] = False
        local['error'] = f'repair-call failed: {e}'
        return local

    repaired = parse_response(content)
    local['consistency_retried'] = True
    local['latency_s'] = round(local.get('latency_s', 0) + latency, 2)
    local['prior_confidence_rejected'] = prior_conf
    local['prior_verdict_rejected'] = prior_verdict
    # Merge the repaired output in-place, but keep audit keys.
    for k in ('category', 'confidence', 'verdict', 'slop_label', 'tags', 'summary'):
        if k in repaired:
            local[k] = repaired[k]
    local['consistency_ok'] = _is_consistent(local)

    # Still contradictory after the re-prompt. Don't trust it — flag for Claude.
    if not local['consistency_ok']:
        local['consistency_tiebreaker'] = 'pending-claude'
        local['error'] = 'contradiction_unresolved'
    return local


def triage_one(article, cfg, backend_cfg, system):
    user = USER_TEMPLATE.format(
        title=article.get('title', ''),
        source=article.get('source', ''),
        feed_name=article.get('feed_name', ''),
        url=article.get('url', ''),
        summary=(article.get('summary') or article.get('description') or '')[:500],
    )
    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user},
    ]
    try:
        content, latency = call_local_model(
            backend_cfg,
            messages,
            json_mode=True,
            temperature=0.0,
        )
    except (HTTPError, URLError, TimeoutError) as e:
        return {'error': str(e)}

    parsed = parse_response(content)
    local = {
        'model': backend_cfg['model'],
        'backend': backend_cfg['backend'],
        'latency_s': round(latency, 2),
        **parsed,
    }
    # Consistency check + one-shot repair re-prompt. On persistent contradiction,
    # validate_and_repair sets `error: contradiction_unresolved` so the upstream
    # orchestrator routes the article to pending-claude-review.
    local = validate_and_repair(local, messages, backend_cfg)
    local['skip'] = decide_skip(local, cfg['escalation_mode'])
    return local


def main():
    parser = argparse.ArgumentParser(description='Local-model first-round triage pass for curaitor')
    parser.add_argument('--model', help='Override user-settings model (also via CURAITOR_LOCAL_MODEL)')
    parser.add_argument('--mode', choices=['strict', 'permissive'], help='Override escalation mode')
    parser.add_argument('--backend', choices=['ollama', 'omlx'], help='Override LLM backend (also via CURAITOR_LOCAL_BACKEND)')
    parser.add_argument('--base-url', dest='base_url', help='Override backend base URL (also via CURAITOR_LOCAL_BASE_URL)')
    parser.add_argument('--force', action='store_true', help='Run even when local_triage.enabled=false')
    args = parser.parse_args()

    settings = load_settings()
    cfg = local_triage_config(settings)
    if args.mode:
        cfg['escalation_mode'] = args.mode
    # CLI overrides surface through env vars so the shared client's resolver
    # picks them up with the same precedence as external-env overrides.
    if args.backend:
        os.environ['CURAITOR_LOCAL_BACKEND'] = args.backend
    if args.base_url:
        os.environ['CURAITOR_LOCAL_BASE_URL'] = args.base_url
    if args.model:
        os.environ['CURAITOR_LOCAL_MODEL'] = args.model

    if not cfg['enabled'] and not args.force:
        # Disabled: pass-through, don't touch stdin, emit it back verbatim.
        data = sys.stdin.read()
        sys.stdout.write(data)
        return

    backend_cfg = resolve_backend_config(cfg['raw'])

    articles = json.load(sys.stdin)
    if not isinstance(articles, list):
        articles = [articles]

    system = DEFAULT_SYSTEM
    augmented = []
    skipped = 0
    consistency_retried = 0
    consistency_unresolved = 0
    for a in articles:
        local = triage_one(a, cfg, backend_cfg, system)
        a['_local'] = local
        if local.get('skip'):
            skipped += 1
        if local.get('consistency_retried'):
            consistency_retried += 1
        if local.get('error') == 'contradiction_unresolved':
            consistency_unresolved += 1
        augmented.append(a)

    json.dump(augmented, sys.stdout)
    sys.stdout.write('\n')
    print(
        f'local-triage: {len(articles)} in, {skipped} auto-skipped, '
        f'{len(articles) - skipped} to claude '
        f'(mode={cfg["escalation_mode"]}, backend={backend_cfg["backend"]}, '
        f'model={backend_cfg["model"]}, '
        f'consistency_retried={consistency_retried}, '
        f'contradiction_unresolved={consistency_unresolved})',
        file=sys.stderr,
    )


if __name__ == '__main__':
    main()
