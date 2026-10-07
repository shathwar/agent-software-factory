#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/../.." && pwd))"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
PYTEST="${PYTEST:-pytest}"

echo "=== Fast In-Memory Unit Tests ==="
PYTHONPATH=src:.:tests "$PYTEST" \
  tests/test_scan_debt.py \
  tests/test_verify_tdd.py \
  tests/test_validate_report.py \
  tests/test_documents.py \
  tests/test_cli_init.py \
  tests/test_verification.py \
  tests/test_convergence.py \
  tests/test_nano_rules.py \
  tests/test_audit_ux.py \
  tests/test_ux_evaluation.py \
  tests/test_agent_regression.py \
  tests/test_behavioral_eval_cases.py \
  -q
echo "✅ Fast unit tests passed."
