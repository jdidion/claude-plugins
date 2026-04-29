---
name: review
description: Multi-provider code review. Default scope is everything since the last time /crew:review ran on this branch (or the full repo on the first run). Runs Claude plus Cursor-provided models (GPT, Gemini, Grok, etc.) in parallel and merges attributed findings. Use --local to review only local changes, or --mr/--pr to review a GitLab MR or GitHub PR. Trigger when the user asks to review code, run a multi-model review, check my changes, or post a review to an MR.
---

Run a multi-provider code review. One command, three scopes:

| Scope | Trigger | What it reviews |
|---|---|---|
| **incremental** (default) | no flag | all commits since the last time this skill ran on the current branch, or the whole repo on the first run |
| **local** | `--local` | staged + unstaged changes only |
| **MR/PR** | `--mr N` or `--pr N` | the diff of the specified GitLab MR or GitHub PR |

All three use the same reviewer roster, the same prompt assembly, and the same merge/attribution logic. Only the diff-capture step differs.

## Arguments

`$ARGUMENTS` accepts, in any order:

- **Scope** (at most one):
  - `--local` — review local (staged + unstaged) changes only.
  - `--mr <N>` or `--pr <N>` — review the specified GitLab MR IID or GitHub PR number.
  - (no scope flag) — incremental default: diff since the last run (or whole repo on first run).
- **Model overrides**: `with <model-a> and <model-b>`, or `with only <model>`. Names are Cursor model IDs (`gpt-5`, `gemini-3.1-pro`, `grok-4-20-thinking`, `claude-*`, etc.). Ambiguous names: run `cursor-agent models`, filter, and ask the user.
- **`--deep`** — report every finding, all severities, no caps. Default caps at 10 findings, 3 suggestions, and hides cosmetic nits.
- **Post-and-monitor intent** (MR/PR mode only) — natural-language phrasing like "post and monitor", "submit and watch", "publish and follow up". Parse by intent, not fixed keywords. Only valid when `--mr`/`--pr` is given.

## Backend routing

Non-Claude models run through pluggable backend scripts under `${CLAUDE_PLUGIN_ROOT}/tools/backends/`. Each implements the same interface:

```
<backend> --prompt-file <path> [--model <id>] [--workspace <path>]
```

Prints `WORKDIR=<path>` on stdout and writes `reply.txt` inside the workdir.

**Per-model routing** is decided by `${CLAUDE_PLUGIN_ROOT}/tools/resolve-backend <model-id>`, which prints the absolute path to the backend that handles that model. Resolution order:

