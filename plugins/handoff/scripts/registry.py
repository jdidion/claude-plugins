#!/usr/bin/env python3
"""Handoff registry: manage session registration, inbox, and discovery.

Canonical registry key is the Claude Code session ID (a UUID). Sessions
are stored keyed by session ID; aliases are short, human-shaped names
(typically the cmux workspace title, slugified) that point at a session.

Schema:

    {
      "sessions": {
        "<session-id>": { alias, surface, workspace, cwd, registered_at, pid }
      },
      "aliases": {
        "<alias>": "<session-id>"
      }
    }

Why session-ID keying: when you resume or `/clear`, a new session ID
appears. Auto-registration on SessionStart re-points the alias at the
new session ID, so `/handoff:send --to plugins` always reaches the live
conversation even across restarts and clears. Dead session IDs are
garbage-collected on each register call based on PID liveness.

Resolution (alias or session ID or canonical name → session ID):
  - If name == known session ID → session ID.
  - Else if name in aliases → aliases[name] (if target still exists).
  - Else None (not found).
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pod  # noqa: E402  # pyright: ignore[reportMissingImports]

HANDOFFS_DIR = Path.home() / ".claude" / "handoffs"
REGISTRY_FILE = HANDOFFS_DIR / "registry.json"
INBOX_DIR = HANDOFFS_DIR / "inbox"
ARCHIVE_DIR = HANDOFFS_DIR / "archive"


def ensure_dirs():
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    INBOX_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)


def load_registry():
    ensure_dirs()
    if REGISTRY_FILE.exists():
        try:
            data = json.loads(REGISTRY_FILE.read_text())
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}
    data.setdefault("sessions", {})
    data.setdefault("aliases", {})
    return data


def save_registry(data):
    ensure_dirs()
    REGISTRY_FILE.write_text(json.dumps(data, indent=2) + "\n")


def slugify(text: str) -> str:
    """'Curaitor Review' → 'curaitor-review'."""
    return re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()


def pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def gc_registry(reg: dict) -> dict:
    """Drop sessions whose PID is dead, and aliases pointing at missing
    sessions. Safe to call on every mutation."""
    live_ids = {sid for sid, s in reg["sessions"].items() if pid_alive(int(s.get("pid", 0)))}
    reg["sessions"] = {sid: s for sid, s in reg["sessions"].items() if sid in live_ids}
    reg["aliases"] = {a: t for a, t in reg["aliases"].items() if t in live_ids}
    return reg


def cmux_identify():
    try:
        result = subprocess.run(
            ["cmux", "identify", "--no-caller"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            focused = data.get("focused", {})
            return {
                "surface": focused.get("surface_ref", ""),
                "workspace": focused.get("workspace_ref", ""),
            }
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass
    return {
        "surface": os.environ.get("CMUX_SURFACE_ID", ""),
        "workspace": os.environ.get("CMUX_WORKSPACE_ID", ""),
    }


def cmux_workspace_title(workspace_ref: str) -> str | None:
    """Look up the title of a cmux workspace via `cmux list-workspaces`.
    Returns None if unavailable or untitled."""
    if not workspace_ref:
        return None
    try:
        result = subprocess.run(
            ["cmux", "list-workspaces"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    for line in result.stdout.splitlines():
        # "  workspace:1  Plugins  [selected]"  or  "* workspace:1  Plugins [selected]"
        m = re.match(r"\s*\*?\s*(workspace:\d+)\s+(.+?)(?:\s+\[selected\])?\s*$", line)
        if m and m.group(1) == workspace_ref:
            title = m.group(2).strip()
            return title or None
    return None


def resolve_name(name: str, reg: dict) -> str | None:
    """Accept a session ID or alias, return canonical session ID or None."""
    if name in reg["sessions"]:
        return name
    target = reg["aliases"].get(name)
    if target and target in reg["sessions"]:
        return target
    return None


def cmd_register(session_id, surface=None, workspace=None, alias=None):
    """Register a session under its Claude session ID.

    - session_id: the canonical key. Required.
    - alias: explicit alias name. If provided, overrides workspace-title
      auto-alias. If omitted, the workspace title is slugified and used
      as the alias if the workspace has a title. Otherwise no alias.
    """
    reg = gc_registry(load_registry())
    refs = cmux_identify()
    surface = surface or refs.get("surface", "")
    workspace = workspace or refs.get("workspace", "")

    # Alias: explicit > workspace title > none.
    final_alias: str | None = None
    if alias:
        final_alias = slugify(alias) or alias
    else:
        title = cmux_workspace_title(workspace)
        if title:
            final_alias = slugify(title) or None

    # Prefer CMUX_CLAUDE_PID (the long-lived Claude process) over
    # os.getppid(), which in hook contexts is the hook's bash wrapper
    # that exits as soon as the hook returns — dead on arrival for GC.
    pid = int(os.environ.get("CMUX_CLAUDE_PID") or os.getppid())
    reg["sessions"][session_id] = {
        "surface": surface,
        "workspace": workspace,
        "cwd": os.getcwd(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "pid": pid,
    }

    if final_alias:
        # Stale aliases with this name are overwritten silently —
        # prior owners lose their alias slot (they still exist in
        # sessions, just no longer addressable via that short name).
        reg["aliases"][final_alias] = session_id

    save_registry(reg)
    (INBOX_DIR / session_id).mkdir(exist_ok=True)

    out = dict(reg["sessions"][session_id])
    out["session_id"] = session_id
    out["alias"] = final_alias  # display-only; not stored in session record
    print(json.dumps(out, indent=2))


def cmd_unregister(session_id):
    """Remove a session and any aliases pointing at it. Idempotent."""
    reg = load_registry()
    reg["sessions"].pop(session_id, None)
    reg["aliases"] = {a: t for a, t in reg["aliases"].items() if t != session_id}
    save_registry(reg)


def cmd_list():
    reg = gc_registry(load_registry())
    save_registry(reg)  # persist the GC
    if not reg["sessions"]:
        print("No sessions registered.")
        return
    # Reverse map session_id → alias (only one alias per session, last-write-wins)
    sid_to_alias: dict[str, str] = {}
    for alias, sid in reg["aliases"].items():
        sid_to_alias[sid] = alias
    for sid, info in sorted(reg["sessions"].items()):
        alias = sid_to_alias.get(sid)
        surface = info.get("surface", "?")
        cwd = info.get("cwd", "?")
        prefix = f"  {alias} → {sid}" if alias else f"  {sid}"
        print(f"{prefix}: {surface} ({cwd})")


def cmd_get(name):
    """Look up a session by ID or alias. Prints the full record."""
    reg = load_registry()
    sid = resolve_name(name, reg)
    if sid is None:
        print(f"Session '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    out = dict(reg["sessions"][sid])
    out["session_id"] = sid
    print(json.dumps(out, indent=2))


def cmd_resolve(name):
    """Print canonical session ID for a given name. Exits 1 if not found."""
    reg = load_registry()
    sid = resolve_name(name, reg)
    if sid is None:
        print(f"Session '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    print(sid)


def _find_session_for_cwd_or_surface(reg):
    """Identify the current session by cwd, then surface."""
    cwd = os.getcwd()
    for sid, info in reg["sessions"].items():
        if info.get("cwd") == cwd:
            return sid
    surface = os.environ.get("CMUX_SURFACE_ID", "")
    if surface:
        for sid, info in reg["sessions"].items():
            if info.get("surface") == surface:
                return sid
    return None


def cmd_whoami():
    """Print this session's ID (and alias if any).
    Format: 'session-id' or 'alias → session-id'."""
    reg = load_registry()
    sid = _find_session_for_cwd_or_surface(reg)
    if sid is None:
        print("unregistered", file=sys.stderr)
        sys.exit(1)
    # Reverse-lookup alias from the aliases map.
    alias = next((a for a, t in reg["aliases"].items() if t == sid), None)
    print(f"{alias} → {sid}" if alias else sid)


def cmd_inbox():
    reg = load_registry()
    sid = _find_session_for_cwd_or_surface(reg)
    if sid is None:
        # Fall back to cwd basename for pre-registration corner case.
        sid = os.path.basename(os.getcwd())

    # Scan both the canonical session-id directory AND any alias
    # directories pointing at this session. Senders running older
    # versions of /handoff:send write pods to inbox/<alias>/ rather
    # than inbox/<session-id>/ — this keeps those discoverable.
    scan_paths = [INBOX_DIR / sid]
    for alias, target in reg["aliases"].items():
        if target == sid:
            alt = INBOX_DIR / alias
            if alt.exists() and alt != scan_paths[0]:
                scan_paths.append(alt)

    files = []
    for p in scan_paths:
        if p.exists():
            files.extend(p.glob("*.md"))
    files.sort(key=lambda f: f.name, reverse=True)

    if not files:
        print("[]")
        return
    seen = pod.SeenStore()
    items = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        try:
            parsed = pod.parse_shape_a(text)
        except ValueError:
            items.append({
                "file": str(f),
                "name": f.name,
                "from": "unknown",
                "timestamp": "",
                "slug": f.stem,
                "format": "invalid",
            })
            continue
        envelope = parsed["envelope"]
        pod_id = str(envelope.get("id") or "")
        items.append({
            "file": str(f),
            "name": f.name,
            "id": pod_id,
            "from": str(envelope.get("from", "unknown")),
            "timestamp": str(envelope.get("createdAt", "")),
            "slug": str(parsed["payload_meta"].get("slug", f.stem)),
            "format": "legacy" if parsed["legacy"] else "pod",
            "fingerprint_ok": parsed["fingerprint_ok"],
            "already_seen": bool(pod_id) and seen.has(pod_id),
        })
    print(json.dumps(items, indent=2))


def cmd_archive(name, filename=None):
    """Archive pod files for a session. Name can be ID or alias.

    Searches both the canonical session-id inbox AND any alias inboxes
    pointing at the session, so pods written by older /handoff:send
    versions (which addressed the alias directly) are archivable.
    """
    reg = load_registry()
    sid = resolve_name(name, reg) or name
    archive_path = ARCHIVE_DIR / sid
    archive_path.mkdir(parents=True, exist_ok=True)

    # Build the set of inbox paths to drain.
    inbox_paths = [INBOX_DIR / sid]
    for alias, target in reg["aliases"].items():
        if target == sid:
            alt = INBOX_DIR / alias
            if alt.exists() and alt not in inbox_paths:
                inbox_paths.append(alt)

    if filename:
        for inbox in inbox_paths:
            src = inbox / filename
            if src.exists():
                src.rename(archive_path / filename)
                print(f"Archived: {filename}")
                return
    else:
        for inbox in inbox_paths:
            for f in inbox.glob("*.md"):
                f.rename(archive_path / f.name)
                print(f"Archived: {f.name}")


def _parse_register_args(argv):
    """Register accepts session ID as positional, plus optional flags.

        registry.py register <session-id> [surface] [workspace] [--alias <name>]
    """
    parser = argparse.ArgumentParser(prog="registry.py register")
    parser.add_argument("session_id", nargs="?")
    parser.add_argument("surface", nargs="?")
    parser.add_argument("workspace", nargs="?")
    parser.add_argument("--alias", default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: registry.py <register|unregister|list|get|resolve|whoami|inbox|archive> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "register":
        args = _parse_register_args(sys.argv[2:])
        if not args.session_id:
            print("register requires a session ID", file=sys.stderr)
            sys.exit(1)
        cmd_register(args.session_id, args.surface, args.workspace, args.alias)
    elif cmd == "unregister":
        if len(sys.argv) < 3:
            print("Usage: registry.py unregister <session-id>", file=sys.stderr)
            sys.exit(1)
        cmd_unregister(sys.argv[2])
    elif cmd == "list":
        cmd_list()
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: registry.py get <name>", file=sys.stderr)
            sys.exit(1)
        cmd_get(sys.argv[2])
    elif cmd == "resolve":
        if len(sys.argv) < 3:
            print("Usage: registry.py resolve <name>", file=sys.stderr)
            sys.exit(1)
        cmd_resolve(sys.argv[2])
    elif cmd == "whoami":
        cmd_whoami()
    elif cmd == "inbox":
        cmd_inbox()
    elif cmd == "archive":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        filename = sys.argv[3] if len(sys.argv) > 3 else None
        if not name:
            print("Usage: registry.py archive <name> [filename]", file=sys.stderr)
            sys.exit(1)
        cmd_archive(name, filename)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
