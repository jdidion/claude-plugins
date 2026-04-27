#!/usr/bin/env python3
"""Accuracy metrics dashboard and backfill for curaitor.

Usage:
    python3 scripts/accuracy-metrics.py              # show dashboard
    python3 scripts/accuracy-metrics.py --backfill   # backfill from vault state

Reads config/accuracy-stats.yaml, computes precision/recall, shows graduation status.
"""

import argparse
import json
import os
import re
import sys
from datetime import date

import yaml

STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'accuracy-stats.yaml')

# Graduation thresholds.
#
# Thresholds were raised by ~5pp at each level after the engagement-as-TP
# change: a Review article now counts as TP if the user kept it OR engaged
# with it (asked questions, requested detail) before ultimately recycling.
# Because the TP bucket is larger under that definition, precision is
# mechanically easier to achieve, so the bars go up to preserve the same
# real-world quality signal.
LEVELS = {
    0: {
        'name': 'Cold start',
        'next': {
            'reviewed': 50,
            'review_ignored_passes': 2,
            'rolling_precision': 0.75,
            'rolling_recall': 0.8,
        },
    },
    1: {
        'name': 'Normal',
        'next': {
            'reviewed': 100,
            'review_ignored_passes': 4,
            'rolling_precision': 0.85,
            'rolling_recall': 0.85,
        },
    },
    2: {
        'name': 'Confident',
        'next': {
            'reviewed': 200,
            'review_ignored_passes': 6,
            'rolling_precision': 0.9,
            'rolling_recall': 0.9,
        },
    },
    3: {
        'name': 'Auto-recycle',
        'next': None,
    },
}


