# claude-plugins

A [Claude Code plugin marketplace](https://docs.anthropic.com/en/docs/claude-code/plugins) with tools for presentations, data analysis, and more.

## Installation

Add this marketplace to Claude Code:

```
/plugin marketplace add jdidion/claude-plugins
```

Then install individual plugins:

```
/plugin install slides@jdidion-plugins
```

## Plugins

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

### curaitor

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

## License

MIT
