#!/usr/bin/env bash
set -euo pipefail

# Setup git hooks for shathwar/skills development
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/../.." && pwd))"

GIT_DIR="$REPO_ROOT/.git"
if [[ ! -d "$GIT_DIR" ]]; then
  echo "❌ Error: Not a git repository ($GIT_DIR not found)."
  exit 1
fi

HOOKS_DIR="$GIT_DIR/hooks"
mkdir -p "$HOOKS_DIR"

PRE_COMMIT="$HOOKS_DIR/pre-commit"

cat << 'EOF' > "$PRE_COMMIT"
#!/usr/bin/env bash
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# 1. Pre-commit hook: verify byte-for-byte parity between src/ and skills/
if [[ -f "$REPO_ROOT/scripts/verify/sync_parity.py" ]]; then
  if ! python3 "$REPO_ROOT/scripts/verify/sync_parity.py" --check; then
    echo "❌ Parity check failed. Run 'python3 scripts/verify/sync_parity.py' and stage changes before committing."
    exit 1
  fi
fi

# 2. Pre-commit hook: verify skill coverage inventory and eval gap analysis
if [[ -f "$REPO_ROOT/scripts/verify/check_coverage.py" ]]; then
  if ! python3 "$REPO_ROOT/scripts/verify/check_coverage.py"; then
    echo "❌ Skill coverage / eval gap inventory check failed."
    exit 1
  fi
fi
EOF

chmod +x "$PRE_COMMIT"

echo "✅ Installed git pre-commit hook at $PRE_COMMIT"
echo "   Auto-checks src/ to skills/ parity and skill coverage inventory on every commit."
