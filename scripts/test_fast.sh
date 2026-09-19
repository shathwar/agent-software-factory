#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== Fast In-Memory Unit Tests ==="
PYTHONPATH=src:tests pytest tests/test_scan_debt.py tests/test_verify_tdd.py tests/test_validate_report.py tests/test_documents.py tests/test_cli_init.py tests/test_verification.py tests/test_convergence.py -q
echo "✅ Fast unit tests passed."
