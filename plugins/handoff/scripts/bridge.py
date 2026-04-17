#!/usr/bin/env python3
"""Team bridge: polls a team inbox and injects messages into a Claude Code session via cmux.

Usage:
  bridge.py start <team-name> <member-name> <surface-ref>  # Start polling
  bridge.py send <team-name> <from-name> <to-name> <message>  # Send a message
  bridge.py status <team-name> <member-name>  # Check inbox without injecting
  bridge.py tasks <team-name>  # List team tasks
  bridge.py claim <team-name> <member-name> <task-id>  # Claim a task
  bridge.py complete <team-name> <task-id>  # Mark task complete
"""

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TEAMS_DIR = Path.home() / ".claude" / "teams"
TASKS_DIR = Path.home() / ".claude" / "tasks"
BRIDGE_PID_DIR = Path.home() / ".claude" / "handoffs" / "bridges"


def inbox_path(team_name, member_name):
    return TEAMS_DIR / team_name / "inboxes" / f"{member_name}.json"


def read_inbox(team_name, member_name):
    path = inbox_path(team_name, member_name)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, IOError):
        return []


def write_inbox(team_name, member_name, messages):
    path = inbox_path(team_name, member_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2) + "\n")


def send_message(team_name, from_name, to_name, text, summary=None):
    """Write a message to a teammate's inbox file."""
    messages = read_inbox(team_name, to_name)
    messages.append({
        "from": from_name,
        "text": text,
        "summary": summary or text[:50],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "color": "green",
        "read": False,
    })
    write_inbox(team_name, to_name, messages)
    return True


