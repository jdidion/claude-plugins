---
name: market
description: Run N independent agents on the SAME task in parallel with NO shared context or planner, then a cheap judge (deterministic oracle or LLM) picks the winner. Use for brittle reasoning where one model often errs, tasks with a cheap oracle (tests/schema/regex), or research queries where diverse phrasings help. Complements /crew:review's hub-spoke flow with a Hayek-style market topology — independent retries surface answers a central planner never reaches. Reply is text-only; file-modification-per-candidate comes in a later version.
---

# /crew:market — Market topology for parallel agent races

Spawn N agents on the same prompt with **no cross-visibility**, collect their outputs, and pick a winner via deterministic oracle or cheap LLM judge. Empirical result from the Coase/Hayek-topology paper: for brittle reasoning with cheap grading, market beats hub-spoke on cost (~4×) *and* quality, and surfaces answers no single model or planner reaches.

This is the **market** spoke of crew's three-topology vision. Hub-spoke lives in `/crew:review`; the topology router `/crew:do` wires them together.

## When to use

- Brittle reasoning: one model often gets it wrong (LeetCode-style puzzles, subtle regex, dense math).
- Tasks with a cheap oracle: tests pass, schema validates, regex matches, exact-string match.
- Research queries where "what does the literature say" benefits from diverse phrasings.

## When NOT to use

- Long-horizon coding with global state — handoffs lose information, use `/crew:review` or a single agent.
- Expensive-to-judge tasks — if the only correctness signal is expensive human review, the market's cheap-judge advantage evaporates.
- Tasks smaller than the spawn overhead — just ask Sonnet directly.
- In-place file modifications — **not supported yet**. Candidates return text only. File-modification-per-candidate with isolated workspaces is a Phase 1.5 follow-up.

## Arguments

`$ARGUMENTS` — `<task> [--n <N>] [--models <a,b,c>] [--judge <model>] [--deterministic <cmd>]`

- `<task>` — the prompt. Everything up to the first `--` flag is the task (quote it if it contains flag-looking tokens).
- `--n <N>` — number of agents. Default 3. Paper says 3–5 is the sweet spot; >5 is diminishing returns.
- `--models <list>` — comma-separated model IDs. Default: `claude,gpt-5.2,gemini-3.1-pro`. Ignored if the list length doesn't equal `--n`; in that case, `--n` wins and the skill takes the first N from the list (cycling if fewer).
- `--judge <model>` — LLM judge model. Default `haiku`. Ignored if `--deterministic` is given.
- `--deterministic <cmd>` — shell command used as the oracle. Runs once per candidate with `{}` in the command replaced by a path to a temp file holding the candidate's text. Exit 0 = pass; non-zero = fail. Winners = set of passing candidates. If multiple pass, prefer shortest response. If no command contains `{}`, the candidate text is piped to the command's stdin instead.

### Diversity rule

**Different models, not different prompts.** Opus × 3 ≈ one Opus. Real value requires different model *families* — mix Claude, OpenAI (`gpt-5.2`, `gpt-5.4-high`), Google (`gemini-3.1-pro`), xAI (`grok-4-20-thinking`), Cursor-hosted (`composer-2`).

## Backend routing

Same system as `/crew:review`:

| Model | Backend |
|---|---|
| `claude` (bare) | In-process `code-reviewer` agent — no external CLI, uses Claude Code's configured Claude model |
| Everything else | `${CLAUDE_PLUGIN_ROOT}/tools/resolve-backend <model>` returns the backend script path; invoke it with `--prompt-file`, `--model`, `--workspace` |

The resolver consults `~/.config/crew/config.toml`'s `[model_routing]` table (user overrides), then the built-in prefix table (e.g. `gpt-*` → codex if installed, else cursor), then falls back to cursor if installed.

## Workflow

### 1. Parse `$ARGUMENTS`

Tokenize into `TASK`, `N`, `MODELS[]`, `JUDGE`, `DETERMINISTIC`. Resolve defaults. Resolve each model to its backend via `resolve-backend`. Fail fast if `N < 1` or `MODELS` is empty.

### 2. Validate the roster

```bash
# Full MODELS list, including "claude"; validate-roster knows to skip
# in-process entries and backends whose catalogs it can't introspect.
"${CLAUDE_PLUGIN_ROOT}/tools/validate-roster" "${MODELS[@]}" || exit 1
```

Same tool as `/crew:review` §4a. Exits 1 if any model is confirmed absent from its backend's catalog. Skips with a warning when the backend CLI isn't introspectable — validation is defense-in-depth, not a hard requirement.

### 3. Spawn N independent agents in parallel

**Critical**: agents must NOT see each other's output. This is what makes it a market vs a committee.

