# Makefile for shathwar/skills and ship-sdlc (AgentFlow SDLC)

PYTHON ?= python3
PYTEST ?= pytest
RUFF ?= ruff

.PHONY: help check test test-fast test-lifecycle test-skills test-all bench benchmark lint sync verify-parity doctor mcp setup-hooks playground install clean

help:
	@echo "Available commands:"
	@echo "  make check           Instant sanity check (<2s: syntax + parity + nano rules)"
	@echo "  make test-fast       Fast in-memory unit tests (<4s: tools, docs, init)"
	@echo "  make test-lifecycle  Focused AgentFlow lifecycle engine tests (~15s)"
	@echo "  make test-skills     Focused specialist tools tests (~5s)"
	@echo "  make test            Run the full test suite (syntax + 480+ tests)"
	@echo "  make bench           Run the AgentFlow evaluation benchmark suite"
	@echo "  make lint            Run ruff code hygiene check"
	@echo "  make sync            Synchronize src/ship/ into skills/*/scripts/"
	@echo "  make verify-parity   Verify 100% byte-for-byte parity between src/ and skills/"
	@echo "  make setup-hooks     Install git pre-commit hook for auto-sync"
	@echo "  make playground      Provision an ephemeral git test repo in .agentflow/playground"
	@echo "  make doctor          Run preflight lifecycle diagnostic checks"
	@echo "  make mcp             Launch the zero-dependency stdio MCP server"
	@echo "  make install         Install ship package locally (pip install -e .)"
	@echo "  make clean           Clean temporary files, build artifacts, and caches"

check:
	@PYTHON="$(PYTHON)" PYTEST="$(PYTEST)" bash scripts/check.sh

test-fast:
	@PYTHON="$(PYTHON)" PYTEST="$(PYTEST)" bash scripts/test_fast.sh

test-lifecycle:
	@echo "Running AgentFlow lifecycle tests..."
	PYTHONPATH=src:tests $(PYTEST) tests/test_inspect_lifecycle.py tests/test_archive_recovery.py tests/test_evidence_gates.py tests/test_turn_regressions.py -q

test-skills:
	@echo "Running specialist tools tests..."
	PYTHONPATH=src:tests $(PYTEST) tests/test_verify_tdd.py tests/test_scan_debt.py tests/test_validate_report.py tests/test_run_spike.py tests/test_audit_ux.py -q

test test-all:
	PYTHON="$(PYTHON)" bash scripts/run_tests.sh

bench benchmark:
	PYTHONPATH=src $(PYTHON) -m ship.cli benchmark --suite all

lint:
	$(RUFF) check src/ tests/

sync:
	$(PYTHON) scripts/sync_skills.py

verify-parity:
	$(PYTHON) scripts/sync_skills.py --check

setup-hooks:
	bash scripts/setup_hooks.sh

playground:
	bash scripts/playground.sh

doctor:
	$(PYTHON) -m ship.cli doctor

mcp:
	PYTHONPATH=src $(PYTHON) -m ship.cli mcp

install:
	pip install -e .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info src/*.egg-info .agentflow