def load_stats():
    if os.path.exists(STATS_PATH):
        with open(STATS_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


ROLLING_CAP = 50


def _entry_signal_count(entry):
    """Number of signals represented by a rolling_window entry.

    Two historical schemas:
      single-signal: {date, signal, source, title}       → 1
      batch:         {date, type, source, count: N}      → N
    """
    if not isinstance(entry, dict):
        return 1
    return int(entry.get('count', 1))


def normalize_rolling_window(stats):
    """Explode batch entries ({type, count}) into singles ({signal}).

    After normalization every entry represents exactly one signal, so
    trim-by-signal reduces to trim-by-length and the dashboard no longer
    needs the dual-schema fallback.
    """
    window = stats.get('rolling_window')
    if not isinstance(window, list):
        return stats
    exploded = []
    for entry in window:
        if not isinstance(entry, dict):
            exploded.append(entry)
            continue
        count = int(entry.get('count', 1))
        signal = entry.get('signal') or entry.get('type') or ''
        if count <= 1 and 'signal' in entry and 'count' not in entry and 'type' not in entry:
            exploded.append(entry)
            continue
        base = {k: v for k, v in entry.items() if k not in ('count', 'type')}
        if signal:
            base['signal'] = signal
        for _ in range(max(1, count)):
            exploded.append(dict(base))
    stats['rolling_window'] = exploded
    return stats


def trim_rolling_window(stats):
    """Cap stats['rolling_window'] at ROLLING_CAP signals (not list entries).

    Batch-form entries ({type, count: N}) made the old per-entry cap
    under-count: 43 entries could carry 600+ signals and the trim would
    no-op. Walk newest → oldest accumulating `count` (default 1); drop the
    tail once adding the next entry would exceed ROLLING_CAP. Drop-whole-
    entry — no splitting. Preserves entry integrity; may keep slightly
    fewer signals than ROLLING_CAP when a straddling entry is dropped.

    save_stats normalizes first, then trims, so on the single-signal
    schema this reduces to trim-by-length.
    """
    window = stats.get('rolling_window')
    if not isinstance(window, list) or not window:
        return stats
    total = 0
    kept_from = len(window)
    for i in range(len(window) - 1, -1, -1):
        count = _entry_signal_count(window[i])
        if total + count > ROLLING_CAP:
            break
        total += count
        kept_from = i
    if kept_from > 0:
        stats['rolling_window'] = window[kept_from:]
    return stats


def save_stats(stats):
    normalize_rolling_window(stats)
    trim_rolling_window(stats)
    with open(STATS_PATH, 'w') as f:
        f.write("# Auto-updated by /cu:review and /cu:review-ignored\n")
        f.write("# Do not edit manually — use scripts/accuracy-metrics.py to view\n\n")
        yaml.dump(stats, f, default_flow_style=False, sort_keys=False, allow_unicode=True)


def compute_metrics(stats):
    """Compute precision, recall, and total reviewed from stats.

    Signal definitions:
      TP — article was kept (y/d/t/c/b/r/p/skip) OR the user engaged with it
           (asked at least one question/asked for detail before the verdict).
           Engagement means triage was right to surface the article for
           attention, even if the ultimate decision was to recycle.
      FP — article was recycled (n) AND there was no engagement. Pure false
           positive: the user saw the summary, said "no", and moved on.
      TN — (via /cu:review-ignored) user confirmed an Ignored article was
           correctly ignored.
      FN — (via /cu:review-ignored) user rescued a wrongly-ignored article.

    The `duplicate` signal counts articles that re-surfaced after already
    being recycled. It's tracked separately from TP/FP/TN/FN so it doesn't
    skew precision/recall — a rising duplicate rate signals dedup regression.

    Engagement is tracked as a side-channel counter (not a separate bucket):
    `engaged_tp` counts how many of the TP signals came from engagement on
    recycled articles vs. outright keeps. Useful for the dashboard.
    """
    lifetime = stats.get('lifetime', {})
    rolling = stats.get('rolling_window', [])

    # Lifetime totals
    lt = {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0, 'duplicate': 0, 'engaged_tp': 0}
    for source in lifetime.values():
        if isinstance(source, dict):
            for k in lt:
                lt[k] += source.get(k, 0)

    # `duplicate` and `engaged_tp` are excluded from the reviewed-total
    # (engaged_tp is already counted inside tp; duplicate isn't a decision).
    lt_total = lt['tp'] + lt['fp'] + lt['tn'] + lt['fn']
    lt_precision = lt['tp'] / (lt['tp'] + lt['fp']) if (lt['tp'] + lt['fp']) > 0 else 0
    lt_recall = lt['tp'] / (lt['tp'] + lt['fn']) if (lt['tp'] + lt['fn']) > 0 else 0
    lt_engagement_rate = lt['engaged_tp'] / lt['tp'] if lt['tp'] else 0

    # Rolling window
    rw = {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0, 'duplicate': 0, 'engaged_tp': 0}
    for entry in rolling:
        # Support both schemas: {signal: tp} and {type: tp, count: N}
        sig = entry.get('signal') or entry.get('type') or ''
        count = entry.get('count', 1)
        if sig in rw:
            rw[sig] += count
        # Engagement is a boolean per entry; count it when present on a TP.
        if sig == 'tp' and entry.get('engaged'):
            rw['engaged_tp'] += count

    rw_total = rw['tp'] + rw['fp'] + rw['tn'] + rw['fn']
    rw_precision = rw['tp'] / (rw['tp'] + rw['fp']) if (rw['tp'] + rw['fp']) > 0 else 0
    rw_recall = rw['tp'] / (rw['tp'] + rw['fn']) if (rw['tp'] + rw['fn']) > 0 else 0
    rw_engagement_rate = rw['engaged_tp'] / rw['tp'] if rw['tp'] else 0

    return {
        'lifetime': lt, 'lifetime_total': lt_total,
        'lt_precision': lt_precision, 'lt_recall': lt_recall,
        'lt_engagement_rate': lt_engagement_rate,
        'rolling': rw, 'rolling_total': rw_total,
        'rw_precision': rw_precision, 'rw_recall': rw_recall,
        'rw_engagement_rate': rw_engagement_rate,
    }


def check_graduation(stats, metrics):
    """Check if current level should graduate. Returns new level or None."""
    level = stats.get('autonomy_level', 0)
    level_info = LEVELS.get(level, {})
    criteria = level_info.get('next')
    if not criteria:
        return None

    total_reviewed = metrics['lifetime_total']
    passes = stats.get('review_ignored_passes', 0)
    rw_prec = metrics['rw_precision']
    rw_rec = metrics['rw_recall']
    rw_total = metrics['rolling_total']

    # Need enough rolling data to be meaningful
    if rw_total < 20:
        return None

    if (total_reviewed >= criteria['reviewed'] and
            passes >= criteria['review_ignored_passes'] and
            rw_prec >= criteria['rolling_precision'] and
            rw_rec >= criteria['rolling_recall']):
        return level + 1
    return None


def check_demotion(stats, fn_count):
    """Check if level should be demoted due to false negatives."""
    level = stats.get('autonomy_level', 0)
    if level > 0 and fn_count >= 3:
        return level - 1
    return None


def print_dashboard(stats, metrics):
    """Print human-readable accuracy dashboard."""
    level = stats.get('autonomy_level', 0)
    level_name = LEVELS.get(level, {}).get('name', 'Unknown')

    print(f"Curaitor Accuracy Dashboard")
    print(f"{'=' * 50}")
    print(f"Autonomy Level: {level} ({level_name})")
    print()

    # Lifetime
    lt = metrics['lifetime']
    print(f"Lifetime ({metrics['lifetime_total']} signals):")
    print(f"  TP: {lt['tp']}  FP: {lt['fp']}  TN: {lt['tn']}  FN: {lt['fn']}")
    print(f"  Precision: {metrics['lt_precision']:.1%}  Recall: {metrics['lt_recall']:.1%}")
    if lt.get('engaged_tp', 0) and lt['tp']:
        engaged = lt['engaged_tp']
        rate = metrics['lt_engagement_rate']
        print(f"  Engagement: {engaged}/{lt['tp']} TPs came from engagement on recycled ({rate:.1%})")
    if lt.get('duplicate', 0):
        reviewed = metrics['lifetime_total']
        rate = lt['duplicate'] / (reviewed + lt['duplicate']) if reviewed else 0
        print(f"  Duplicates re-surfaced: {lt['duplicate']} ({rate:.1%} of inflow)")

    # Per source
    lifetime = stats.get('lifetime', {})
    for source in ['instapaper', 'rss']:
        s = lifetime.get(source, {})
        total = sum(s.get(k, 0) for k in ['tp', 'fp', 'tn', 'fn'])
        if total > 0:
            tp, fp = s.get('tp', 0), s.get('fp', 0)
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0
            print(f"  {source}: {total} signals, precision={prec:.1%}")
    print()

    # Rolling
    rw = metrics['rolling']
    print(f"Rolling window ({metrics['rolling_total']}/50 entries):")
    print(f"  TP: {rw['tp']}  FP: {rw['fp']}  TN: {rw['tn']}  FN: {rw['fn']}")
    print(f"  Precision: {metrics['rw_precision']:.1%}  Recall: {metrics['rw_recall']:.1%}")
    if rw.get('engaged_tp', 0) and rw['tp']:
        print(f"  Engagement: {rw['engaged_tp']}/{rw['tp']} TPs ({metrics['rw_engagement_rate']:.1%})")
    if rw.get('duplicate', 0):
        print(f"  Duplicates re-surfaced: {rw['duplicate']}")
    print()

    # Review-ignored
    passes = stats.get('review_ignored_passes', 0)
    last = stats.get('last_review_ignored')
    print(f"Review-ignored: {passes} passes, last: {last or 'never'}")
    print()

    # Graduation
    criteria = LEVELS.get(level, {}).get('next')
    if criteria:
        print(f"Next level ({level + 1}) requires:")
        total = metrics['lifetime_total']
        print(f"  Reviewed: {total}/{criteria['reviewed']} {'OK' if total >= criteria['reviewed'] else ''}")
        print(f"  Review-ignored passes: {passes}/{criteria['review_ignored_passes']} {'OK' if passes >= criteria['review_ignored_passes'] else ''}")
        rw_total = metrics['rolling_total']
        if rw_total >= 20:
            print(f"  Rolling precision: {metrics['rw_precision']:.1%}/{criteria['rolling_precision']:.0%} {'OK' if metrics['rw_precision'] >= criteria['rolling_precision'] else ''}")
            print(f"  Rolling recall: {metrics['rw_recall']:.1%}/{criteria['rolling_recall']:.0%} {'OK' if metrics['rw_recall'] >= criteria['rolling_recall'] else ''}")
        else:
            print(f"  Rolling window: {rw_total}/20 minimum entries needed")
    else:
        print("Max level reached.")


def backfill(stats):
    """Backfill lifetime counts from observable vault state."""
    # Find vault
    vault = None
    config_path = os.path.expanduser("~/Library/Application Support/obsidian/obsidian.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        candidates = [v.get('path', '') for v in config.get('vaults', {}).values() if os.path.isdir(v.get('path', ''))]
        markers = ['Curaitor/Inbox', 'Curaitor/Review', 'Curaitor/Ignored']
        for p in candidates:
            score = sum(1 for m in markers if os.path.isdir(os.path.join(p, m)))
            if score >= 2:
                vault = p
                break

    if not vault:
        print("Could not find vault for backfill", file=sys.stderr)
        sys.exit(1)

    print(f"Vault: {vault}")

    def count_by_source(folder):
        path = os.path.join(vault, folder)
        counts = {'instapaper': 0, 'rss': 0, 'other': 0}
        if not os.path.isdir(path):
            return counts
        for f in os.listdir(path):
            if not f.endswith('.md') or f.startswith('.'):
                continue
            try:
                with open(os.path.join(path, f)) as fh:
                    head = fh.read(500)
                m = re.search(r'^source:\s*(.+)$', head, re.MULTILINE)
                source = m.group(1).strip() if m else 'other'
                if source in counts:
                    counts[source] += 1
                else:
                    counts['other'] += 1
            except (OSError, UnicodeDecodeError):
                continue
        return counts

    # Count articles by folder
    inbox = count_by_source('Curaitor/Inbox')
    library = count_by_source('Library')
    ignored = count_by_source('Curaitor/Ignored')

    # Count recycle entries
    recycle_path = os.path.join(vault, 'Curaitor', 'Recycle.md')
    recycle_count = 0
    if os.path.exists(recycle_path):
        with open(recycle_path) as f:
            recycle_count = sum(1 for line in f if line.strip().startswith('- ['))

    # Approximate signals:
    # Inbox + Library = TP (articles kept after review/triage)
    # Recycle = FP (from review) + TN (from review-ignored) — split roughly
    # Ignored (remaining) = TN (unreviewed)
    for source in ['instapaper', 'rss']:
        tp = inbox.get(source, 0) + library.get(source, 0)
        tn = ignored.get(source, 0)
        stats['lifetime'][source]['tp'] = tp
        stats['lifetime'][source]['tn'] = tn
        # FP and FN are harder to approximate — leave at 0 (conservative)

    total_tp = sum(stats['lifetime'][s]['tp'] for s in ['instapaper', 'rss'])
    total_tn = sum(stats['lifetime'][s]['tn'] for s in ['instapaper', 'rss'])

    print(f"Backfill results:")
    print(f"  Inbox/Library (TP): instapaper={inbox.get('instapaper', 0)}, rss={inbox.get('rss', 0)}, other={inbox.get('other', 0) + library.get('other', 0)}")
    print(f"  Ignored (TN): instapaper={ignored.get('instapaper', 0)}, rss={ignored.get('rss', 0)}, other={ignored.get('other', 0)}")
    print(f"  Recycle entries: {recycle_count}")
    print(f"  Total TP={total_tp}, TN={total_tn}")

    # Set level based on volume
    total = total_tp + total_tn
    if total >= 100:
        stats['autonomy_level'] = 1
        print(f"\nSetting autonomy_level=1 (Normal) based on {total} articles")
    else:
        stats['autonomy_level'] = 0
        print(f"\nSetting autonomy_level=0 (Cold start) based on {total} articles")

    # Rolling window stays empty — graduation must be earned from new data
    stats['rolling_window'] = []

    save_stats(stats)
    print(f"\nSaved to {STATS_PATH}")


def cmd_trim(args):
    """Apply the FIFO cap to rolling_window in place (signal-counted).

    Safe to run repeatedly. Reports both list-entry count and signal-total
    before and after so callers can see a batch→single normalization that
    re-inflated the list but left signal total unchanged.
    """
    del args  # unused; kept for dispatch-signature consistency
    stats = load_stats()
    window = stats.get('rolling_window') or []
    before_entries = len(window)
    before_signals = sum(_entry_signal_count(e) for e in window)
    if before_signals <= ROLLING_CAP and before_entries <= ROLLING_CAP:
        print(json.dumps({
            'before_entries': before_entries,
            'before_signals': before_signals,
            'after_entries': before_entries,
            'after_signals': before_signals,
            'status': 'already-at-cap',
        }))
        return
    save_stats(stats)  # normalizes + trims on write
    after_window = (load_stats() or {}).get('rolling_window') or []
    after_entries = len(after_window)
    after_signals = sum(_entry_signal_count(e) for e in after_window)
    print(json.dumps({
        'before_entries': before_entries,
        'before_signals': before_signals,
        'after_entries': after_entries,
        'after_signals': after_signals,
        'status': 'trimmed',
    }))


def cmd_normalize(args):
    """One-shot: explode batch entries into singles, then trim.

    Writes through save_stats which handles both. After this runs, every
    rolling_window entry represents exactly one signal.
    """
    del args
    stats = load_stats()
    window = stats.get('rolling_window') or []
    before_entries = len(window)
    before_signals = sum(_entry_signal_count(e) for e in window)
    save_stats(stats)  # normalize + trim
    after_window = (load_stats() or {}).get('rolling_window') or []
    print(json.dumps({
        'before_entries': before_entries,
        'before_signals': before_signals,
        'after_entries': len(after_window),
        'after_signals': sum(_entry_signal_count(e) for e in after_window),
        'status': 'normalized',
    }))


def cmd_record_signal(args):
    """Append a rolling_window entry AND increment lifetime counters.

    Replaces the ad-hoc inline YAML edits the skill docs described.
    Auto-trims the rolling window, so skills don't need to.

    Example:
      python3 scripts/accuracy-metrics.py --record-signal \
          --signal tp --source rss --title "Article Title"
      python3 scripts/accuracy-metrics.py --record-signal \
          --signal tp --source rss --engaged --title "Article"
    """
    if not args.signal or not args.source:
        print(json.dumps({'status': 'error', 'error': 'need --signal and --source'}))
        sys.exit(2)
    if args.signal not in ('tp', 'fp', 'tn', 'fn', 'duplicate'):
        print(json.dumps({'status': 'error', 'error': f'bad --signal: {args.signal}'}))
        sys.exit(2)

    stats = load_stats()
    stats.setdefault('lifetime', {})
    stats['lifetime'].setdefault(args.source, {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0})
    stats['lifetime'][args.source][args.signal] = stats['lifetime'][args.source].get(args.signal, 0) + 1

    # Track engaged-TP as a side-channel counter (separate from signal).
    if args.signal == 'tp' and args.engaged:
        stats['lifetime'][args.source]['engaged_tp'] = (
            stats['lifetime'][args.source].get('engaged_tp', 0) + 1
        )

    entry = {
        'date': date.today().isoformat(),
        'signal': args.signal,
        'source': args.source,
    }
    if args.title:
        entry['title'] = args.title
    if args.engaged:
        entry['engaged'] = True
    stats.setdefault('rolling_window', []).append(entry)

    save_stats(stats)  # auto-trims
    window = (load_stats() or {}).get('rolling_window') or []
    print(json.dumps({'status': 'recorded', 'rolling_window_size': len(window)}))


def main():
    parser = argparse.ArgumentParser(description='Curaitor accuracy metrics')
    parser.add_argument('--backfill', action='store_true', help='Backfill stats from vault state')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--trim', action='store_true',
                        help='One-shot: cap rolling_window at ROLLING_CAP signals (FIFO, keep newest). '
                             'Counts signals by entry.count (default 1), so batch entries are respected.')
    parser.add_argument('--normalize', action='store_true',
                        help='One-shot: explode batch rolling_window entries ({type, count: N}) into '
                             'N single-signal entries ({signal}), then trim. Makes trim-by-length == '
                             'trim-by-signal for future writes.')
    parser.add_argument('--record-signal', action='store_true',
                        help='Append a rolling_window entry + increment lifetime counters. '
                             'Auto-trims. Requires --signal and --source; --title, --engaged optional.')
    parser.add_argument('--signal', choices=['tp', 'fp', 'tn', 'fn', 'duplicate'],
                        help='Signal type (used with --record-signal)')
    parser.add_argument('--source', help='Source tag: rss|instapaper|other (used with --record-signal)')
    parser.add_argument('--title', help='Article title for the rolling_window entry (used with --record-signal)')
    parser.add_argument('--engaged', action='store_true',
                        help='Mark the entry as engaged TP (used with --record-signal --signal tp)')
    args = parser.parse_args()

    stats = load_stats()

    if args.trim:
        cmd_trim(args)
        return
    if args.normalize:
        cmd_normalize(args)
        return
    if args.record_signal:
        cmd_record_signal(args)
        return

    if args.backfill:
        if 'lifetime' not in stats:
            stats['lifetime'] = {
                'instapaper': {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0},
                'rss': {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0},
            }
        backfill(stats)
        return

    metrics = compute_metrics(stats)

    if args.json:
        output = {
            'autonomy_level': stats.get('autonomy_level', 0),
            'level_name': LEVELS.get(stats.get('autonomy_level', 0), {}).get('name', 'Unknown'),
            **metrics,
            'review_ignored_passes': stats.get('review_ignored_passes', 0),
            'last_review_ignored': stats.get('last_review_ignored'),
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print_dashboard(stats, metrics)


if __name__ == '__main__':
    main()
