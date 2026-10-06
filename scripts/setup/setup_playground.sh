#!/usr/bin/env bash
set -euo pipefail

# Provision an ephemeral disposable git workspace for manual AgentFlow testing
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd))"
PLAYGROUND_DIR="$REPO_ROOT/.agentflow/playground"

rm -rf "$PLAYGROUND_DIR"
mkdir -p "$PLAYGROUND_DIR"

cd "$PLAYGROUND_DIR"
git init -b main --quiet
git config user.name "AgentFlow Developer"
git config user.email "developer@example.com"
git config commit.gpgsign false

# Create sample source and test files
mkdir -p src tests
cat << 'EOF' > src/app.py
def hello(name: str) -> str:
    return f"Hello, {name}!"
EOF

cat << 'EOF' > tests/test_app.py
from src.app import hello

def test_hello():
    assert hello("world") == "Hello, world!"
EOF

git add .
git commit -m "chore: initial commit" --quiet

echo "🚀 Ephemeral AgentFlow playground created at:"
echo "   $PLAYGROUND_DIR"
echo ""
echo "To explore and test:"
echo "   cd .agentflow/playground"
echo "   agentflow init"
echo "   agentflow status"
echo ""
