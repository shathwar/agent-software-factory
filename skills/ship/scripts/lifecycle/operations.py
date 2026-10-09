"""Local installation diagnostics and explicit, backed-up ledger migration."""
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional
import uuid

from .config import ShipConfigManager
from .ledger import FileLedgerStore, read_ledger_file, ensure_gitignore_has_agentflow
from .paths import get_state_file, get_journal_file, agentflow_path
from .transactions import atomic_write


OPENSPEC_REPOSITORY = "https://github.com/Fission-AI/OpenSpec.git"


def update_git_dependency(path: Path) -> dict:
    """If path is a git repository or inside one, pull latest changes with fast-forward only."""
    git = shutil.which("git")
    if not git:
        return {"updated": False, "status": "git-missing"}
    real_path = path.resolve()
    target_dir = real_path if real_path.is_dir() else real_path.parent
    check = subprocess.run(
        [git, "-C", str(target_dir), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        return {"updated": False, "status": "not-a-git-repo"}
    try:
        res = subprocess.run(
            [git, "-C", str(target_dir), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            check=True,
        )
        out = res.stdout.strip()
        status = "up-to-date" if "Already up to date" in out else "updated"
        return {"updated": True, "status": status, "detail": out}
    except subprocess.CalledProcessError as exc:
        return {"updated": False, "status": "update-failed", "error": exc.stderr.strip() or str(exc)}


def resolve_skill_path(name: str, ship: Path, root: Optional[Path] = None) -> Optional[Path]:
    """Discover a skill's location across standard agent host directories."""
    if not name or not name.strip():
        return None
    name = name.strip()
    p = Path(name)
    if p.is_file() and p.name.endswith(".md"):
        return p
    if (p / "SKILL.md").is_file():
        return p

    candidates = [
        ship.parent / name,
        Path.home() / ".gemini/config/skills" / name,
        Path.home() / ".gemini/antigravity/builtin/skills" / name,
        Path.home() / ".claude/skills" / name,
    ]
    if root:
        candidates.extend([
            root / ".claude/skills" / name,
            root / "skills" / name,
        ])
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file() or (candidate.is_file() and candidate.name.endswith(".md")):
            return candidate
    return None


def ensure_openspec_dependency(ship: Path, update: bool = False, install: bool = True) -> dict:
    """Verify, discover, or update the default external SDD skill beside Ship."""
    destination = ship.parent / "openspec"
    found_path: Optional[Path] = None
    if (destination / "SKILL.md").is_file() or any(destination.glob("**/SKILL.md")):
        found_path = destination
    else:
        for candidate in [
            Path.home() / ".gemini/config/skills/openspec",
            Path.home() / ".gemini/antigravity/builtin/skills/openspec",
            Path.home() / ".claude/skills/openspec",
        ]:
            if (candidate / "SKILL.md").is_file():
                found_path = candidate
                break

    git = shutil.which("git")
    if found_path:
        update_info = None
        if update:
            update_info = update_git_dependency(found_path)
        status = "updated" if update_info and update_info.get("updated") else "present"
        return {"installed": False, "path": str(found_path), "status": status, "update": update_info}

    if not git:
        return {"installed": False, "path": str(destination), "status": "missing"}
    if install and os.environ.get("SHIP_ALLOW_NETWORK_INSTALL", "").lower() in ("1", "true", "yes"):
        ref = os.environ.get("SHIP_OPENSPEC_REF", "main")
        subprocess.run([git, "clone", "--depth", "1", "--branch", ref, OPENSPEC_REPOSITORY, str(destination)], check=True)
        return {"installed": True, "path": str(destination), "status": "installed", "ref": ref}
    return {"installed": False, "path": str(destination), "status": "external-dependency"}


def ensure_simplify_dependency(
    ship: Path,
    root: Optional[Path] = None,
    config: Optional[dict] = None,
    update: bool = False,
    install: bool = True,
) -> dict:
    """Verify, discover, or update the configured simplify / anti-bloat provider."""
    provider = "ponytail"
    skills_map = {"refactor": "ponytail", "review": "ponytail-review", "debt": "ponytail-debt"}
    if config and isinstance(config.get("simplify"), dict):
        provider = config["simplify"].get("provider", "ponytail")
        skills_map = config["simplify"].get("skills", skills_map)

    if provider == "builtin":
        target = ship.parent / "simplify"
        is_ok = (target / "SKILL.md").is_file()
        return {
            "provider": "builtin",
            "installed": True,
            "path": str(target),
            "status": "present" if is_ok else "missing",
        }

    resolved = {}
    missing = []
    updates = {}
    for op, skill_name in skills_map.items():
        found = resolve_skill_path(skill_name, ship, root)
        if found:
            resolved[op] = str(found)
            if update:
                updates[op] = update_git_dependency(found)
        else:
            missing.append(skill_name)

    all_present = len(missing) == 0
    status = "present" if all_present else ("external-dependency" if provider != "builtin" and not install else "missing")
    if all_present and update:
        if any(u.get("updated") for u in updates.values()):
            status = "updated"

    return {
        "provider": provider,
        "status": status,
        "skills": resolved,
        "missing": missing,
        "updates": updates if update else None,
    }


def doctor(root: Path, initialize: bool = False, update: bool = False):
    """Run diagnostics and initialize/update external SDD and Simplify dependencies."""
    should_update = update or os.environ.get("SHIP_UPDATE_DEPENDENCIES", "").lower() in ("1", "true", "yes")
    checks = []
    dependency = {"installed": False, "status": "not-applicable"}
    simplify_dep = {"provider": "not-applicable", "status": "not-applicable"}
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

    cfg = None
    try:
        cfg = ShipConfigManager.load(root)
    except Exception:
        pass

    if (ship / "SKILL.md").is_file():
        if initialize:
            try:
                dependency = ensure_openspec_dependency(ship, update=should_update, install=True)
                check("sdd:openspec", True, f"{dependency['status']}: {dependency['path']}")
            except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
                dependency = {"installed": False, "status": "failed", "error": str(exc)}
                check("sdd:openspec", False, str(exc))

            try:
                simplify_dep = ensure_simplify_dependency(ship, root=root, config=cfg, update=should_update, install=True)
                prov = simplify_dep["provider"]
                ok = simplify_dep["status"] in ("present", "updated", "external-dependency")
                detail = f"{simplify_dep['status']}: {', '.join(simplify_dep.get('skills', {}).values()) or 'none'}"
                if simplify_dep.get("missing"):
                    detail += f" (missing: {', '.join(simplify_dep['missing'])})"
                check(f"simplify:{prov}", ok, detail)
            except Exception as exc:
                simplify_dep = {"provider": "failed", "status": "failed", "error": str(exc)}
                check("simplify:provider", False, str(exc))
        else:
            dependency = {"installed": False, "status": "not-checked"}
            simplify_dep = {"provider": "not-checked", "status": "not-checked"}
        version_file = ship / "VERSION"
        version = version_file.read_text().strip() if version_file.exists() else "unknown"
        check("version", version != "unknown", version)
        for skill, script in {"ship": "inspect_lifecycle.py", "review": "validate_report.ts", "tdd": "verify_tdd.ts", "simplify": "scan_debt.ts", "spike": "run_spike.ts"}.items():
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
    if initialize and not (root / ".agentflow.json").exists() and dependency.get("status") in {"present", "installed"}:
        init_agentflow(root)
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
    return {"version": version, "ok": all(c["ok"] for c in checks), "checks": checks, "sdd": dependency, "simplify": simplify_dep}


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
        "sdd": {
            "provider": "openspec",
            "snapshot": ".agentflow/sdd.json",
            "skills": {
                "prepare": "openspec-propose",
                "inspect": "openspec-propose",
                "verify": "openspec-verify-change",
                "finalize": "openspec-archive-change",
            },
        },
        "simplify": {
            "provider": "ponytail",
            "skills": {
                "refactor": "ponytail",
                "review": "ponytail-review",
                "debt": "ponytail-debt",
            },
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