def cmux_send(surface_ref, text):
    """Type text into a cmux surface."""
    try:
        result = subprocess.run(
            ["cmux", "send", "--surface", surface_ref, text],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def cmux_notify(title, body):
    """Send an OS notification via cmux."""
    try:
        subprocess.run(
            ["cmux", "notify", "--title", title, "--body", body],
            capture_output=True, text=True, timeout=5
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def format_message_for_injection(msg):
    """Format a team message for display in a Claude session."""
    from_name = msg.get("from", "unknown")
    text = msg.get("text", "")
    summary = msg.get("summary", "")

    # Skip idle notifications and structured protocol messages
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            msg_type = parsed.get("type", "")
            if msg_type in ("idle_notification", "task_assignment"):
                return None
            if msg_type == "shutdown_request":
                return f"[TEAM] {from_name} requests shutdown. Type: /team-respond shutdown approve"
        except json.JSONDecodeError:
            pass

    return f"[TEAM MESSAGE from {from_name}]: {text}"


def start_polling(team_name, member_name, surface_ref, interval=2.0):
    """Poll inbox and inject new messages into the cmux surface."""
    BRIDGE_PID_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = BRIDGE_PID_DIR / f"{team_name}-{member_name}.pid"
    pid_file.write_text(str(os.getpid()))

    last_count = len(read_inbox(team_name, member_name))
    print(f"Bridge started: {member_name}@{team_name} → {surface_ref} (PID {os.getpid()})")
    print(f"Polling every {interval}s. Ctrl+C to stop.")

    def cleanup(sig, frame):
        pid_file.unlink(missing_ok=True)
        print("\nBridge stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    while True:
        try:
            messages = read_inbox(team_name, member_name)
            if len(messages) > last_count:
                new_messages = messages[last_count:]
                for msg in new_messages:
                    if msg.get("read"):
                        continue
                    formatted = format_message_for_injection(msg)
                    if formatted:
                        # Notify
                        cmux_notify(
                            f"Team: {msg.get('from', '?')}",
                            msg.get("summary", formatted[:80])
                        )
                        # Type into session
                        cmux_send(surface_ref, formatted + "\\n")
                        # Mark as read
                        msg["read"] = True

                # Write back with read flags
                write_inbox(team_name, member_name, messages)
                last_count = len(messages)
            else:
                last_count = len(messages)

            time.sleep(interval)
        except KeyboardInterrupt:
            cleanup(None, None)
        except Exception as e:
            print(f"Bridge error: {e}", file=sys.stderr)
            time.sleep(interval)


def list_tasks(team_name):
    """List tasks for a team."""
    tasks_dir = TASKS_DIR / team_name
    if not tasks_dir.exists():
        print("No tasks found.")
        return

    tasks = []
    for f in sorted(tasks_dir.glob("*.json")):
        if f.name in (".lock", ".highwatermark"):
            continue
        try:
            task = json.loads(f.read_text())
            tasks.append(task)
        except (json.JSONDecodeError, IOError):
            continue

    if not tasks:
        print("No tasks found.")
        return

    for t in tasks:
        status = t.get("status", "?")
        owner = t.get("owner", "unassigned")
        subject = t.get("subject", "?")
        tid = t.get("id", "?")
        print(f"  #{tid} [{status}] {subject} ({owner})")


def claim_task(team_name, member_name, task_id):
    """Claim a task by updating its owner and status."""
    task_file = TASKS_DIR / team_name / f"{task_id}.json"
    if not task_file.exists():
        print(f"Task #{task_id} not found.", file=sys.stderr)
        sys.exit(1)

    task = json.loads(task_file.read_text())
    task["owner"] = member_name
    task["status"] = "in_progress"
    task_file.write_text(json.dumps(task, indent=2) + "\n")
    print(f"Claimed task #{task_id}: {task.get('subject', '?')}")


def complete_task(team_name, task_id):
    """Mark a task as completed."""
    task_file = TASKS_DIR / team_name / f"{task_id}.json"
    if not task_file.exists():
        print(f"Task #{task_id} not found.", file=sys.stderr)
        sys.exit(1)

    task = json.loads(task_file.read_text())
    task["status"] = "completed"
    task_file.write_text(json.dumps(task, indent=2) + "\n")
    print(f"Completed task #{task_id}: {task.get('subject', '?')}")


def check_status(team_name, member_name):
    """Show inbox status without injecting."""
    messages = read_inbox(team_name, member_name)
    unread = [m for m in messages if not m.get("read")]
    print(f"Inbox: {len(messages)} total, {len(unread)} unread")
    for msg in unread:
        from_name = msg.get("from", "?")
        summary = msg.get("summary", msg.get("text", "")[:60])
        ts = msg.get("timestamp", "")
        print(f"  [{ts[:19]}] {from_name}: {summary}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "start":
        if len(sys.argv) < 5:
            print("Usage: bridge.py start <team-name> <member-name> <surface-ref>")
            sys.exit(1)
        start_polling(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "send":
        if len(sys.argv) < 6:
            print("Usage: bridge.py send <team-name> <from-name> <to-name> <message>")
            sys.exit(1)
        send_message(sys.argv[2], sys.argv[3], sys.argv[4], " ".join(sys.argv[5:]))
        print(f"Message sent to {sys.argv[4]}")

    elif cmd == "status":
        if len(sys.argv) < 4:
            print("Usage: bridge.py status <team-name> <member-name>")
            sys.exit(1)
        check_status(sys.argv[2], sys.argv[3])

    elif cmd == "tasks":
        if len(sys.argv) < 3:
            print("Usage: bridge.py tasks <team-name>")
            sys.exit(1)
        list_tasks(sys.argv[2])

    elif cmd == "claim":
        if len(sys.argv) < 5:
            print("Usage: bridge.py claim <team-name> <member-name> <task-id>")
            sys.exit(1)
        claim_task(sys.argv[2], sys.argv[3], sys.argv[4])

    elif cmd == "complete":
        if len(sys.argv) < 4:
            print("Usage: bridge.py complete <team-name> <task-id>")
            sys.exit(1)
        complete_task(sys.argv[2], sys.argv[3])

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
