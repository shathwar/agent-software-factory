# Makefile for shathwar/skills and ship-sdlc (AgentFlow SDLC)

.PHONY: help check test test-fast test-lifecycle test-skills test-all sync verify-parity doctor mcp setup-hooks playground install clean

help:
	@echo "Available commands:"
	@echo "  make check           Instant sanity check (<2s: syntax + parity + nano rules)"
	@echo "  make test-fast       Fast in-memory unit tests (<4s: tools, docs, init)"
	@echo "  make test-lifecycle  Focused AgentFlow lifecycle engine tests (~15s)"
	@echo "  make test-skills     Focused specialist tools tests (~5s)"
	@echo "  make test            Run the full test suite (syntax + 270+ tests)"
	@echo "  make test-all        Run the full test suite via scripts/run_tests.sh"
	@echo "  make sync            Synchronize src/ship/ into skills/*/scripts/"
	@echo "  make verify-parity   Verify 100% byte-for-byte parity between src/ and skills/"
	@echo "  make setup-hooks     Install git pre-commit hook for auto-sync"
	@echo "  make playground      Provision an ephemeral git test repo in .agentflow/playground"
	@echo "  make doctor          Run preflight lifecycle diagnostic checks"
	@echo "  make mcp             Launch the zero-dependency stdio MCP server"
	@echo "  make install         Install ship package locally (pip install -e .)"
	@echo "  make clean           Clean temporary files, build artifacts, and caches"

check:
	@echo "Running instant sanity check..."
	python3 -m py_compile src/ship/*.py src/ship/lifecycle/*.py src/ship/tools/*.py
	python3 scripts/sync_skills.py --check
	PYTHONPATH=src:tests pytest tests/test_nano_rules.py -q

test-fast:
	@echo "Running fast unit tests..."
	PYTHONPATH=src:tests pytest tests/test_scan_debt.py tests/test_verify_tdd.py tests/test_validate_report.py tests/test_documents.py tests/test_cli_init.py tests/test_verification.py tests/test_convergence.py -q

test-lifecycle:
	@echo "Running AgentFlow lifecycle tests..."
	PYTHONPATH=src:tests pytest tests/test_inspect_lifecycle.py tests/test_archive_recovery.py tests/test_evidence_gates.py tests/test_turn_regressions.py -q

test-skills:
	@echo "Running specialist tools tests..."
	PYTHONPATH=src:tests pytest tests/test_verify_tdd.py tests/test_scan_debt.py tests/test_validate_report.py tests/test_run_spike.py -q

test: test-all

test-all:
	./scripts/run_tests.sh

sync:
	python3 scripts/sync_skills.py

verify-parity:
	python3 scripts/sync_skills.py --check

setup-hooks:
	bash scripts/setup_hooks.sh

playground:
	bash scripts/playground.sh

doctor:
	python3 -m ship.cli doctor

mcp:
	PYTHONPATH=src python3 -m ship.cli mcp

install:
	pip install -e .

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache build dist *.egg-info src/*.egg-info .agentflow
