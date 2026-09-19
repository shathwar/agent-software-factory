#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. Instant Sanity Check ==="
python3 -m py_compile src/ship/*.py src/ship/lifecycle/*.py src/ship/tools/*.py
python3 scripts/sync_skills.py --check
PYTHONPATH=src:tests pytest tests/test_nano_rules.py -q
echo "✅ Sanity check passed (<2s)."
