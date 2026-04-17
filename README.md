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
| [slides](#slides) | MARP slide decks to PDF, PPTX, Google Slides | `/slides` |
| [muck](#muck) | Fight AI slop: spot, guard, clean, learn voice | `/muck:spot` `/muck:guard` `/muck:clean` `/muck:voice` |
| [curaitor](#curaitor) | Article discovery, triage, and review | `/cu:triage` `/cu:discover` `/cu:review` `/cu:read` |
| [offload](#offload) | Session memory, prompt logging, context analysis | `/offload:context` `/offload:export` `/offload:summarize` |

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

Four tools for fighting AI slop: spot it, guard against it, clean it up, and learn your voice.

**Commands:**

| Command | Purpose | When to use |
|---------|---------|-------------|
| `/muck:spot` | Detect slop | Before submitting — "how sloppy is this?" |
| `/muck:guard` | Prevent slop | Configuring CLAUDE.md or skill preambles |
| `/muck:clean` | Remove slop | After drafting — rewrite with human voice |
| `/muck:voice` | Learn your voice | Periodically — teach muck how you write |

**Features:**
- 62 Tier 1 flagged words + 38 Tier 2 + 16 Tier 3 + 42 banned phrases
- Mechanical detection script (runs outside LLM, saves tokens)
- Voice presets: crisp, warm, expert, story
- Context profiles: linkedin, blog, technical, email, docs, casual
- Voice learning from writing samples + feedback loop from edits
- Guard mode emits compact anti-slop instructions for any CLAUDE.md

**Requirements:**
- Python 3.9+ with `pyyaml` (`pip install pyyaml`)

**Usage:**
```
/muck:spot draft.md                          # Detect slop
/muck:clean draft.md --preset crisp          # Rewrite to remove slop
/muck:guard --format section                 # Anti-slop CLAUDE.md block
/muck:voice --learn essay.md blog.md         # Learn your voice
/muck:voice --feedback output.md edited.md   # Refine from your edits
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

### offload

Session memory persistence, prompt logging, and context analysis. Hooks fire automatically on PreCompact, SessionEnd, and UserPromptSubmit (prompt logging is opt-in).

**Features:**
- PreCompact hook injects git state + reminder so learnings survive compaction
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

## License

MIT (unless otherwise noted per plugin)
