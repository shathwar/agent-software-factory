"""Local installation diagnostics and explicit, backed-up ledger migration."""
import json
from pathlib import Path
import platform
import shutil
import sys
from typing import Any, Dict, Optional
import uuid

from .config import ShipConfigManager
from .ledger import FileLedgerStore, read_ledger_file, ensure_gitignore_has_agentflow
from .paths import get_state_file, get_journal_file, agentflow_path
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
    if (ship / "SKILL.md").is_file():
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
        check("schema", (ship / "references/agentflow.schema.json").is_file(), "Bundled configuration schema")
    else:
        from ship import __version__
        from .config import get_schema_path
        version = __version__
        check("version", True, version)
        check("schema", get_schema_path().is_file(), "Packaged configuration schema")
        check("distribution", True, "CLI package; install prompt skills separately in the agent host")
    try:
        config = ShipConfigManager.load(root)
        check("configuration", True, f"profile={config['workflow']['profile']}, execution={config['workflow']['execution']}")
    except ValueError as exc:
        check("configuration", False, str(exc))
    try:
        state = read_ledger_file(get_state_file(root))
        check("ledger", True, "Not initialized" if state is None else ("Version 1" if "version" in state else "Legacy versionless ledger; run --migrate-state"))
        journal = get_journal_file(root)
        check("recovery", not journal.exists(), "Run normal inspection to recover interrupted archive" if journal.exists() else "No pending archive")
    except (ValueError, OSError) as exc:
        check("ledger", False, str(exc))
    return {"version": version, "ok": all(c["ok"] for c in checks), "checks": checks}


def migrate_state(root: Path):
    """Stamp the supported versionless format as v1; never infer unknown schemas."""
    with FileLedgerStore.lock(root):
        path = get_state_file(root)
        state = read_ledger_file(path)
        if state is None or "version" in state:
            return {"changed": False, "version": state.get("version") if state else None}
        backup = agentflow_path(root, f"state.pre-v1-{uuid.uuid4().hex}.json")
        atomic_write(backup, path.read_bytes())
        state["version"] = 1
        FileLedgerStore.save(root, state)
        return {"changed": True, "version": 1, "backup": str(backup)}


def detect_test_command(repo_root: Path) -> str:
    """Auto-detect test command from repository files."""
    pkg_json = repo_root / "package.json"
    if pkg_json.is_file():
        try:
            data = json.loads(pkg_json.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "test" in data.get("scripts", {}):
                if (repo_root / "pnpm-lock.yaml").exists():
                    return "pnpm test"
                if (repo_root / "yarn.lock").exists():
                    return "yarn test"
                return "npm test"
        except Exception:
            pass

    if (repo_root / "Cargo.toml").is_file():
        return "cargo test"

    if (repo_root / "go.mod").is_file():
        return "go test ./..."

    if any((repo_root / f).exists() for f in ("pytest.ini", "pyproject.toml", "setup.cfg")) or (repo_root / "tests").is_dir():
        return "pytest"

    return ""


def init_agentflow(
    root: Path,
    profile: str = "standard",
    scope: str = ".",
    test_cmd: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Initialize an AgentFlow workflow in the repository."""
    config_file = root / ".agentflow.json"
    if config_file.exists() and not force:
        raise FileExistsError(f"{config_file.name} already exists. Use force=True to overwrite.")

    detected_test = test_cmd if test_cmd is not None else detect_test_command(root)
    name = root.name or "project"

    config_data = {
        "$schema": "https://raw.githubusercontent.com/shathwar/agentflow/main/skills/ship/references/agentflow.schema.json",
        "version": 1,
        "workflow": {
            "profile": profile,
            "execution": "auto",
        },
        "project": {
            "name": name,
            "scope": scope,
        },
        "gates": {
            "implementation": {
                "test": detected_test,
            },
        },
    }

    config_file.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")
    ensure_gitignore_has_agentflow(root)

    return {
        "ok": True,
        "path": str(config_file),
        "profile": profile,
        "test_command": detected_test,
    }
