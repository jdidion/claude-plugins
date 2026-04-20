#!/usr/bin/env python3
"""Handoff registry: manage session registration, inbox, and discovery."""

import json
import os
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
        return json.loads(REGISTRY_FILE.read_text())
    return {"sessions": {}}


def save_registry(data):
    ensure_dirs()
    REGISTRY_FILE.write_text(json.dumps(data, indent=2) + "\n")


def cmux_identify():
    """Get current session's cmux refs."""
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
    # Fallback to env vars
    return {
        "surface": os.environ.get("CMUX_SURFACE_ID", ""),
        "workspace": os.environ.get("CMUX_WORKSPACE_ID", ""),
    }


def cmd_register(name, surface=None, workspace=None):
    """Register a session."""
    reg = load_registry()
    refs = cmux_identify()
    surface = surface or refs.get("surface", "")
    workspace = workspace or refs.get("workspace", "")

    reg["sessions"][name] = {
        "surface": surface,
        "workspace": workspace,
        "cwd": os.getcwd(),
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getppid(),
    }
    save_registry(reg)
    (INBOX_DIR / name).mkdir(exist_ok=True)
    print(json.dumps(reg["sessions"][name], indent=2))


def cmd_auto_register():
    """Auto-register using cwd basename."""
    name = os.path.basename(os.getcwd())
    cmd_register(name)


def cmd_list():
    """List registered sessions."""
    reg = load_registry()
    if not reg["sessions"]:
        print("No sessions registered.")
        return
    for name, info in sorted(reg["sessions"].items()):
        surface = info.get("surface", "?")
        cwd = info.get("cwd", "?")
        print(f"  {name}: {surface} ({cwd})")


def cmd_get(name):
    """Get a session's surface ref."""
    reg = load_registry()
    session = reg["sessions"].get(name)
    if session:
        print(json.dumps(session, indent=2))
    else:
        print(f"Session '{name}' not found.", file=sys.stderr)
        sys.exit(1)


def cmd_whoami():
    """Print this session's registered name."""
    reg = load_registry()
    cwd = os.getcwd()
    surface = os.environ.get("CMUX_SURFACE_ID", "")
    # Match by cwd first, then surface
    for name, info in reg["sessions"].items():
        if info.get("cwd") == cwd:
            print(name)
            return
    for name, info in reg["sessions"].items():
        if surface and info.get("surface") == surface:
            print(name)
            return
    print("unregistered", file=sys.stderr)
    sys.exit(1)


def cmd_inbox():
    """List handoff files in this session's inbox."""
    reg = load_registry()
    cwd = os.getcwd()
    my_name = None
    for name, info in reg["sessions"].items():
        if info.get("cwd") == cwd:
            my_name = name
            break
    if not my_name:
        my_name = os.path.basename(cwd)

    inbox_path = INBOX_DIR / my_name
    if not inbox_path.exists():
        print("[]")
        return

    files = sorted(inbox_path.glob("*.md"), reverse=True)
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
    """Move handoff(s) from inbox to archive."""
    inbox_path = INBOX_DIR / name
    archive_path = ARCHIVE_DIR / name
    archive_path.mkdir(parents=True, exist_ok=True)

    if filename:
        src = inbox_path / filename
        if src.exists():
            src.rename(archive_path / filename)
            print(f"Archived: {filename}")
    else:
        for f in inbox_path.glob("*.md"):
            f.rename(archive_path / f.name)
            print(f"Archived: {f.name}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: registry.py <register|auto-register|list|get|whoami|inbox|archive> [args]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "register":
        name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(os.getcwd())
        surface = sys.argv[3] if len(sys.argv) > 3 else None
        workspace = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_register(name, surface, workspace)
    elif cmd == "auto-register":
        cmd_auto_register()
    elif cmd == "list":
        cmd_list()
    elif cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: registry.py get <name>", file=sys.stderr)
            sys.exit(1)
        cmd_get(sys.argv[2])
    elif cmd == "whoami":
        cmd_whoami()
    elif cmd == "inbox":
        cmd_inbox()
    elif cmd == "archive":
        name = sys.argv[2] if len(sys.argv) > 2 else os.path.basename(os.getcwd())
        filename = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_archive(name, filename)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
