# claude-plugins

A [Claude Code plugin marketplace](https://docs.anthropic.com/en/docs/claude-code/plugins) with tools for presentations, writing, article curation, and more.

## Installation

Add this marketplace to Claude Code:

```
/plugin marketplace add jdidion/claude-plugins
```

Then install individual plugins:

```
/plugin install slides@jdidion-plugins
/plugin install muck@jdidion-plugins
```

## Plugins

| Plugin | Description | Commands |
|--------|-------------|----------|
| [slides](#slides) | MARP / Typst slide decks to PDF, PPTX, Google Slides | `/slides` |
| [muck](#muck) | Fight AI slop: spot, guard, clean, learn voice, generate | `/muck:spot` `/muck:guard` `/muck:clean` `/muck:voice` `/muck:gen` |
| [curaitor](#curaitor) | Article discovery, triage, and review | `/cu:triage` `/cu:discover` `/cu:review` `/cu:read` |
| [crew](#crew) | Multi-provider code review with attribution | `/crew:review` `/crew:market` `/crew:do` |
| [handoff](#handoff) | AirDrop-style context transfer + interactive teams | `/handoff:send` `/handoff:inbox` `/handoff:team` `/handoff:bridge` |
| [offload](#offload) | Session memory, prompt logging, context analysis | `/offload:context` `/offload:export` `/offload:summarize` |
| [ed](#ed) | Open a file in an editor / viewer / OS app from a Claude session | `/ed:edit` `/ed:view` `/ed:open` |

---

### slides

Create [MARP](https://marp.app/) markdown slide decks and convert to PDF, HTML, PPTX, and Google Slides with visual validation.

**Features:**
- Teal/white theme with consistent styling across all output formats
- Two-column layouts, markdown tables, code blocks, images
- Custom MARP-to-PPTX converter using python-pptx
- Mermaid diagram rendering to PNG
- PPTX visual validation via Keynote (macOS)
- Google Slides upload via Drive API

**Requirements:**
- Node.js (for MARP CLI and Mermaid CLI)
- Python 3.9+ with `python-pptx` (`pip install python-pptx`)
- Keynote (macOS, optional — for PPTX visual validation)

**Usage:**
```
/slides deck.md pptx          # Convert to PPTX
/slides deck.md pdf            # Convert to PDF
/slides deck.md all            # Convert to all formats
/slides new talk.md            # Create a new slide deck
/slides diagram flow.mmd       # Render Mermaid diagram to PNG
```

---

### muck

Five tools for fighting AI slop: spot it, guard against it, clean it up, learn your voice, and generate it (for testing).

**Commands:**

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/muck:spot` | Detect slop | Before submitting — "how sloppy is this?" |
| `/muck:guard` | Prevent slop | Configuring CLAUDE.md or skill preambles |
| `/muck:clean` | Remove slop | After drafting — rewrite with human voice |
| `/muck:voice` | Learn your voice | Periodically — teach muck how you write |
| `/muck:gen` | Generate sloppy text | Building/regression-testing the spot/clean pipelines |

**Features:**
- 62 Tier 1 flagged words + 38 Tier 2 + 16 Tier 3 + 42 banned phrases
- Mechanical detection script (runs outside LLM, saves tokens)
- Voice presets: crisp, warm, expert, story
- Context profiles: linkedin, blog, technical, email, docs, casual
- Voice learning from writing samples + feedback loop from edits
- `/muck:voice --learn` and `/muck:clean --voice` accept HTTP(S) URLs and Google Drive refs alongside local paths
- Guard mode emits compact anti-slop instructions for any CLAUDE.md

**Requirements:**
- Python 3.9+ with `pyyaml` (`pip install pyyaml`)
- `gws` CLI on PATH (only if you use Google Drive sources)

**Usage:**
```
/muck:spot draft.md                                       # Detect slop
/muck:clean draft.md --preset crisp                       # Rewrite to remove slop
/muck:clean draft.md --voice https://blog/canonical-post/ # Match a specific blog's voice
/muck:guard --format section                              # Anti-slop CLAUDE.md block
/muck:voice --learn essay.md https://blog/post/           # Learn from local + remote sources
/muck:voice --feedback output.md edited.md                # Refine from your edits
```

---

### curaitor

> Licensed under the [Elastic License 2.0](plugins/curaitor/LICENSE.md). Free to use. See license for details.

AI-powered article discovery, triage, and interactive review. Automates finding and filtering articles while keeping you in the loop for what matters.

**Features:**
- Three-tier confidence routing (Inbox / Review / Ignored) with progressive autonomy
- Interactive review in cmux browser with deep-read RAG discussion
- Instapaper, RSS/Feedly, and social network (Sill) sources
- Zotero integration, Obsidian topic graph, preference learning from every verdict

**Requirements:**
- [Obsidian](https://obsidian.md) with MCP server
- Python 3 with `requests-oauthlib` and `pyyaml`
- [cmux](https://cmux.dev) (optional, for interactive browser review)

**Usage:**
```
/cu:triage          # Process Instapaper saves
/cu:discover        # Surface articles from RSS feeds
/cu:review          # Interactive review session
/cu:read            # Deep reading with RAG discussion
/cu:review-ignored  # Check for false negatives
```

---

### crew

Multi-provider code review for Claude Code. Runs Claude alongside other model families (GPT, Gemini, Grok, local models) in parallel through pluggable backends, then merges findings with attribution so you can see which model caught what.

**Why multi-provider?** Same-context self-review suffers from choice-supportive bias — once a model sees its own output, it inflates confidence and defends the original answer. Different model families catch different issues; three reviewers with attribution beats one reviewer with more thinking. Deterministic `lsp_diagnostics` and `ast_grep` pre-gates run before any LLM is invoked.

**Commands:**

| Command | Topology | What it does |
|---|---|---|
| `/crew:review` | Hub-spoke | Multi-provider code review with attribution — incremental, local, MR, or PR scopes; optional post-and-monitor on MR/PR |
| `/crew:market` | Market | Run N independent agents on the same prompt; deterministic oracle or Haiku judge picks the winner |
| `/crew:do` | Router | Auto-pick the topology from task shape (heuristic classifier; `--topology` override always wins) |

**Default roster:** Claude (via the bundled `code-reviewer` agent), `gpt-5.2`, `gemini-3.1-pro`. Override per-invocation (`with gpt-5.2 and grok-4-20-thinking`) or globally via `~/.config/crew/config.toml`.

**Requirements:**
- Backend CLIs for non-Claude models (`cursor-agent`, `gemini`, etc.) — pluggable scripts under `tools/backends/`
- `glab` / `gh` for MR / PR scopes

**Usage:**
```
/crew:review                                          # Incremental: commits since last run
/crew:review --local                                  # Staged + unstaged only
/crew:review --mr 123 with claude and gpt-5.2         # MR review with custom roster
/crew:review --pr 456 --deep post and monitor         # Full report, posted, watched
/crew:market "<task>" --n 3 --judge haiku             # 3-way market with LLM judge
/crew:do "<task>" --topology auto                     # Let crew pick the topology
```

---

### handoff

AirDrop-style context transfer between Claude Code sessions, plus interactive team coordination with shared messaging and tasks.

**Commands:**

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/handoff:send` | Send context to another session | "Pass this to the Prism session" |
| `/handoff:inbox` | Check for incoming handoffs | Start of session, or when notified |
| `/handoff:register` | Register session for discovery | Once per session (or auto via hook) |
| `/handoff:team` | Create/manage interactive teams | Parallel work across multiple sessions |
| `/handoff:bridge` | Join a running team externally | Connect to a team from any cmux pane |

**Features:**
- Structured markdown handoff files (objective, context, files, next steps)
- Delivery via cmux send (types into target session) + OS notification
- File-based team messaging compatible with Claude Code's native Agent Teams
- Bridge script lets external sessions participate in native team inboxes
- Team checkpoint/resume for long-running coordination
- YAML team definitions for repeatable setups
- Dynamic membership: add/remove teammates at any time

**Requirements:**
- [cmux](https://cmux.dev) (for cross-session delivery; file-only mode works without)
- Python 3

**Usage:**
```
/handoff:register prism-dev                                    # Register this session
/handoff:send "review variant filter changes" --to curaitor    # Send context
/handoff:inbox                                                 # Check incoming

/handoff:team create sgnipt-sprint                             # Create a team
/handoff:team add variant-filter --cwd ~/projects/sgnipt       # Add interactive teammate
/handoff:bridge sgnipt-sprint pipeline-tests                   # Join from another session
```

**Install:**
```
/plugin marketplace add jdidion/claude-plugins
/plugin install handoff@jdidion-plugins
```

---

### offload

Session memory persistence, prompt logging, and context analysis. Hooks fire automatically on PreCompact, SessionEnd, and UserPromptSubmit (prompt logging is opt-in).

**Features:**
- PreCompact hook injects git state + directs Claude to invoke `/offload:context` (which preserves learnings, then chains to `/compact`) instead of compacting directly
- SessionEnd hook persists session snapshot for future pickup
- Opt-in prompt logging to JSONL for trend analysis
- Export prompts as JSONL, CSV, or Markdown
- Summarize offloaded context globally or per project/session

**Requirements:**
- `git` and `jq` on PATH

Hooks activate automatically when the plugin is enabled — no manual config needed.

**Usage:**
```
/offload:context                         # Save learnings + compact
/offload:context --enable-prompts        # Turn on prompt logging
/offload:export --format csv             # Export prompts as CSV
/offload:export --project myapp          # Filter by project
/offload:summarize                       # Global summary
/offload:summarize --project myapp       # Project summary
```

---

### ed

Open a file in your editor or viewer in a cmux terminal surface adjacent to the Claude Code conversation. Or hand it to the OS default app (Preview, Keynote, Finder) when terminal rendering doesn't help.

**Commands:**

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/ed:edit` | Open editor + optional hot-reload viewer pane | Iterate on a file while watching the rendered output |
| `/ed:view` | Open a single viewer pane (with editor read-only fallback) | Read-only browsing of a rendered file |
| `/ed:open` | Hand to OS default app | PDFs, .key, images, video — formats terminal viewers don't render well |

**Features:**
- Per-extension viewer config in `${XDG_CONFIG_HOME:-~/.config}/ed/config.toml` and per-repo `.ed.toml`
- Orientation-aware splits (horizontal vs. vertical monitor layouts)
- Editor + viewer split perpendicular to the Claude↔editor split
- Fallback ladder: extension viewer → default viewer → `$VIEWER` → editor read-only
- macOS-only: `--app <name>` and `--reveal` for `/ed:open`

**Requirements:**
- [cmux](https://cmux.dev) (for the terminal surfaces; `/ed:open` works without it on macOS / Linux)
- Editor of choice (helix, micro, nano, vim, emacs, etc.)

**Usage:**
```
/ed:edit notes.md                        # Editor (+ live viewer if .md has one configured)
/ed:edit nano notes.md                   # Override editor for this invocation
/ed:view data.csv --live                 # Live-reload viewer (e.g. csvlens)
/ed:open report.pdf                      # Preview / xdg-open
/ed:open --reveal slide.key              # Highlight in Finder (macOS)
```

---

## License

MIT (unless otherwise noted per plugin)
