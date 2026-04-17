#!/bin/bash
# Gather git state for context offloading. Output: compact plain text.
set -euo pipefail

CWD="${1:-$(pwd)}"
cd "$CWD" 2>/dev/null || exit 0

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "not a git repo"; exit 0; }

BRANCH=$(git branch --show-current 2>/dev/null || echo "detached")
MAIN=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main")

echo "branch: $BRANCH (base: $MAIN)"

DIRTY=$(git status --porcelain 2>/dev/null)
if [ -n "$DIRTY" ]; then
  echo "dirty:"
  echo "$DIRTY"
fi

if [ "$BRANCH" != "$MAIN" ]; then
  COMMITS=$(git log --oneline "${MAIN}..HEAD" 2>/dev/null || true)
  if [ -n "$COMMITS" ]; then
    echo "commits since $MAIN:"
    echo "$COMMITS"
  fi
else
  COMMITS=$(git log --oneline -5 2>/dev/null || true)
  if [ -n "$COMMITS" ]; then
    echo "recent:"
    echo "$COMMITS"
  fi
fi

STASH_COUNT=$(git stash list 2>/dev/null | wc -l | tr -d ' ')
if [ "$STASH_COUNT" -gt 0 ]; then
  echo "stashes: $STASH_COUNT"
fi
