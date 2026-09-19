#!/usr/bin/env bash
set -euo pipefail

# Setup git hooks for shathwar/skills development
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# Pre-commit hook: maintain byte-for-byte parity between src/ and skills/
REPO_ROOT="$(git rev-parse --show-toplevel)"
if [[ -f "$REPO_ROOT/scripts/sync_skills.py" ]]; then
  python3 "$REPO_ROOT/scripts/sync_skills.py"
  git add -u "$REPO_ROOT/skills"
fi
EOF

chmod +x "$PRE_COMMIT"

echo "✅ Installed git pre-commit hook at $PRE_COMMIT"
echo "   Auto-syncs src/ to skills/ on every commit."
