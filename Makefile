# Makefile for shathwar/skills and ship-sdlc

.PHONY: help test test-fast sync verify-parity doctor mcp install clean

help:
	@echo "Available commands:"
	@echo "  make test           Run the full test suite (syntax + 258+ tests)"
	@echo "  make test-fast      Run unit tests directly with PYTHONPATH=tests:src"
	@echo "  make sync           Synchronize src/ship/ into skills/*/scripts/"
	@echo "  make verify-parity  Verify 100% byte-for-byte parity between src/ and skills/"
	@echo "  make doctor         Run preflight lifecycle diagnostic checks"
	@echo "  make mcp            Launch the zero-dependency stdio MCP server"
	@echo "  make install        Install ship package locally (pip install -e .)"
	@echo "  make clean          Clean temporary files, build artifacts, and caches"

test:
	./scripts/run_tests.sh

test-fast:
	PYTHONPATH=tests:src python3 -m unittest discover -s tests -v

sync:
	python3 scripts/sync_skills.py

verify-parity:
	python3 scripts/sync_skills.py --check

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