- **Claude-backed candidates** (bare `claude` in the roster): launch via `Agent()` with `run_in_background: true`, the plugin's `code-reviewer` subagent in "freeform" mode, and a prompt containing *only* the task. Do not mention that other agents are running. Do not pass any shared planner output.
- **Non-Claude candidates**: resolve the backend once, then invoke in the background:
  ```bash
  BACKEND=$("${CLAUDE_PLUGIN_ROOT}/tools/resolve-backend" "<model>")
  "$BACKEND" \
    --prompt-file "$TASK_FILE" \
    --model "<model>" \
    --workspace "$(pwd)" &
  ```
  Capture each PID and each `WORKDIR=` line the backend prints so reply paths are reachable later.

Each candidate runs to completion independently. No timeouts in v1 — add `--timeout` if runaway candidates become a problem.

### 4. Collect candidate outputs

Wait for all spawns to complete.

- Claude-backed: the `Agent()` returned string is the output. Write to `/tmp/crew-market-<slug>/candidate-<i>.txt`.
- Non-Claude-backed: read `<workdir>/reply.txt`. Copy or symlink to the same temp dir.

Name each file `candidate-<i>-<model>.txt` so the judge sees unambiguous labels.

If any candidate failed (empty reply, non-zero exit, subagent error), note it in the final report and **exclude from judging**, but don't hard-fail the whole run unless *all* candidates failed.

### 5. Judge

#### Deterministic oracle (if `--deterministic` given)

For each candidate file:

```bash
if [[ "$DETERMINISTIC" == *"{}"* ]]; then
    cmd="${DETERMINISTIC//\{\}/$candidate_file}"
    bash -c "$cmd" && PASSING+=("$candidate_file")
else
    bash -c "$DETERMINISTIC" < "$candidate_file" && PASSING+=("$candidate_file")
fi
```

- 0 passing → report "no candidate satisfied oracle"; print all outputs for human review.
- 1 passing → that's the winner.
- 2+ passing → prefer shortest response (byte count of the text).

Record each candidate's pass/fail status for the final report.

#### LLM judge (default, when no `--deterministic`)

Spawn a single judge agent using `$JUDGE` (default `haiku`) with the prompt:

```
You are judging N candidate answers to the same task. Your job is to
pick the best one. Be strict: one winner, one-sentence rationale,
no equivocation.

Task:
<TASK verbatim>

Candidate A (<model_a>):
<candidate A text>

Candidate B (<model_b>):
<candidate B text>

Candidate C (<model_c>):
<candidate C text>

Respond in this exact format:
WINNER: <letter>
RATIONALE: <one sentence>
```

Parse the response. If the judge refuses to pick one, log "judge abstained" and present all candidates to the user as a tie.

### 6. Report

Print a single summary:

```
Market: <N> candidates on "<TASK (truncated)>"

WINNER: candidate-<i> (<model>) via <deterministic|judge-<model>>
RATIONALE: <one-line rationale>

Full winner:
<winner text>

---
Candidates:
  A. <model_a> [PASS / FAIL / winner]  (N bytes, ~$X.XX)
  B. <model_b> [PASS / FAIL]
  C. <model_c> [PASS / FAIL]

Losing candidates printed below (collapse in reader if supported):

=== candidate-A (<model_a>) ===
<text>

=== candidate-B (<model_b>) ===
<text>

=== candidate-C (<model_c>) ===
<text>
```

Keep per-candidate outputs so the user can override the judge's pick if they disagree.

## Cost estimation

Approximate total cost = sum of per-candidate spawn costs + judge cost. For each Claude-backed candidate, use a rough heuristic (input + output tokens × per-model rate). Skip exact accounting in v1 — just label "(cost estimate: ~$X.XX)" and note in the report that it's approximate.

## Rules

- **No cross-visibility.** Never pass one candidate's output into another candidate's prompt.
- **Different models, not different prompts.** Rejecting `--models opus,opus,opus` would be pedantic, but warn the user that the market's diversity advantage requires family diversity.
- **Claude counts as a family.** Different backend-hosted providers (codex for GPT, cursor for Grok, gemini for Gemini) each count as their own family. Prefer rosters that mix at least two families.
- **Don't judge with a family member.** If `--judge haiku` and `haiku` is one of the candidate models, the judge has a bias. Warn and continue; the user explicitly chose the judge.
- **Deterministic beats LLM.** If the task has any cheap oracle, pass `--deterministic` — LLM judges are approximate and have failure modes the paper didn't fully characterize.
- **Text only in v1.** If the task requires file modifications, tell the user to use `/crew:review` (hub-spoke) or wait for file-modification mode in the Phase 1.5 follow-up.

## Known limitations

- No per-candidate cost cap (`--max-cost`) yet. Runaway candidates aren't killed.
- No retry-on-upstream-error. If a backend call hits a transient error, that candidate just fails — no fallback. The fallback-chain feature is separate design work.
- No streaming display. Candidates run to completion in the background; the user sees the summary at the end, not progress.
- No workspace isolation. Candidates can't modify files safely; they return text.
