#!/usr/bin/env python3
"""Batch write Obsidian notes from JSON input.

Usage:
    echo '[{"path": "Inbox/title.md", "frontmatter": {...}, "content": "..."}]' | python scripts/write-notes.py

Or:
    python scripts/write-notes.py < /tmp/notes.json

Input: JSON array of objects with:
  - path: note path relative to vault root (e.g., "Inbox/My Article.md")
  - frontmatter: dict of YAML frontmatter fields
  - content: markdown body content

Discovers the Obsidian vault path automatically.
"""

import json
import os
import sys

import yaml


def find_vault_path():
    """Discover Obsidian vault path from Obsidian config."""
    config_path = os.path.expanduser(
        "~/Library/Application Support/obsidian/obsidian.json"
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        paths = [v.get('path', '') for v in config.get('vaults', {}).values()]
        for p in paths:
            if os.path.isdir(p):
                return p

    # Fallback: common locations
    for candidate in [
        os.path.expanduser("~/Library/CloudStorage/GoogleDrive-*/My Drive/Obsidian"),
        os.path.expanduser("~/Documents/Obsidian"),
        os.path.expanduser("~/Obsidian"),
    ]:
        import glob
        matches = glob.glob(candidate)
        if matches and os.path.isdir(matches[0]):
            return matches[0]

    print("Could not find Obsidian vault", file=sys.stderr)
    sys.exit(1)


def write_note(vault_path, path, frontmatter, content):
    """Write a single note to the vault."""
    full_path = os.path.join(vault_path, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    parts = []
    if frontmatter:
        parts.append('---')
        parts.append(yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip())
        parts.append('---')
        parts.append('')
    parts.append(content)

    with open(full_path, 'w') as f:
        f.write('\n'.join(parts))


def main():
    vault_path = find_vault_path()
    notes = json.load(sys.stdin)

    if not isinstance(notes, list):
        notes = [notes]

    written = 0
    errors = 0
    for note in notes:
        try:
            write_note(
                vault_path,
                note['path'],
                note.get('frontmatter', {}),
                note.get('content', ''),
            )
            written += 1
        except Exception as e:
            print(f"Error writing {note.get('path', '?')}: {e}", file=sys.stderr)
            errors += 1

    print(json.dumps({
        'vault': vault_path,
        'written': written,
        'errors': errors,
        'total': len(notes),
    }))


if __name__ == '__main__':
    main()
