#!/usr/bin/env bash
# ==============================================================================
# scripts/test/test_full.sh — Run all validation checks and tests for the repository
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/../.." && pwd))"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/src:$REPO_ROOT/tests${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="${PYTHON:-python3}"

echo "=== 1. Checking Bash & Python Syntax ==="
bash -n skills/review/scripts/inspect_changes.sh
bash -n scripts/setup/install_skills.sh 2>/dev/null || bash -n scripts/install.sh
"$PYTHON" -m py_compile skills/review/scripts/validate_report.py
"$PYTHON" -m py_compile skills/simplify/scripts/scan_debt.py
"$PYTHON" -m py_compile skills/ship/scripts/inspect_lifecycle.py
"$PYTHON" -m py_compile skills/ship/scripts/lifecycle/*.py
"$PYTHON" -m py_compile src/ship/*.py src/ship/lifecycle/*.py src/ship/mcp/*.py src/ship/tools/*.py
"$PYTHON" -m py_compile skills/tdd/scripts/verify_tdd.py
"$PYTHON" -m py_compile skills/design/scripts/validate_design.py
"$PYTHON" -m py_compile skills/spike/scripts/run_spike.py
"$PYTHON" -m py_compile scripts/verify/sync_parity.py
"$PYTHON" -m py_compile scripts/verify/ci_gate.py
if command -v ruff >/dev/null 2>&1; then
  ruff check .
  echo "✓ Ruff lint checks passed"
fi
echo "✓ Script syntax OK"
echo ""

echo "=== 2. Checking Distribution Parity & Skill Coverage ==="
"$PYTHON" scripts/verify/sync_parity.py --check
"$PYTHON" scripts/verify/check_coverage.py
echo "✓ Skill distribution parity OK"
echo ""

echo "=== 3. Running Unit Tests with Python stdlib ==="
"$PYTHON" -m unittest discover -s tests -v
echo ""

echo "=== 4. Running AgentFlow Evaluation Benchmark Suite ==="
"$PYTHON" -m ship.cli benchmark --suite all
echo ""
echo "All checks and tests passed successfully!"
