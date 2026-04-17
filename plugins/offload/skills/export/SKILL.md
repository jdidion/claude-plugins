# /offload:export — Export prompt log

Export the prompt log for external analysis.

## Arguments

$ARGUMENTS — Optional filters and format:
- `--project NAME` — filter by project directory name
- `--since YYYY-MM-DD` — only prompts after this date
- `--session SID` — filter by session ID
- `--format jsonl|csv|markdown` — output format (default: jsonl)

## Workflow

Run the export script:

```bash
bash <plugin_root>/scripts/export-prompts.sh $ARGUMENTS
```

If no prompts have been logged, inform the user they need to enable prompt logging first:

```bash
DATA_DIR="${CLAUDE_PLUGIN_DATA:-$HOME/.claude/plugins/data/offload}"
mkdir -p "$DATA_DIR"
echo '{"prompt_logging": true}' > "$DATA_DIR/config.json"
```

### Output formats

- **jsonl** (default): one JSON object per line, machine-readable
- **csv**: header + rows, importable to spreadsheets
- **markdown**: table format, readable in conversation

### Analysis hints

When the user asks for analysis after exporting, look for:
- Repeated or rephrased prompts (user had to retry)
- Prompt complexity trends over time
- Project-level patterns (which projects need more prompting)
- Common correction patterns ("no, I meant...", "not that", "undo")
