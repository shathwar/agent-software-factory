#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || (cd "$SCRIPT_DIR/../.." && pwd))"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
PYTEST="${PYTEST:-pytest}"

echo "=== 1. Instant Sanity Check ==="
"$PYTHON" -m py_compile src/ship/*.py src/ship/lifecycle/*.py src/ship/tools/*.py
"$PYTHON" scripts/verify/sync_parity.py --check
"$PYTHON" scripts/verify/check_coverage.py
PYTHONPATH=src:.:tests "$PYTEST" tests/test_nano_rules.py tests/test_documents.py tests/test_audit_ux.py tests/test_ux_evaluation.py -q
echo "✅ Sanity check passed (<2s)."
