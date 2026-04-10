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

## License

MIT
