# /cu:status — CurAItor status dashboard

Quick overview of queue counts, cron health, accuracy metrics, and recent activity.

See [`protocol.md`](./protocol.md) for the execution protocol (Environment, Workflow, Conventions, Common Pitfalls).

## Arguments

$ARGUMENTS — Optional: `--verbose` for full detail including rolling window entries.

## At a glance

1. **Step 0 — drain the level-2 pending queue.** If `scripts/level2-queue.py status` reports `pending > 0`, process those articles with Claude *before* the status dashboard. They are articles that cron-Claude couldn't finalize (usually auth expiry). See protocol §Workflow Step 0.
2. Gather data with `scripts/prefetch-review.py`, `scripts/accuracy-metrics.py`, and tail commands (see protocol §Workflow Step 1).
3. Print a one-screen dashboard (protocol §Workflow Step 2).
4. Suggest next actions (protocol §Workflow Step 3).

Output cap: one screen, no scrolling. Save tokens by using scripts, not reading individual notes.
