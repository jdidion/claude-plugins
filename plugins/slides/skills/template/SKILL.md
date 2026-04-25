---
name: template
description: Configure a default PPTX template for the slides plugin. Inspect a .pptx, infer which layouts fit each MARP slide role (title, section, content, two-column), prompt for overrides, and save the mapping so subsequent /slides ... pptx uses the template automatically.
---

# /slides:template — Configure a default PPTX template

Inspect a PPTX template, infer which layouts to use for each MARP slide role (title / section / content / two-column), and save the mapping to `~/.claude/scripts/slides_config.json`. After this, `/slides deck.md pptx` will use the template automatically.

## Arguments

$ARGUMENTS — path to a `.pptx` template file. Required.

## Step 1: Inspect the template

```bash
python3 $CLAUDE_PLUGIN_ROOT/bin/template_inspect.py "<path-to-pptx>" --pretty
```

The inspector emits JSON with:
- `layouts[]` — every slide layout in the template with its placeholders
- `role_picks` — best-guess layout for each role (title / section / content / two_column), each with a `confidence` of `high`, `medium`, or `low`

## Step 2: Present the picks

For each role, show the auto-pick with confidence. Example:

```
Template: /Users/me/Templates/corp.pptx
11 layouts found

Auto-picked:
  title       → "TITLE"                   (high)
  section     → "SECTION_HEADER"          (medium)
  content     → "TITLE_AND_BODY"          (high)
  two_column  → "TITLE_AND_TWO_COLUMNS"   (high)
```

## Step 3: Confirm or override

Ask the user: "Accept these picks? (y/n, or name a role to change)"

For any role the user wants to change (or any role whose confidence is **low** or **None**), show the full layout list with placeholder summaries and let the user pick:

```
Layouts in this template:
  [0]  TITLE                  [CENTER_TITLE, SUBTITLE]
  [1]  SECTION_HEADER         [TITLE]
  [2]  TITLE_AND_BODY         [TITLE, BODY]
  [3]  TITLE_AND_TWO_COLUMNS  [TITLE, BODY, BODY]
  [4]  ONE_COLUMN_TEXT        [TITLE, BODY]
  ...

Which layout for <role>? (enter index, name, or "skip")
```

If the user says `skip`, omit that role from the config — the converter will fall back to keyword search.

Roles to confirm/override in order: `title`, `section`, `content`, `two_column`.

## Step 4: Write the config

Write `~/.claude/scripts/slides_config.json`:

```json
{
  "default_template": "<absolute path to .pptx>",
  "layout_names": {
    "title": "<chosen layout name>",
    "section": "<chosen layout name>",
    "content": "<chosen layout name>",
    "two_column": "<chosen layout name>"
  }
}
```

Use the absolute path from the `template` field of the inspector output. Only include `layout_names` keys the user confirmed — skipped roles are omitted.

If the config file already exists, merge rather than overwrite (preserve any keys we don't touch). Read it, update `default_template` and `layout_names`, write it back.

## Step 5: Confirm

Print:

```
Saved ~/.claude/scripts/slides_config.json
  default_template: <path>
  layout_names:
    title       → <name>
    section     → <name>
    content     → <name>
    two_column  → <name>

/slides will now use this template by default. Override with:
  /slides deck.md pptx --template=/path/to/other.pptx
```

## Rules

- Always use the absolute path (resolve `~` and relative paths)
- Never overwrite other keys in `slides_config.json` — merge
- Don't write the file if the user cancels partway through — confirm before each write
- If the file isn't a `.pptx`, stop and tell the user
- The inspector returns `role_picks[role] = None` when no candidate exists — always prompt in that case