1. User config at `~/.config/crew/config.toml` under `[model_routing]` (glob patterns, first match wins)
2. Built-in prefix table: `gpt-*` → codex→cursor, `gemini-*` → gemini→cursor, `grok-*` → cursor, `claude-*` → anthropic-api→cursor, `llama*`/`mistral*`/`qwen*` → ollama
3. Fallback to `cursor` if installed (broad model support via Cursor's gateway)

The resolver picks the first backend in each list whose CLI is on PATH. Users get correct behavior without configuration as long as they have at least one relevant CLI installed.

### Shipped backends

| Backend | Status | Required binary |
|---|---|---|
| `cursor` | Full | `cursor-agent` |
| `codex` | Stub (CLI shape unverified) | `codex` |

Additional backends (`gemini`, `ollama`, `anthropic-api`) are tracked as issues. Any file in `tools/backends/` that honors the interface contract works — no plugin-side change required.

### Default roster

Run `resolve-backend --defaults` to get the default model list:

1. **Claude** — via the `code-reviewer` agent (no external backend).
2. **`gpt-5`** — routed by the resolver.
3. **`gemini-3.1-pro`** — routed by the resolver.

Override via config:
```toml
[defaults]
roster = ["claude", "gpt-5.1", "gemini-3.2-pro"]
```

Per-invocation override:
```
/crew:review with gpt-5 and gemini-3.1-pro
/crew:review with only gpt-5
```

If the user asks for a model no installed backend can handle, stop and tell them. Use `resolve-backend --list-available` to name the installed backends.

## State file (incremental mode)

Last-reviewed commit per branch is stored outside the tree:

```
.git/crew-review-state.json
```

Format:
```json
{
  "branches": {
    "<branch>": { "last_reviewed_sha": "<sha>", "ts": "<iso8601>" }
  }
}
```

The file lives in `.git/`, so it is per-worktree and survives rebases / tree rewrites that rewrite the working-tree copy. It is never committed.

## Workflow

### 1. Parse `$ARGUMENTS`

Determine:
- `SCOPE` ∈ `{incremental, local, mr, pr}`.
- `MR_ID` (if mr/pr scope).
- `DEEP=1` or `DEEP=0`.
- `ROSTER` — list of `(model_id, backend)` tuples after parsing overrides. If none specified, use the default roster above.
- `POST_AND_MONITOR=1` if the user expressed intent AND scope is `mr`/`pr`. Otherwise 0.

### 2. Capture the diff

Write the diff to a temp file `DIFF_FILE`. Capture:
- `DIFFSTAT` = `git diff --stat <range>` (or equivalent for the scope)
- `TITLE` — branch name, MR/PR title, or a short description of the scope
- `DESCRIPTION`, `COMMITS` — only populated for MR/PR mode

Per-scope rules:

**`local`:**
```bash
git diff HEAD > "$DIFF_FILE"    # staged + unstaged combined
DIFFSTAT=$(git diff --stat HEAD)
TITLE="$(git rev-parse --abbrev-ref HEAD) (local changes)"
```

**`mr` / `pr`:**

For `mr` (GitLab):
```bash
glab mr view "$MR_ID"
glab mr diff "$MR_ID" > "$DIFF_FILE"
```
Capture title, description, source branch, target branch, commit list.

For `pr` (GitHub):
```bash
gh pr view "$MR_ID" --json title,body,headRefName,baseRefName,commits
gh pr diff "$MR_ID" > "$DIFF_FILE"
```

Then enter a worktree on the MR/PR's source branch (see §2a).

**`incremental`:**

```bash
CUR_BRANCH=$(git rev-parse --abbrev-ref HEAD)
LAST_SHA=$(python3 -c "
import json, pathlib, sys
p = pathlib.Path('.git/crew-review-state.json')
if not p.exists():
    sys.exit(1)
data = json.loads(p.read_text())
br = data.get('branches', {}).get('$CUR_BRANCH')
if not br: sys.exit(1)
print(br['last_reviewed_sha'])
" 2>/dev/null)

if [ -n "$LAST_SHA" ] && git cat-file -e "$LAST_SHA^{commit}" 2>/dev/null; then
    # Incremental: diff from last-reviewed to HEAD.
    git diff "$LAST_SHA..HEAD" > "$DIFF_FILE"
    DIFFSTAT=$(git diff --stat "$LAST_SHA..HEAD")
    TITLE="$CUR_BRANCH (since $(git rev-parse --short "$LAST_SHA"))"
else
    # First run on this branch (or stored SHA is gone): review the whole current tree.
    ${CLAUDE_PLUGIN_ROOT}/tools/snapshot-diff --repo-root "$(pwd)" > "$DIFF_FILE"
    DIFFSTAT=$(git ls-files | wc -l | awk '{printf "%s tracked files\n", $1}')
    TITLE="$CUR_BRANCH (full snapshot)"
fi
```

If `SCOPE=incremental` and `HEAD` equals the stored `last_reviewed_sha` exactly, tell the user there is nothing new to review since the last run and offer `--local` or explicit scope. Stop.

### 2a. (MR/PR only) Enter a worktree on the source branch

Use `EnterWorktree` with name `crew-review-<scope>-<id>`. Then:
```bash
git fetch origin <source-branch>
git checkout <source-branch>
```

Do all subsequent work from the worktree. For `local` and `incremental` scopes, skip the worktree — those run in-place.

### 3. Assemble the review prompt

```bash
${CLAUDE_PLUGIN_ROOT}/tools/assemble-review-prompt \
  --diff "$DIFF_FILE" \
  --repo-root "$REPO_ROOT" \
  --title "$TITLE" \
  ${DESCRIPTION:+--description "$DESCRIPTION"} \
  ${COMMITS:+--commits "$COMMITS"} \
  --stat "$DIFFSTAT" \
  ${DEEP:+--deep}
```

Capture the printed workdir as `PROMPT_DIR`.

### 4. Resolve each model to a backend; adapt the repo if needed

For every non-Claude model in the roster, resolve the backend script:

```bash
for model in <roster>; do
    [ "$model" = "claude" ] && continue
    BACKEND=$(${CLAUDE_PLUGIN_ROOT}/tools/resolve-backend "$model")
    # Record (model, backend) pairs for Step 5.
done
```

If any resolved backend is the cursor script, run the cursor adapter first (it creates an `AGENTS.md` symlink and translates `.mcp.json`):

```bash
if [ <any backend ends in /cursor> ]; then
    ${CLAUDE_PLUGIN_ROOT}/tools/cursor-adapt setup --repo-root "$REPO_ROOT"
fi
```

The adapter is idempotent and tracks what it creates so cleanup only removes what setup added. Other backends don't need adaptation.

### 5. Launch external models in parallel (background)

For each resolved `(model, backend)` pair, invoke the backend:

```bash
"$BACKEND" \
  --prompt-file "$PROMPT_DIR/prompt.md" \
  --model "$model" \
  --workspace "$REPO_ROOT"
```

Each invocation prints `WORKDIR=<path>` on stdout. Save the workdirs; read `<workdir>/reply.txt` later. All backends implement the same interface — the skill does not need per-backend branching.

Report the backend each model used in the header of the final output so the user can audit routing (e.g. `gpt-5 → codex, gemini-3.1-pro → cursor`).

### 6. Run Claude's review in parallel

Delegate to the `code-reviewer` agent in an isolated context:

```
Agent(subagent_type: "crew:code-reviewer",
      prompt: "<pass $PROMPT_DIR/prompt.md and deep flag>")
```

Save the returned findings string to a file so `merge-findings` can consume it uniformly.

### 7. Wait for all reviewers

- Claude: the agent's returned string (written to a file).
- Each external model: `<workdir>/reply.txt`.

If any reviewer failed (non-zero exit, empty reply, timeout), note it in the merged report and continue. Do not hard-fail the whole review because one model timed out.

### 8. Merge

```bash
${CLAUDE_PLUGIN_ROOT}/tools/merge-findings \
  --out "$MERGE_OUT" \
  --reply "Claude:$CLAUDE_REPLY" \
  --reply "<model-a>:<workdir-a>/reply.txt" \
  --reply "<model-b>:<workdir-b>/reply.txt"
```

Writes `merged.md` (full per-reviewer reports + overlap hints) and `agreements.md` (machine-readable clusters). Attribute findings:

- `[All]` — every reviewer flagged it.
- `[<A>+<B>]` — two-of-three overlap.
- `[<reviewer>]` — single-source.
- `[<reviewer> — likely false positive: <reason>]` — single-source findings you've checked against the source and judged wrong.

Don't silently drop findings from external reviewers; tag them.

### 9. Cleanup

```bash
${CLAUDE_PLUGIN_ROOT}/tools/cursor-adapt cleanup --repo-root "$REPO_ROOT"
```

For MR/PR scope: **before** entering post-and-monitor mode, `ExitWorktree action=remove discard_changes=true`. Don't post from inside a worktree.

### 10. Update state (incremental scope only)

Record the reviewed SHA so the next incremental run starts from here:

```bash
python3 - <<PY
import json, pathlib, datetime
p = pathlib.Path('.git/crew-review-state.json')
data = json.loads(p.read_text()) if p.exists() else {}
data.setdefault('branches', {})['$CUR_BRANCH'] = {
    'last_reviewed_sha': '$(git rev-parse HEAD)',
    'ts': datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
p.write_text(json.dumps(data, indent=2) + '\n')
PY
```

Skip this for `local` and `mr`/`pr` scopes — state tracks branch-level review progress, not one-off reviews.

### 11. Present the merged review

Header:
```
**Multi-provider review** [<scope-label>]: <list of reviewers> | <N> findings
(<A> all reviewers, <B> two-of-three, <C> single-source)
```

`<scope-label>` is one of: `local`, `MR !<N>`, `PR #<N>`, `since <short-sha>`, or `full snapshot`.

Then findings ordered `CRITICAL → WARNING → SUGGESTION` (plus `NIT` in `--deep`), each tagged. Testing section + Verdict at the end.

## Post-and-monitor (MR/PR scope only)

**Only when the user explicitly asked.** Skip this entire section otherwise.

### Post the review

1. Extract the project path from `git remote get-url origin` (e.g. `group/project` or `org/repo`).
2. For each finding: post a separate discussion thread:
   - GitLab: `gitlab_create_merge_request_discussion`, positioned on the relevant file and line when possible.
   - GitHub: `gh pr review --comment` with file+line, or an equivalent PR-review-comment MCP tool.
3. For the summary: post as a general MR/PR note (not positioned on a file).
4. Include the attribution tag (`[All]`, `[Claude+gpt-5]`, etc.) in each posted comment.
5. Prefix every posted comment with 🤖.

### Monitor

1. Record the current UTC timestamp.
2. Poll for MR/PR activity periodically.
3. On activity:
   - **Author replied in a thread**: read the response. If the concern is addressed, resolve the discussion. Otherwise, reply (🤖-prefixed). If unclear, ask the user.
   - **New commits pushed**: fetch the latest diff; for each prior finding, check if it's fixed. Resolve threads that are fixed, comment on those that aren't, and post new threads for any new issues you can verify.
   - **MR/PR merged or closed**: stop monitoring.
4. Stop after 3 consecutive polls with no actionable activity, or immediately if any note contains "stop monitoring" or "ask your user".

## Rules

- Always run your own review (via the `code-reviewer` agent). Don't just aggregate external models.
- Never post to GitLab/GitHub in default mode — only when the user explicitly asked for post-and-monitor AND the scope is `mr`/`pr`.
- Respect project-specific review guidance in `CLAUDE.md`/`AGENTS.md` and `.ci/ai-review/review-prompt-template.txt`.
- History-aware: use `git blame` / `git log` on changed regions before flagging.
- Prefer parallelism: assemble → launch external models in background → launch Claude agent → wait for all → merge. Total latency is max(reviewer), not sum.
- If Cursor auth fails, tell the user to run `cursor-agent login` in a fresh terminal and stop. Do not work around auth.
- `--deep` is a global flag across all scopes.
- `--local` and `--mr`/`--pr` are mutually exclusive; if both are given, stop and ask.
