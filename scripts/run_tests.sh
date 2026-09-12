#!/usr/bin/env bash
# ==============================================================================
# scripts/run_tests.sh — Run all validation checks and tests for the repository
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== 1. Checking Bash & Python Syntax ==="
bash -n skills/adversarial-review/scripts/inspect_changes.sh
python3 -m py_compile skills/adversarial-review/scripts/validate_report.py
echo "✓ Script syntax OK"
echo ""

echo "=== 2. Running Unit Tests with Python stdlib ==="
python3 -m unittest discover -s tests -v
echo ""
echo "All checks and tests passed successfully!"
