---
name: team
description: Create and manage interactive teams of Claude Code sessions with shared messaging and task coordination via cmux. Use when the user asks to create a team, spawn teammates, manage shared tasks, or coordinate multi-session work.
---

# /handoff:team — Create and manage interactive teams

Create a team of Claude Code sessions running in separate cmux panes with shared messaging and task coordination.

## Arguments
$ARGUMENTS — Subcommand: `create`, `add`, `tasks`, `msg`, `checkpoint`, `resume`, `destroy`, or a YAML file path to load.

## Creating a team

### Interactive creation
```
/handoff:team create <team-name>
```

1. Ask the user for a team description
2. Create the team:
   - If this session should be the native lead (can use TeamCreate, SendMessage natively):
     ```
     Use the TeamCreate tool: {"team_name": "<name>", "description": "<desc>"}
     ```
   - If creating for external-only use (no native lead):
     ```bash
     python3 $PLUGIN_ROOT/scripts/team-config.py create <name> --description "<desc>"
     ```
3. Register the current session as a member:
   ```bash
   python3 $PLUGIN_ROOT/scripts/team-config.py join <name> <session-name>
   ```
4. Print team status and available commands

### From YAML
```
/handoff:team load path/to/team.yaml
```

YAML format:
```yaml
team: sgnipt-sprint
description: "sgNIPT variant calling improvements for ALGS-1185"
members:
  - name: variant-filter
    type: executor
    cwd: ~/projects/sgnipt-research
    prompt: "Focus on variant filter optimization for ALGS-1185"
  - name: pipeline-tests
    type: test-engineer
    cwd: ~/projects/sgnipt-research
    prompt: "Write integration tests for the new variant filters"
```

Load and create:
```bash
python3 $PLUGIN_ROOT/scripts/team-config.py load <yaml-file>
```

## Adding teammates

```
/handoff:team add <member-name> [--cwd PATH] [--pane|--workspace]
```

1. Create a new cmux pane or workspace for the teammate:
   - `--pane` (default): `cmux new-pane --type terminal --direction right`
   - `--workspace`: `cmux new-workspace --name <member-name> --cwd <path>`
2. Register them into the team config:
   ```bash
   python3 $PLUGIN_ROOT/scripts/team-config.py join <team-name> <member-name> --surface <new-surface-ref> --cwd <path>
   ```
3. Start a Claude session in the new pane:
   ```bash
   cmux send --surface <new-surface-ref> "claude -p 'You are <member-name> on team <team-name>. Read ~/.claude/teams/<team-name>/config.json to see your teammates. Check tasks with: python3 $PLUGIN_ROOT/scripts/bridge.py tasks <team-name>. Send messages with: python3 $PLUGIN_ROOT/scripts/bridge.py send <team-name> <member-name> <to-name> <message>. Start the inbox bridge: python3 $PLUGIN_ROOT/scripts/bridge.py start <team-name> <member-name> <your-surface>'\n"
   ```
4. Alternatively, if the lead has native TeamCreate, spawn as a native teammate:
   ```
   Use the Agent tool with team_name: "<team-name>", name: "<member-name>"
   ```
   Note: native teammates are in-process (not interactive). Use cmux approach for interactive sessions.

## Dynamic membership

Add members at any time during the team's lifetime:
```
/handoff:team add debugger --cwd ~/projects/sgnipt-research
```

Remove members:
```bash
python3 $PLUGIN_ROOT/scripts/team-config.py remove <team-name> <member-name>
```

## Task management

```
/handoff:team tasks
```

Lists all tasks. The lead can also use native TaskCreate/TaskUpdate tools if available.

For external members, use the bridge script:
```bash
python3 $PLUGIN_ROOT/scripts/bridge.py tasks <team-name>
python3 $PLUGIN_ROOT/scripts/bridge.py claim <team-name> <member-name> <task-id>
python3 $PLUGIN_ROOT/scripts/bridge.py complete <team-name> <task-id>
```

## Messaging

From the lead (if native):
```
Use SendMessage tool: {"to": "<member-name>", "message": "...", "summary": "..."}
```

From any session (via bridge):
```bash
python3 $PLUGIN_ROOT/scripts/bridge.py send <team-name> <from-name> <to-name> "<message>"
```

Broadcast to all:
```bash
for member in $(python3 -c "import json; c=json.load(open('$HOME/.claude/teams/<team>/config.json')); [print(m['name']) for m in c['members']]"); do
  python3 $PLUGIN_ROOT/scripts/bridge.py send <team-name> <from-name> "$member" "<message>"
done
```

## Checkpoint and resume

### Checkpoint
```
/handoff:team checkpoint
```

Saves the entire team state (config, tasks, inboxes) to a JSON file:
```bash
python3 $PLUGIN_ROOT/scripts/team-config.py checkpoint <team-name>
```

The lead can also ask each teammate to checkpoint individually:
```
Use SendMessage: {"to": "*", "message": "Please write a checkpoint of your current progress to ~/.claude/handoffs/checkpoints/<team-name>/<your-name>.md including: what you were working on, progress so far, files changed, and next steps."}
```

### Resume
```
/handoff:team resume <checkpoint-file>
```

1. Read the checkpoint JSON
2. Recreate the team config
3. Re-spawn teammates with their checkpoint context as initial prompts
4. Restore tasks to their checkpointed state

## Saving team config
```
/handoff:team save [path]
```

Exports current team to YAML for reuse:
```bash
python3 $PLUGIN_ROOT/scripts/team-config.py save <team-name> <path>
```

## Destroying a team
```
/handoff:team destroy
```

1. Send shutdown to all native teammates
2. Close cmux panes for external members
3. Checkpoint before destroying (optional)
4. Remove team directories:
   ```bash
   python3 $PLUGIN_ROOT/scripts/team-config.py destroy <team-name>
   ```

## Rules
- Always offer to checkpoint before destroying
- External members (cmux-based) are interactive — the user can type in their panes
- Native members (in-process) are subagents — not interactive
- Clearly indicate which type each member is when listing
- The bridge script must be running for external members to receive messages
