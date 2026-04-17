#!/usr/bin/env python3
"""Team configuration management: create, load, save, and join teams.

Usage:
  team-config.py create <team-name> [--description TEXT]
  team-config.py show <team-name>
  team-config.py join <team-name> <member-name> [--surface SURFACE_REF] [--cwd PATH]
  team-config.py remove <team-name> <member-name>
  team-config.py load <yaml-file>
  team-config.py save <team-name> <yaml-file>
  team-config.py list
  team-config.py destroy <team-name>
  team-config.py checkpoint <team-name> [--output PATH]
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

TEAMS_DIR = Path.home() / ".claude" / "teams"
TASKS_DIR = Path.home() / ".claude" / "tasks"
CHECKPOINTS_DIR = Path.home() / ".claude" / "handoffs" / "checkpoints"


def create_team(name, description=""):
    """Create team directories and config (without native TeamCreate)."""
    team_dir = TEAMS_DIR / name
    team_dir.mkdir(parents=True, exist_ok=True)
    (team_dir / "inboxes").mkdir(exist_ok=True)
    (TASKS_DIR / name).mkdir(parents=True, exist_ok=True)

    config = {
        "name": name,
        "description": description,
        "createdAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        "leadAgentId": "",
        "leadSessionId": "",
        "members": [],
    }
    config_path = team_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(json.dumps(config, indent=2))
    return config


def show_team(name):
    """Display team config."""
    config_path = TEAMS_DIR / name / "config.json"
    if not config_path.exists():
        print(f"Team '{name}' not found.", file=sys.stderr)
        sys.exit(1)
    config = json.loads(config_path.read_text())
    print(f"Team: {config['name']}")
    print(f"Description: {config.get('description', '')}")
    print(f"Lead: {config.get('leadAgentId', 'none')}")
    print(f"Members ({len(config.get('members', []))}):")
    for m in config.get("members", []):
        backend = m.get("backendType", "unknown")
        surface = m.get("surface", m.get("tmuxPaneId", ""))
        print(f"  {m['name']} ({m.get('agentType', '?')}) [{backend}] {surface}")


def join_team(team_name, member_name, surface_ref="", cwd=None):
    """Register an external session as a team member."""
    config_path = TEAMS_DIR / team_name / "config.json"
    if not config_path.exists():
        print(f"Team '{team_name}' not found.", file=sys.stderr)
        sys.exit(1)

    config = json.loads(config_path.read_text())

    # Remove existing member with same name (re-join)
    config["members"] = [m for m in config["members"] if m["name"] != member_name]

    # Get cmux refs if not provided
    if not surface_ref:
        try:
            result = subprocess.run(
                ["cmux", "identify", "--no-caller"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                focused = data.get("focused", {})
                surface_ref = focused.get("surface_ref", "")
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

    member = {
        "agentId": f"{member_name}@{team_name}",
        "name": member_name,
        "agentType": "external",
        "color": "green",
        "joinedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
        "tmuxPaneId": surface_ref,
        "surface": surface_ref,
        "backendType": "external-cmux",
        "subscriptions": [],
        "cwd": cwd or os.getcwd(),
    }
    config["members"].append(member)
    config_path.write_text(json.dumps(config, indent=2) + "\n")

    # Create inbox
    inbox_dir = TEAMS_DIR / team_name / "inboxes"
    inbox_dir.mkdir(exist_ok=True)
    inbox_file = inbox_dir / f"{member_name}.json"
    if not inbox_file.exists():
        inbox_file.write_text("[]\n")

    print(json.dumps(member, indent=2))
    return member


def remove_member(team_name, member_name):
    """Remove a member from the team."""
    config_path = TEAMS_DIR / team_name / "config.json"
    if not config_path.exists():
        print(f"Team '{team_name}' not found.", file=sys.stderr)
        sys.exit(1)
    config = json.loads(config_path.read_text())
    config["members"] = [m for m in config["members"] if m["name"] != member_name]
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Removed {member_name} from {team_name}")


def save_to_yaml(team_name, yaml_path):
    """Export team config to YAML."""
    if not HAS_YAML:
        print("PyYAML not installed. pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    config_path = TEAMS_DIR / team_name / "config.json"
    if not config_path.exists():
        print(f"Team '{team_name}' not found.", file=sys.stderr)
        sys.exit(1)
    config = json.loads(config_path.read_text())

    # Convert to a cleaner YAML format
    yaml_config = {
        "team": config["name"],
        "description": config.get("description", ""),
        "members": [],
    }
    for m in config.get("members", []):
        yaml_config["members"].append({
            "name": m["name"],
            "type": m.get("agentType", "external"),
            "cwd": m.get("cwd", ""),
            "prompt": m.get("prompt", ""),
        })

    Path(yaml_path).write_text(yaml.dump(yaml_config, default_flow_style=False))
    print(f"Saved to {yaml_path}")


def load_from_yaml(yaml_path):
    """Import team config from YAML and create/update the team."""
    if not HAS_YAML:
        print("PyYAML not installed. pip install pyyaml", file=sys.stderr)
        sys.exit(1)
    yaml_config = yaml.safe_load(Path(yaml_path).read_text())
    team_name = yaml_config["team"]
    create_team(team_name, yaml_config.get("description", ""))
    for m in yaml_config.get("members", []):
        if m.get("type") != "team-lead":
            join_team(team_name, m["name"], cwd=m.get("cwd", ""))
    print(f"Loaded team '{team_name}' from {yaml_path}")


def list_teams():
    """List all teams."""
    if not TEAMS_DIR.exists():
        print("No teams.")
        return
    for d in sorted(TEAMS_DIR.iterdir()):
        if d.is_dir() and (d / "config.json").exists():
            config = json.loads((d / "config.json").read_text())
            members = len(config.get("members", []))
            desc = config.get("description", "")[:50]
            print(f"  {d.name}: {members} members — {desc}")


def destroy_team(team_name):
    """Remove team directories."""
    team_dir = TEAMS_DIR / team_name
    tasks_dir = TASKS_DIR / team_name
    if team_dir.exists():
        shutil.rmtree(team_dir)
    if tasks_dir.exists():
        shutil.rmtree(tasks_dir)
    print(f"Destroyed team '{team_name}'")


def checkpoint_team(team_name, output_path=None):
    """Save a checkpoint of the entire team state."""
    CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    output_path = output_path or str(CHECKPOINTS_DIR / f"{team_name}-{ts}.json")

    config_path = TEAMS_DIR / team_name / "config.json"
    if not config_path.exists():
        print(f"Team '{team_name}' not found.", file=sys.stderr)
        sys.exit(1)

    checkpoint = {
        "team_name": team_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": json.loads(config_path.read_text()),
        "tasks": [],
        "inboxes": {},
    }

    # Collect tasks
    tasks_dir = TASKS_DIR / team_name
    if tasks_dir.exists():
        for f in sorted(tasks_dir.glob("*.json")):
            try:
                checkpoint["tasks"].append(json.loads(f.read_text()))
            except (json.JSONDecodeError, IOError):
                pass

    # Collect inboxes
    inboxes_dir = TEAMS_DIR / team_name / "inboxes"
    if inboxes_dir.exists():
        for f in inboxes_dir.glob("*.json"):
            try:
                checkpoint["inboxes"][f.stem] = json.loads(f.read_text())
            except (json.JSONDecodeError, IOError):
                pass

    Path(output_path).write_text(json.dumps(checkpoint, indent=2) + "\n")
    print(f"Checkpoint saved: {output_path}")
    print(f"  Config: {len(checkpoint['config'].get('members', []))} members")
    print(f"  Tasks: {len(checkpoint['tasks'])}")
    print(f"  Inboxes: {len(checkpoint['inboxes'])}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create":
        name = sys.argv[2] if len(sys.argv) > 2 else "unnamed"
        desc = ""
        if "--description" in sys.argv:
            idx = sys.argv.index("--description")
            desc = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        create_team(name, desc)

    elif cmd == "show":
        show_team(sys.argv[2])

    elif cmd == "join":
        if len(sys.argv) < 4:
            print("Usage: team-config.py join <team-name> <member-name> [--surface REF] [--cwd PATH]")
            sys.exit(1)
        surface = ""
        cwd = None
        if "--surface" in sys.argv:
            idx = sys.argv.index("--surface")
            surface = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""
        if "--cwd" in sys.argv:
            idx = sys.argv.index("--cwd")
            cwd = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        join_team(sys.argv[2], sys.argv[3], surface, cwd)

    elif cmd == "remove":
        if len(sys.argv) < 4:
            print("Usage: team-config.py remove <team-name> <member-name>")
            sys.exit(1)
        remove_member(sys.argv[2], sys.argv[3])

    elif cmd == "save":
        if len(sys.argv) < 4:
            print("Usage: team-config.py save <team-name> <yaml-file>")
            sys.exit(1)
        save_to_yaml(sys.argv[2], sys.argv[3])

    elif cmd == "load":
        if len(sys.argv) < 3:
            print("Usage: team-config.py load <yaml-file>")
            sys.exit(1)
        load_from_yaml(sys.argv[2])

    elif cmd == "list":
        list_teams()

    elif cmd == "destroy":
        if len(sys.argv) < 3:
            print("Usage: team-config.py destroy <team-name>")
            sys.exit(1)
        destroy_team(sys.argv[2])

    elif cmd == "checkpoint":
        if len(sys.argv) < 3:
            print("Usage: team-config.py checkpoint <team-name> [--output PATH]")
            sys.exit(1)
        output = None
        if "--output" in sys.argv:
            idx = sys.argv.index("--output")
            output = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        checkpoint_team(sys.argv[2], output)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)
