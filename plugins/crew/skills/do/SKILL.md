---
name: do
description: Topology router for multi-agent tasks. Given a task description, classify its shape (global-state vs independent-subtasks vs brittle-reasoning-with-oracle) and dispatch to the right topology — solo, market, or hub-spoke (which today means pointing you at /crew:review). Use when you want the "right way" to run a task without picking the topology yourself. --topology <choice> overrides auto-detection.
---

# /crew:do — Topology router for multi-agent tasks

Task shape determines which topology wins. Hand-picking is error-prone — pick market for a task that needs global coherence and you'll get garbage; pick solo for a brittle-reasoning task and you waste the "independent retries" win. This skill picks for you.

Based on the Coase/Hayek-topology paper's decision table:

| Task shape | Best topology | Why |
|---|---|---|
| One global state, many invariants | Solo | Handoffs lose information |
| Clean independent subtasks | Hub-spoke | Decomposition is cheap |
| Brittle answer, easy-ish judging | Market | Retry and diversity help |
| Long-running agents with divergent memories/tools | Market or hybrid | Local production info matters |

## Current dispatch status

- **solo** → spawns a single agent with the user's chosen model. Implemented.
- **market** → delegates to `/crew:market`'s spawn-and-judge flow. Implemented.
- **hub-spoke** → emits guidance pointing at `/crew:review` for code review, or (for non-review hub-spoke tasks) a note that generalized hub-spoke isn't yet factored out of `/crew:review`. Not a full dispatch.
- **hybrid** → **not implemented**. Router will warn and fall back to whichever non-hybrid topology it ranks second-best for the task.

Treat this skill as an experimental shim. The classifier is heuristic — validate its picks against your own sense for the task before committing. The explicit `--topology <choice>` escape hatch always wins over auto-detection.

## Arguments

`$ARGUMENTS` — `<task> [--topology auto|solo|market|hub-spoke|hybrid] [--n <N>] [--models <list>] [--judge <model>] [--deterministic <cmd>]`

- `<task>` — the prompt or task description. Everything before the first `--` flag.
- `--topology` — default `auto`. Explicit value skips classification.
- Market-passthrough flags (`--n`, `--models`, `--judge`, `--deterministic`) — forwarded verbatim to `/crew:market` when that topology is chosen. Ignored for solo and hub-spoke.

## Workflow

### 1. Parse `$ARGUMENTS`

Tokenize `TASK`, `TOPOLOGY_OVERRIDE`, and the passthrough flags. If `TOPOLOGY_OVERRIDE` is explicit, skip to §3.

### 2. Classify the task

Spawn a cheap classifier agent (default `haiku`) with this prompt:

```
You are classifying a software task to pick the best execution topology.
Read the task and return exactly ONE of these topology names:

  solo       — the task has global state, many invariants, or
               requires a coherent long-horizon plan. A single agent
               tracking everything wins.
  market     — the task is brittle (one model often gets it wrong)
               AND has a cheap correctness signal (tests, schema,
               regex, exact match). Run N independent agents and let
               the oracle pick.
  hub-spoke  — the task decomposes into clean independent subtasks
               a planner can divide and delegate. Code review is the
               canonical example.
  hybrid     — large tasks that benefit from market WITHIN hub-spoke
               branches, OR a mix of long-horizon coherence and
               brittle sub-steps.

Rules:
- Return a single word on a single line. No explanation unless the
  task is genuinely ambiguous, in which case add a one-line reason
  after the topology name.
- If the task is one-shot Q&A, research, or math, prefer "market"
  when "--deterministic" is plausible; otherwise "solo".
- Code-review-shaped tasks ("review this diff", "audit these
  changes") → "hub-spoke".
- Long-horizon feature work or refactors with cross-file invariants →
  "solo".

Task:
<TASK>
```

Parse the first word of the response. If not one of the four, log the unexpected output and fall back to `solo`.

### 3. Dispatch

#### solo

Spawn a single agent. Default model comes from the user's `--models` override, else the first entry of `resolve-backend --defaults` (typically `claude`).

- **`claude`** (bare): spawn via `Agent(subagent_type: "crew:code-reviewer", prompt: <TASK>)` in foreground. Or for non-review freeform tasks, a plain `Agent(model: "claude-...", prompt: <TASK>)` in foreground.
- **Non-Claude**: resolve the backend:
  ```bash
  BACKEND=$("${CLAUDE_PLUGIN_ROOT}/tools/resolve-backend" "<model>")
  "$BACKEND" --prompt-file "$TASK_FILE" --model "<model>" --workspace "$(pwd)"
  ```
  Read `<workdir>/reply.txt` for the response.

Return the response directly. No judge step.

#### market

Forward all passthrough flags to the `/crew:market` invocation:

```
Run /crew:market "<TASK>" [--n <N>] [--models <list>] \
                          [--judge <model>] [--deterministic <cmd>]
```

See `skills/market/SKILL.md` for full semantics.

#### hub-spoke

This topology's logic lives in `/crew:review` today and hasn't been factored out into a generic primitive. Route based on the task:

- **Task looks like code review** (mentions "review", "audit", "diff", "MR/PR number"): tell the user to run `/crew:review` (with appropriate scope flag — `--local`, `--mr N`, `--pr N`) and stop. Do not dispatch automatically; `/crew:review` needs context (current branch, MR metadata) that the router doesn't have.
- **Task is hub-spoke-shaped but not review**: report "Hub-spoke for non-review tasks is not yet supported in /crew:do. Fall back to `/crew:do --topology solo` or `/crew:do --topology market` (if the task has a cheap oracle)." Do not dispatch. Exit 0.

Do not fake a hub-spoke dispatch. Factoring the `/crew:review` pipeline into a generalized primitive is a Phase 4+ follow-up.

#### hybrid

Warn:

```
Hybrid topology is not yet implemented. Falling back to <second-choice>.
```

Pick the second-choice topology from the classifier's implicit hierarchy — for most tasks, that's `market` if a cheap oracle is available (check for `--deterministic`), else `solo`. Dispatch accordingly.

### 4. Report the dispatch

Before running the chosen topology, print one line:

```
Topology: <chosen> (auto-detected | explicit) — <brief rationale or "user-specified">
```

For `auto`, the rationale is the classifier's output (or the fallback reason if the classifier abstained).

## Rules

- **Explicit overrides are sacred.** `--topology <choice>` skips classification and dispatches directly. The classifier is only consulted when `--topology auto` (default).
- **Prefer dry-running.** When in doubt about the classifier's pick, the user can always rerun with an explicit topology. Surface the classification clearly so they can second-guess.
- **Classifier limits.** Haiku is cheap but not calibrated — it will mispick on edge cases. This skill is a convenience, not an oracle. The `--topology` escape hatch is load-bearing.
- **Hub-spoke gap is honest.** Today `/crew:review` is the only hub-spoke implementation. If you think your task fits hub-spoke but isn't review, that's a feature request for a future skill, not a failure of this router.
- **Cost.** One classifier call (~Haiku) + whatever the chosen topology costs. Classifier cost is ~$0.001 per run — negligible.

## Known limitations

- **No empirical validation of the classifier.** The prompt encodes the paper's decision table, but no labeled dataset has been used to tune it. Expect mispicks, especially on tasks that straddle categories. Build one if this is used in anger.
- **Hybrid topology is not implemented.** Stub with fallback.
- **Hub-spoke dispatch is advisory only.** Requires factoring hub-spoke out of `/crew:review`, which is a larger project.
- **No ensemble vote.** Could ask multiple cheap classifiers and majority-vote. Not done — adds latency for marginal confidence gain on a task that's already probabilistic.
