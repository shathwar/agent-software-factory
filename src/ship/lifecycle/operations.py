"""Local installation diagnostics and explicit, backed-up ledger migration."""
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid

from .config import ShipConfigManager
from .ledger import FileLedgerStore, read_ledger_file
from .paths import repository_path
from .transactions import atomic_write


def doctor(root: Path):
    """Read-only checks; never synchronize state, run project commands, or recover files."""
    checks = []
    def check(name, ok, detail):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
    check("python", sys.version_info >= (3, 10), platform.python_version() + " (requires 3.10+)")
    check("platform", sys.platform in ("darwin", "linux"), sys.platform + " (macOS/Linux supported; use WSL on Windows)")
    check("git", shutil.which("git") is not None, shutil.which("git") or "Install Git")
    cur_file = Path(__file__).resolve()
    if len(cur_file.parents) > 3 and (cur_file.parents[3] / "skills" / "ship").is_dir():
        ship = cur_file.parents[3] / "skills" / "ship"
    else:
        ship = cur_file.parents[2]
    version_file = ship / "VERSION"
    version = version_file.read_text().strip() if version_file.exists() else "unknown"
    check("version", version != "unknown", version)
    for skill, script in {"ship": "inspect_lifecycle.py", "review": "validate_report.py", "tdd": "verify_tdd.py", "simplify": "scan_debt.py", "spike": "run_spike.py"}.items():
        folder = ship.parent / skill
        check(f"skill:{skill}", (folder / "SKILL.md").is_file() and (folder / "scripts" / script).is_file(), str(folder))
    check("skill:design", (ship.parent / "design/SKILL.md").is_file(), str(ship.parent / "design"))
    for name in ("ship", "design", "review", "tdd", "simplify", "spike"):
        receipt = ship.parent / name / "VERSION"
        try:
            installed = receipt.read_text().strip()
        except OSError:
            installed = "missing"
        check(f"version:{name}", installed == version and installed != "unknown", installed)
    check("schema", (ship / "references/ship.schema.json").is_file(), "Bundled configuration schema")
    try:
        config = ShipConfigManager.load(root)
        check("configuration", True, f"profile={config['workflow']['profile']}, execution={config['workflow']['execution']}")
    except ValueError as exc:
        check("configuration", False, str(exc))
    try:
        state = read_ledger_file(repository_path(root, ".ship/state.json"))
        check("ledger", True, "Not initialized" if state is None else ("Version 1" if "version" in state else "Legacy versionless ledger; run --migrate-state"))
        journal = repository_path(root, ".ship/archive-transaction.json")
        check("recovery", not journal.exists(), "Run normal inspection to recover interrupted archive" if journal.exists() else "No pending archive")
    except (ValueError, OSError) as exc:
        check("ledger", False, str(exc))
    return {"version": version, "ok": all(c["ok"] for c in checks), "checks": checks}


def migrate_state(root: Path):
    """Stamp the supported versionless format as v1; never infer unknown schemas."""
    with FileLedgerStore.lock(root):
        path = repository_path(root, ".ship/state.json")
        state = read_ledger_file(path)
        if state is None or "version" in state:
            return {"changed": False, "version": state.get("version") if state else None}
        backup = repository_path(root, f".ship/state.pre-v1-{uuid.uuid4().hex}.json")
        atomic_write(backup, path.read_bytes())
        state["version"] = 1
        FileLedgerStore.save(root, state)
        return {"changed": True, "version": 1, "backup": str(backup)}
