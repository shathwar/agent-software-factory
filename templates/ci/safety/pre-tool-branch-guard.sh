#!/bin/bash
set -euo pipefail

# PreToolUse hook to prevent direct code modification on main/master branches
PROTECTED_BRANCHES="${PROTECTED_BRANCHES:-^(main|master)$}"

CURRENT_BRANCH=$(git symbolic-ref --short HEAD 2>/dev/null || git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

if [ -n "$CURRENT_BRANCH" ]; then
  if echo "$CURRENT_BRANCH" | grep -qE "$PROTECTED_BRANCHES"; then
    echo "{\"decision\":\"block\",\"reason\":\"Direct file edits on protected branch '$CURRENT_BRANCH' are forbidden. Create and switch to a feature branch first (e.g., git checkout -b feature/my-change).\"}"
    exit 2
  fi
fi

exit 0
