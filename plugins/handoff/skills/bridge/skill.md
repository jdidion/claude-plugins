# /handoff:bridge — Connect this session to an existing team

Join this Claude Code session to a running team as an external member with message bridging.

## Arguments
$ARGUMENTS — `<team-name> [member-name]`. If member-name is omitted, uses the cwd basename.

## Step 1: Verify team exists

```bash
python3 $PLUGIN_ROOT/scripts/team-config.py show $TEAM_NAME
```

If the team doesn't exist, tell the user and exit.

## Step 2: Register as a member

```bash
python3 $PLUGIN_ROOT/scripts/team-config.py join $TEAM_NAME $MEMBER_NAME
```

This adds this session to the team's `config.json` with the current cmux surface ref.

## Step 3: Start the inbox bridge

Run the bridge as a background process:
```bash
python3 $PLUGIN_ROOT/scripts/bridge.py start $TEAM_NAME $MEMBER_NAME $SURFACE_REF &
```

The bridge:
- Polls `~/.claude/teams/$TEAM_NAME/inboxes/$MEMBER_NAME.json` every 2 seconds
- When new messages arrive, sends an OS notification and types the message into this session
- Marks messages as read after delivery

## Step 4: Print quick-reference

```
Connected to team "$TEAM_NAME" as "$MEMBER_NAME"
Bridge running (PID $$)

Quick reference:
  Check tasks:    python3 $PLUGIN_ROOT/scripts/bridge.py tasks $TEAM_NAME
  Claim task:     python3 $PLUGIN_ROOT/scripts/bridge.py claim $TEAM_NAME $MEMBER_NAME <id>
  Complete task:  python3 $PLUGIN_ROOT/scripts/bridge.py complete $TEAM_NAME <id>
  Send message:   python3 $PLUGIN_ROOT/scripts/bridge.py send $TEAM_NAME $MEMBER_NAME <to> "<msg>"
  Check inbox:    python3 $PLUGIN_ROOT/scripts/bridge.py status $TEAM_NAME $MEMBER_NAME

Messages from teammates will appear automatically in this session.
```

## Step 5: Checkpoint hook (optional)

Suggest adding a checkpoint-on-exit:
```
To auto-checkpoint when this session ends, I can write your progress to
~/.claude/handoffs/checkpoints/$TEAM_NAME/$MEMBER_NAME.md

Want me to set up a SessionEnd hook for this? (y/n)
```

If yes, write a SessionEnd hook entry that runs:
```bash
python3 $PLUGIN_ROOT/scripts/bridge.py send $TEAM_NAME $MEMBER_NAME team-lead "Checkpointing: $(cat ~/.claude/handoffs/checkpoints/$TEAM_NAME/$MEMBER_NAME.md 2>/dev/null || echo 'no checkpoint written')"
```

## Rules
- The bridge runs as a background process — it won't block the session
- Messages are typed as plain text into the session input
- The user can still type normally — messages appear between prompts
- If cmux is unavailable, fall back to manual inbox checking
