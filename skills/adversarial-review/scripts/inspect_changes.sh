#!/usr/bin/env bash
# Helper script to inspect current git changes for adversarial review

set -euo pipefail

# Ensure we are in a git repository
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Error: Not inside a git repository." >&2
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
BASE_BRANCH="main"
if ! git rev-parse --verify "$BASE_BRANCH" >/dev/null 2>&1; then
    if git rev-parse --verify master >/dev/null 2>&1; then
        BASE_BRANCH="master"
    else
        BASE_BRANCH=""
    fi
fi

echo "============================================================"
echo "           ADVERSARIAL REVIEW: CHANGE INSPECTOR             "
echo "============================================================"
echo "Current Branch : $BRANCH"
if [ -n "$BASE_BRANCH" ]; then
    echo "Base Branch    : $BASE_BRANCH"
fi
echo ""

echo "--- 1. Working Tree Changes (Uncommitted) ---"
UNCOMMITTED_COUNT=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$UNCOMMITTED_COUNT" -gt 0 ]; then
    echo "Found $UNCOMMITTED_COUNT uncommitted file(s):"
    git status --short
    echo ""
    echo "Diff summary:"
    git diff --stat
else
    echo "Working tree is clean."
fi
echo ""

if [ -n "$BASE_BRANCH" ] && [ "$BRANCH" != "$BASE_BRANCH" ]; then
    echo "--- 2. Branch Changes vs $BASE_BRANCH ---"
    BRANCH_DIFF_COUNT=$(git diff --name-only "$BASE_BRANCH"...HEAD | wc -l | tr -d ' ')
    if [ "$BRANCH_DIFF_COUNT" -gt 0 ]; then
        echo "Found $BRANCH_DIFF_COUNT changed file(s) compared to $BASE_BRANCH:"
        git diff --stat "$BASE_BRANCH"...HEAD
        echo ""
        echo "Changed files list:"
        git diff --name-only "$BASE_BRANCH"...HEAD
    else
        echo "No commits differing from $BASE_BRANCH."
    fi
    echo ""
fi

echo "--- 3. Recent 5 Commits ---"
git log --oneline -n 5
echo ""
echo "============================================================"
