#!/usr/bin/env python3
"""Inspect repository state against the engineering lifecycle.

Zero-dependency script (Python 3.10+ standard library).

Evaluates filesystem indicators to determine active gate:
- design: Specification & Architecture (design / spike)
- implementation: Test-First Implementation (tdd + simplify)
- audit: Adversarial Review & Adjudication (audit loop)
- delivery: Ready to Ship (delivery & PR sign-off)
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
from contextlib import contextmanager
import datetime
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


def git_cmd(
    repo_root: Path,
    *args: str,
    check: bool = False,
    env: Optional[Dict[str, str]] = None,
    text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    """Execute a git command in the repository directory."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=text,
        check=check,
        env=env,
    )


def git_out(repo_root: Path, *args: str) -> str:
    """Execute a git command and return stripped stdout if successful, else empty string."""
    try:
        res = git_cmd(repo_root, *args)
        return res.stdout.strip() if res.returncode == 0 else ""
    except Exception:
        return ""


def read_json_file(path: Path, default: Any = None) -> Any:
    """Safely load JSON from file path, returning default on missing file or parse error."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def compute_working_tree_fingerprint(repo_root: Path) -> str:
    """Compute a deterministic SHA-256 fingerprint of HEAD commit, working tree diff, and untracked files."""
    hasher = hashlib.sha256()

    # 1. Commit SHA of HEAD if git repo
    head_sha = git_out(repo_root, "rev-parse", "HEAD") or "none"
    hasher.update(f"HEAD:{head_sha}\n".encode("utf-8"))

    # 2. Diff of tracked files (both staged and unstaged)
    try:
        if head_sha != "none":
            diff_res = git_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", "--", text=False)
            if diff_res.returncode == 0:
                hasher.update(b"DIFF:\n" + diff_res.stdout)
        else:
            diff_staged = git_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--cached", "--", text=False)
            diff_unstaged = git_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--", text=False)
            if diff_staged.returncode == 0:
                hasher.update(b"DIFF_STAGED:\n" + diff_staged.stdout)
            if diff_unstaged.returncode == 0:
                hasher.update(b"DIFF_UNSTAGED:\n" + diff_unstaged.stdout)
    except Exception:
        pass

    # 3. Untracked files (excluding scratch, archive, etc.)
    ignored_prefixes = (".scratch/", "scratch/", ".ship/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
    try:
        untracked_res = git_cmd(repo_root, "ls-files", "--others", "--exclude-standard", "-z", text=False)
        if untracked_res.returncode == 0:
            for raw_path in sorted(p for p in untracked_res.stdout.split(b"\0") if p):
                rel_str = raw_path.decode("utf-8", errors="replace")
                if any(rel_str.startswith(p) for p in ignored_prefixes) or rel_str == "report.json":
                    continue
                full_path = repo_root / rel_str
                if full_path.is_file():
                    hasher.update(f"UNTRACKED:{rel_str}\n".encode("utf-8"))
                    try:
                        hasher.update(full_path.read_bytes())
                    except Exception:
                        pass
    except Exception:
        pass

    return hasher.hexdigest()


def load_ship_config(repo_root: Path, explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from .ship.json."""
    default_config: Dict[str, Any] = {
        "version": 1,
        "project": {
            "name": "",
            "root": ".",
            "scope": ".",
        },
        "gates": {
            "design": {
                "adr_dir": "docs/adr",
                "specs_dir": "openspec/specs",
            },
            "spike": {
                "timeout": 60.0,
                "concurrency": 1,
            },
            "implementation": {
                "test": "",
                "typecheck": "",
                "lint": "",
            },
            "simplify": {
                "max_debt": 0,
                "strict": True,
            },
            "audit": {
                "base_branch": "main",
                "reviewers": ["correctness", "concurrency", "design", "judge"],
                "max_iterations": 3,
            },
            "delivery": {
                "target_branch": "main",
                "clean_worktree": True,
                "sync_specs": True,
                "archive_packages": True,
            },
        },
        "create_git_tag": False,
        "telemetry": {
            "sink": None,
        },
        "config_source": None,
    }

    config_file: Optional[Path] = None
    if explicit_path:
        p = Path(explicit_path)
        if not p.is_absolute():
            p = repo_root / p
        if p.exists() and p.is_file():
            config_file = p
    else:
        candidate = repo_root / ".ship.json"
        if candidate.exists() and candidate.is_file():
            config_file = candidate

    if not config_file:
        return default_config

    try:
        content = config_file.read_text(encoding="utf-8", errors="replace")
        loaded: Dict[str, Any] = json.loads(content)
        if not isinstance(loaded, dict):
            return default_config

        def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
            for k, v in source.items():
                if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                    deep_merge(target[k], v)
                else:
                    target[k] = v

        deep_merge(default_config, loaded)
        try:
            default_config["config_source"] = str(config_file.relative_to(repo_root))
        except ValueError:
            default_config["config_source"] = str(config_file)
    except Exception as e:
        default_config["config_error"] = str(e)

    return default_config


def get_git_info(repo_root: Path) -> Dict[str, Any]:
    """Gather git branch, commit SHA, tree hash, and working tree status."""
    info: Dict[str, Any] = {
        "is_git": False,
        "branch": "unknown",
        "commit": None,
        "tree_hash": None,
        "is_clean": True,
        "modified_count": 0,
        "untracked_count": 0,
        "modified_source_files": [],
        "working_tree_fingerprint": None,
    }
    if git_out(repo_root, "rev-parse", "--is-inside-work-tree") != "true":
        return info

    info["is_git"] = True
    info["branch"] = git_out(repo_root, "branch", "--show-current") or git_out(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    info["commit"] = git_out(repo_root, "rev-parse", "HEAD") or None
    info["tree_hash"] = git_out(repo_root, "rev-parse", "HEAD^{tree}") or None

    try:
        status_res = git_cmd(repo_root, "status", "--porcelain")
        status_lines = [l for l in status_res.stdout.splitlines() if l.strip()]
        info["is_clean"] = len(status_lines) == 0
        info["modified_count"] = sum(1 for l in status_lines if not l.startswith("??"))
        info["untracked_count"] = sum(1 for l in status_lines if l.startswith("??"))

        # Identify unreviewed source modifications (filtering out scratch, archive, and internal state)
        ignored_prefixes = (".scratch/", "scratch/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
        modified_sources = []
        for l in status_lines:
            filename = l[3:].strip()
            if " -> " in filename:
                filename = filename.split(" -> ", 1)[1].strip()
            if filename.startswith('"') and filename.endswith('"'):
                filename = filename[1:-1]
            if not any(filename.startswith(p) for p in ignored_prefixes) and filename not in {"report.json", ".gitignore"}:
                modified_sources.append(filename)
        info["modified_source_files"] = modified_sources
        info["working_tree_fingerprint"] = compute_working_tree_fingerprint(repo_root)
    except Exception:
        pass
    return info


def inspect_adrs(repo_root: Path) -> List[Dict[str, Any]]:
    """Scan docs/adr/ for architecture decision records."""
    adr_dir = repo_root / "docs" / "adr"
    adrs = []
    if not adr_dir.exists():
        return adrs

    for path in sorted(adr_dir.glob("*.md")):
        if path.name.lower() in {"readme.md", "template.md"}:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        status_match = re.search(r"\*\*Status\*\*:\s*([A-Za-z0-9_-]+)", content, re.IGNORECASE)
        status = status_match.group(1).upper() if status_match else "UNKNOWN"
        adrs.append({
            "name": path.name,
            "path": str(path.relative_to(repo_root)),
            "status": status,
        })
    return adrs


def get_active_change(repo_root: Path) -> Optional[str]:
    """Read active change ID from .ship/state.json."""
    ledger_data = read_json_file(repo_root / ".ship" / "state.json")
    if isinstance(ledger_data, dict) and ledger_data.get("active_change_id"):
        return ledger_data["active_change_id"]
    return None


@contextmanager
def ledger_lock(repo_root: Path, timeout_sec: float = 10.0):
    """File lock around .ship/state.json mutations to prevent concurrent write clobbering."""
    ship_dir = repo_root / ".ship"
    ship_dir.mkdir(parents=True, exist_ok=True)
    lock_file = ship_dir / "state.lock"

    fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o666)
    locked = False
    try:
        if fcntl:
            start_time = time.time()
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except (BlockingIOError, IOError, OSError):
                    if time.time() - start_time >= timeout_sec:
                        fcntl.flock(fd, fcntl.LOCK_EX)
                        locked = True
                        break
                    time.sleep(0.01)
        yield
    finally:
        if locked and fcntl:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                pass
        try:
            os.close(fd)
        except Exception:
            pass


def set_active_change(repo_root: Path, change: str) -> None:
    """Persist active change to .ship/state.json."""
    with ledger_lock(repo_root):
        ledger = load_ledger(repo_root, auto_sync=False)
        ledger_path = get_ledger_path(repo_root)
        if not ledger.get("changes") and not ledger_path.exists():
            ledger = sync_ledger_from_workspace(repo_root)
        ledger["active_change_id"] = change.strip()
        save_ledger(repo_root, ledger)


def clear_active_change(repo_root: Path, change: Optional[str] = None) -> None:
    """Clear .ship/state.json active_change_id."""
    with ledger_lock(repo_root):
        state_file = repo_root / ".ship" / "state.json"
        if state_file.exists():
            data = read_json_file(state_file, {})
            if isinstance(data, dict) and (change is None or data.get("active_change_id") == (change.strip() if change else None)):
                data["active_change_id"] = None
                save_ledger(repo_root, data)


def inspect_openspec(
    repo_root: Path,
    target_change: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scan openspec/changes/ for active change packages and parse tasks.md."""
    resolved_target = target_change
    changes_dir = repo_root / "openspec" / "changes"
    archive_dir = repo_root / "openspec" / "archive"
    packages = []
    
    def target_is_archived(target: str) -> bool:
        if archive_dir.exists():
            for d in archive_dir.iterdir():
                if d.is_dir() and (d.name == target or d.name.endswith(f"-{target}")):
                    return True
        state_file = repo_root / ".ship" / "state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                entry = data.get("changes", {}).get(target, {})
                if entry.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
                    return True
            except Exception:
                pass
        return False

    if not changes_dir.exists():
        if resolved_target and not target_is_archived(resolved_target):
            raise ValueError(f"Specified OpenSpec change '{resolved_target}' not found (openspec/changes does not exist).")
        return packages

    # Explicit change validation: if target specified, it MUST exist or be archived
    if resolved_target:
        target_dir = changes_dir / resolved_target
        if not target_dir.exists() or not target_dir.is_dir():
            if target_is_archived(resolved_target):
                return packages
            available = [d.name for d in sorted(changes_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
            avail_str = f" Available: {', '.join(available)}" if available else " (no packages found)"
            raise ValueError(f"Specified OpenSpec change '{resolved_target}' not found under openspec/changes/.{avail_str}")

    active_persisted = resolved_target or get_active_change(repo_root)
    # If active_persisted was read from file, verify existence; clear if stale
    if active_persisted and not resolved_target:
        if not (changes_dir / active_persisted).is_dir():
            clear_active_change(repo_root)
            active_persisted = None

    for change_dir in changes_dir.iterdir():
        if not change_dir.is_dir() or change_dir.name.startswith("."):
            continue

        tasks_file = change_dir / "tasks.md"
        tasks_found = False
        total_tasks = 0
        completed_tasks = 0
        next_task = None

        if tasks_file.exists():
            tasks_found = True
            content = tasks_file.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("- [ ]") or stripped.startswith("* [ ]"):
                    total_tasks += 1
                    if next_task is None:
                        next_task = stripped[5:].strip()
                elif stripped.startswith(("- [x]", "- [X]", "* [x]", "* [X]")):
                    total_tasks += 1
                    completed_tasks += 1

        proposal_file = change_dir / "proposal.md"
        specs_dir = change_dir / "specs"

        try:
            mtime = change_dir.stat().st_mtime
        except Exception:
            mtime = 0.0

        packages.append({
            "change": change_dir.name,
            "path": str(change_dir.relative_to(repo_root)),
            "has_proposal": proposal_file.exists(),
            "has_specs": specs_dir.exists() and any(specs_dir.iterdir()) if specs_dir.exists() else False,
            "has_tasks": tasks_found,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": total_tasks - completed_tasks,
            "next_task": next_task,
            "mtime": mtime,
            "is_active_target": (change_dir.name == active_persisted),
        })

    packages.sort(
        key=lambda p: (
            1 if p["is_active_target"] else 0,
            1 if p["pending_tasks"] > 0 else 0,
            p["mtime"],
            p["change"],
        ),
        reverse=True,
    )

    return packages


def inspect_archived_openspec(repo_root: Path) -> List[Dict[str, Any]]:
    """Scan openspec/archive/ for completed historical change packages."""
    archive_dir = repo_root / "openspec" / "archive"
    archived = []
    if not archive_dir.exists():
        return archived

    for child in sorted(archive_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            archived.append({
                "name": child.name,
                "path": str(child.relative_to(repo_root)),
            })
    return archived


def inspect_living_specs(repo_root: Path) -> List[Dict[str, Any]]:
    """Scan openspec/specs/ for living cumulative system specifications."""
    specs_dir = repo_root / "openspec" / "specs"
    specs = []
    if not specs_dir.exists():
        return specs

    for child in sorted(specs_dir.glob("*.md")):
        specs.append({
            "name": child.name,
            "path": str(child.relative_to(repo_root)),
        })
    return specs


REMOVAL_TITLE_MARKER = re.compile(
    r"(?:\s*[\[\(]\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\s*[\]\)]|\s*--\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\b|\s*\bSTATUS:\s*(?:REMOVED|DELETED)\b)",
    re.IGNORECASE,
)

REMOVAL_BODY_MARKER = re.compile(
    r"^\s*(?:[\[\(]\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\s*[\]\)]|--\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\b|\bSTATUS:\s*(?:REMOVED|DELETED)\b)",
    re.IGNORECASE,
)


def normalize_req_title(raw_title: str) -> str:
    """Normalize requirement title for matching, removing explicit removal markers, brackets, and markdown formatting."""
    cleaned = REMOVAL_TITLE_MARKER.sub("", raw_title).strip()
    cleaned = cleaned.strip("*`\"' ")
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    cleaned = re.sub(r"^\[[A-Za-z0-9_-]+\]\s*", "", cleaned)
    cleaned = re.sub(r"^[A-Za-z0-9_-]+:\s*", "", cleaned)
    return cleaned.strip("*`\"' ").strip().lower()


def parse_requirements_doc(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse a markdown spec into preamble and individual requirement sections."""
    lines = content.splitlines(keepends=True)
    req_header_regex = re.compile(r"^(#{1,4})\s+Requirement:\s*(.+)$", re.IGNORECASE)

    preamble_lines: List[str] = []
    requirements: List[Dict[str, Any]] = []
    current_req: Optional[Dict[str, Any]] = None

    for line in lines:
        match = req_header_regex.match(line.rstrip("\r\n"))
        if match:
            if current_req is not None:
                requirements.append(current_req)
            level = match.group(1)
            raw_title = match.group(2).strip()
            is_removal = bool(REMOVAL_TITLE_MARKER.search(raw_title))
            norm_key = normalize_req_title(raw_title)
            current_req = {
                "header": line.rstrip("\r\n"),
                "level": level,
                "raw_title": raw_title,
                "key": norm_key,
                "body_lines": [],
                "is_removal": is_removal,
            }
        else:
            if current_req is None:
                preamble_lines.append(line)
            else:
                current_req["body_lines"].append(line)

    if current_req is not None:
        requirements.append(current_req)

    # Check body lines for removal markers if not explicit in header
    for req in requirements:
        if not req["is_removal"]:
            for bline in req["body_lines"][:3]:
                stripped = bline.strip()
                if stripped and REMOVAL_BODY_MARKER.match(stripped):
                    req["is_removal"] = True
                    break

    preamble = "".join(preamble_lines)
    return preamble, requirements


def merge_spec_requirements(living_content: str, delta_content: str) -> str:
    """Merge delta requirements into living spec, preserving untouched requirements."""
    living_preamble, living_reqs = parse_requirements_doc(living_content)
    delta_preamble, delta_reqs = parse_requirements_doc(delta_content)

    # If neither document uses Requirement headings, fall back
    if not living_reqs and not delta_reqs:
        if not living_content.strip():
            return delta_content
        return living_content.rstrip() + "\n\n" + delta_content.strip() + "\n"

    # If living spec had no requirements but delta does:
    if not living_reqs and delta_reqs:
        return delta_content

    # Index living requirements
    living_dict: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    for req in living_reqs:
        living_dict[req["key"]] = req

    # Apply delta requirements
    for d_req in delta_reqs:
        key = d_req["key"]
        if d_req["is_removal"]:
            if key in living_dict:
                del living_dict[key]
        else:
            # Add or update
            living_dict[key] = d_req

    # Reconstruct document
    preamble = living_preamble if living_preamble.strip() else delta_preamble
    result: List[str] = []
    if preamble.strip():
        result.append(preamble.rstrip())

    for req in living_dict.values():
        clean_header = REMOVAL_TITLE_MARKER.sub("", req["header"]).rstrip()
        body = "".join(req["body_lines"]).strip()
        if body:
            result.append(f"{clean_header}\n{body}")
        else:
            result.append(clean_header)

    return "\n\n".join(result).strip() + "\n"


def is_test_evidence_passing(evidence: Any) -> bool:
    """Validate that test evidence explicitly confirms passing tests using strict structured checks."""
    if evidence is None:
        return False
    if isinstance(evidence, bool):
        return evidence
    if isinstance(evidence, dict):
        if not evidence:
            return False
        # 1. Exit code must be 0
        if "exit_code" in evidence:
            if evidence["exit_code"] != 0:
                return False
        # 2. Passed flag must be boolean True
        if "passed" in evidence:
            if evidence["passed"] is not True:
                return False
        # 3. Tests run count must be positive integer (> 0)
        if "tests_run" in evidence:
            if not isinstance(evidence["tests_run"], int) or evidence["tests_run"] <= 0:
                return False
        # 4. Failure/error counts must be 0
        for fail_key in ("failed", "errors", "failures"):
            if fail_key in evidence and isinstance(evidence[fail_key], (int, float)):
                if evidence[fail_key] > 0:
                    return False
        # 5. Status string
        if "status" in evidence:
            st = str(evidence["status"]).lower().strip()
            if st not in {"pass", "passed", "ok", "success", "green"}:
                return False

        # Affirmative passing criteria:
        has_positive = (
            (evidence.get("passed") is True)
            or ("exit_code" in evidence and evidence["exit_code"] == 0 and evidence.get("tests_run", 1) > 0)
            or ("status" in evidence and str(evidence["status"]).lower().strip() in {"pass", "passed", "ok", "success", "green"})
            or ("test_evidence" in evidence and is_test_evidence_passing(evidence["test_evidence"]))
        )
        return has_positive

    if isinstance(evidence, str):
        ev_clean = evidence.strip()
        if not ev_clean:
            return False
        ev_lower = ev_clean.lower()
        # Direct word matches like "PASS", "PASSED", "SUCCESS", "OK", "GREEN"
        if ev_lower in {"pass", "passed", "ok", "success", "green"}:
            return True

        # Explicit rejection of negative phrases
        if re.search(r"\b(?:not\s+passed|failed|errors?:\s*[1-9]|failure|crash)\b", ev_lower):
            return False

        # Parse structured pattern: e.g. "0 failures, 12 passed" or "12 passed, 0 failures" or "12 tests passed"
        m_fail = re.search(r"(\d+)\s*(?:tests?\s+)?(?:failures?|errors?|failed)", ev_lower)
        m_pass = re.search(r"(\d+)\s*(?:tests?\s+)?passed", ev_lower)
        if m_fail or m_pass:
            fail_count = int(m_fail.group(1)) if m_fail else 0
            pass_count = int(m_pass.group(1)) if m_pass else 0
            return fail_count == 0 and pass_count > 0

        # General "all ... tests passed" phrase
        if re.search(r"\ball\s+(?:\d+\s+)?tests?\s+passed\b", ev_lower):
            return True

        # Unittest output: "Ran N tests in ...\n\nOK"
        if re.search(r"Ran\s+([1-9][0-9]*)\s+tests?.*?\bOK\b", ev_clean, re.DOTALL):
            return True

        # Pytest summary: "X passed in Ys"
        m_pytest = re.search(r"([1-9][0-9]*)\s+passed\b", ev_lower)
        if m_pytest and not re.search(r"[1-9][0-9]*\s+(?:failed|error)", ev_lower):
            return True

        return False

    return False


def is_spike_completed(spike_dir: Path) -> bool:
    """Check if a spike directory contains verified completion evidence or verdict."""
    for marker in [".completed", ".done"]:
        if (spike_dir / marker).exists():
            return True

    for report_file in [spike_dir / "report.json", spike_dir / "verdict.json"]:
        if report_file.exists():
            try:
                content = report_file.read_text(encoding="utf-8").strip()
                if not content:
                    return False
                data = json.loads(content)
                if not isinstance(data, dict):
                    return False
                verdict = str(data.get("verdict", "")).strip().upper()
                if verdict in {"CONFIRMED", "REFUTED", "QUALIFIED", "PASS", "SUCCESS"}:
                    return True
                st = str(data.get("status", "")).strip().lower()
                if st in {"complete", "completed", "done"} and (data.get("recommendation") or data.get("outcome")):
                    return True
            except Exception:
                # Corrupt or interrupted JSON must never count as completed
                return False

    for md_file in spike_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace").strip()
            # Headings alone do NOT establish completion; an explicit verdict is required
            verdict_match = re.search(
                r"\bVerdict\*{0,2}:\s*\*{0,2}(CONFIRMED|REFUTED|QUALIFIED|PASS|APPROVED)\b",
                content,
                re.IGNORECASE,
            )
            if verdict_match and len(content.splitlines()) >= 5:
                return True
        except Exception:
            return False

    return False


NON_SPIKE_SCRATCH_DIRS = {
    "archive", "coverage", "logs", "cache", "tmp", "temp", "dist",
    "build", "node_modules", "venv", ".venv", "__pycache__", "checkpoints",
}


def is_evidence_dir(dir_path: Path) -> bool:
    """Distinguish audit and delivery evidence directories from empirical spikes independently of package location."""
    for evidence_name in ("delivery_evidence.json", "review_report.json", "audit_report.json"):
        if (dir_path / evidence_name).exists():
            return True
    report_file = dir_path / "report.json"
    if report_file.exists():
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and (
                data.get("reviewer") in {"judge", "review_judge", "correctness", "concurrency", "design"}
                or "judge_report" in data
            ):
                return True
        except Exception:
            pass
    return False


def inspect_spikes(repo_root: Path) -> List[str]:
    """Scan .scratch/ or scratch/ for active, uncompleted spikes."""
    spikes = []
    changes_dir = repo_root / "openspec" / "changes"
    archive_dir = repo_root / "openspec" / "archive"

    known_packages = set()
    if changes_dir.exists():
        known_packages.update(d.name for d in changes_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    if archive_dir.exists():
        for d in archive_dir.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                known_packages.add(d.name)
                m = re.match(r"^\d{4}-\d{2}-\d{2}-(.+)$", d.name)
                if m:
                    change_part = m.group(1)
                    known_packages.add(change_part)
                    if "-" in change_part:
                        known_packages.add(re.sub(r"-\d+$", "", change_part))

    for base in [repo_root / ".scratch", repo_root / "scratch"]:
        if base.exists() and base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    if (child.name in NON_SPIKE_SCRATCH_DIRS
                            or child.name.startswith("rollback_")
                            or child.name in known_packages):
                        continue
                    if is_evidence_dir(child):
                        continue
                    if not is_spike_completed(child):
                        spikes.append(str(child.relative_to(repo_root)))
    return spikes


def validate_judge_report_contract(report: Any, allow_delivery_keys: bool = False) -> List[str]:
    """Validate a Judge report dict against the canonical 6-field report contract."""
    if not isinstance(report, dict):
        return ["Judge report must be a JSON object"]

    top_required = {"reviewer", "status", "findings", "coverage", "questions", "routing_notes"}
    missing = top_required - report.keys()
    if missing:
        return [f"Judge report missing required field: {k}" for k in sorted(missing)]

    allowed_keys = set(top_required)
    if allow_delivery_keys:
        allowed_keys |= {
            "change", "verdict", "test_evidence",
            "commit", "snapshot", "tree_hash", "working_tree_fingerprint"
        }

    extra = report.keys() - allowed_keys
    if extra:
        return [f"Judge report has unexpected property: {k}" for k in sorted(extra)]

    errors = []
    if report.get("reviewer") != "judge":
        errors.append(f"Judge report reviewer must be 'judge', got '{report.get('reviewer')}'")
    if not isinstance(report.get("status"), str) or report.get("status") not in {"complete", "incomplete", "skipped"}:
        errors.append(f"Judge report status must be one of complete/incomplete/skipped, got '{report.get('status')}'")

    for list_field in ("coverage", "questions", "routing_notes"):
        val = report.get(list_field)
        if not isinstance(val, list):
            errors.append(f"Judge report field '{list_field}' must be an array")
        elif any(not isinstance(item, str) for item in val):
            errors.append(f"Judge report field '{list_field}' all items must be strings")

    findings = report.get("findings")
    if not isinstance(findings, list):
        errors.append("Judge report field 'findings' must be an array")
        return errors

    finding_required = {
        "id", "severity", "category", "file", "line", "title",
        "problem", "evidence", "impact", "recommendation", "confidence", "fixability"
    }
    severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    categories = {
        "SpecAlignment", "Correctness", "Concurrency", "Failure/Resilience",
        "Simplicity", "Maintainability", "Reuse", "Performance", "SOLID",
        "Patterns", "ProductionRisk"
    }
    fixabilities = {"autonomous", "requires-human"}
    id_regex = re.compile(r"^FINDING-[0-9]{3,}$")
    line_regex = re.compile(r"^L[1-9][0-9]*(-L[1-9][0-9]*)?$")

    seen_ids = set()
    for idx, finding in enumerate(findings):
        prefix = f"findings[{idx}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        f_missing = finding_required - finding.keys()
        if f_missing:
            for k in sorted(f_missing):
                errors.append(f"{prefix}.{k}: field is required")
        f_extra = finding.keys() - finding_required
        if f_extra:
            for k in sorted(f_extra):
                errors.append(f"{prefix}.{k}: unexpected property")

        if f_missing:
            continue

        fid = finding["id"]
        if not isinstance(fid, str) or not id_regex.match(fid):
            errors.append(f"{prefix}.id: must match pattern ^FINDING-[0-9]{{3,}}$")
        else:
            if fid in seen_ids:
                errors.append(f"Duplicate finding ID: {fid}")
            seen_ids.add(fid)

        if not isinstance(finding["severity"], str) or finding["severity"] not in severities:
            errors.append(f"{prefix}.severity: must be one of {sorted(severities)}")
        if not isinstance(finding["category"], str) or finding["category"] not in categories:
            errors.append(f"{prefix}.category: must be one of {sorted(categories)}")
        if not isinstance(finding["fixability"], str) or finding["fixability"] not in fixabilities:
            errors.append(f"{prefix}.fixability: must be one of {sorted(fixabilities)}")

        for str_field in ("title", "problem", "evidence", "impact", "recommendation"):
            val = finding.get(str_field)
            if not isinstance(val, str) or len(val.strip()) < 1:
                errors.append(f"{prefix}.{str_field}: must be a non-empty string")

        conf = finding.get("confidence")
        if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
            errors.append(f"{prefix}.confidence: must be a finite number between 0.0 and 1.0")

        path = finding.get("file")
        if not isinstance(path, str) or len(path.strip()) < 1:
            errors.append(f"{prefix}.file: must be a non-empty string")
        elif (Path(path).is_absolute() or ".." in Path(path).parts
                or "\\" in path or re.match(r"^[A-Za-z]:", path) or path == "."):
            errors.append(f"{fid}: file must be a repository-relative path")

        fline = finding.get("line")
        if not isinstance(fline, str) or not line_regex.match(fline):
            errors.append(f"{prefix}.line: must match pattern ^L[1-9][0-9]*(-L[1-9][0-9]*)?$")
        else:
            start, _, end = fline.partition("-L")
            if end and int(end) < int(start[1:]):
                errors.append(f"{fid}: line range ends before it starts")

    return errors


def parse_audit_report_file(p: Path, repo_root: Path) -> Dict[str, Any]:
    """Parse and validate an audit report file or delivery evidence envelope."""
    def make_err_report(err: str) -> Dict[str, Any]:
        return {
            "path": str(p.relative_to(repo_root)),
            "is_envelope": False,
            "reviewer": "unknown",
            "status": "fail",
            "verdict": "FAIL",
            "findings_count": 0,
            "critical_or_high_count": 0,
            "is_judge": False,
            "raw_test_evidence": None,
            "test_evidence_passed": False,
            "snapshot_sha": None,
            "snapshot_tree": None,
            "snapshot_fingerprint": None,
            "judge_report_valid": False,
            "judge_report_errors": [err],
        }

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return make_err_report(f"Could not read report file: {e}")

    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return make_err_report("Report file is not a JSON object")
    except Exception as e:
        return make_err_report(f"Invalid JSON in report file: {e}")

    # Support Delivery Evidence Envelope format
    is_envelope = "judge_report" in data or "snapshot" in data
    raw_judge_report = data.get("judge_report") if is_envelope else data
    judge_data = raw_judge_report if isinstance(raw_judge_report, dict) else {}
    snapshot_info = data.get("snapshot") if is_envelope and isinstance(data.get("snapshot"), dict) else {}

    judge_report_errors: List[str] = []
    if is_envelope:
        if raw_judge_report is None:
            judge_report_errors = ["Envelope is missing required 'judge_report' object"]
        elif not isinstance(raw_judge_report, dict):
            judge_report_errors = ["Envelope 'judge_report' must be a JSON object"]
        else:
            judge_report_errors = validate_judge_report_contract(raw_judge_report, allow_delivery_keys=False)
    else:
        judge_report_errors = validate_judge_report_contract(data, allow_delivery_keys=True)

    judge_report_valid = (len(judge_report_errors) == 0)

    findings = judge_data.get("findings", []) if isinstance(judge_data.get("findings"), list) else []
    critical_or_high = [
        f for f in findings
        if isinstance(f, dict) and f.get("severity") in {"CRITICAL", "HIGH"}
    ]
    reviewer = str(judge_data.get("reviewer", data.get("reviewer", "unknown"))).lower()
    status = str(judge_data.get("status", data.get("status", "unknown"))).lower()

    # Verdict and test evidence can be in envelope or top-level
    verdict = str(data.get("verdict", judge_data.get("verdict", ""))).strip().upper()
    raw_test_evidence = data.get("test_evidence") if "test_evidence" in data else judge_data.get("test_evidence")
    test_evidence_passed = is_test_evidence_passing(raw_test_evidence)

    snapshot_sha = snapshot_info.get("commit") or data.get("commit")
    snapshot_tree = snapshot_info.get("tree_hash") or data.get("tree_hash")
    snapshot_fingerprint = snapshot_info.get("working_tree_fingerprint") or data.get("working_tree_fingerprint")

    change = data.get("change") or snapshot_info.get("change") or judge_data.get("change")

    return {
        "path": str(p.relative_to(repo_root)),
        "is_envelope": is_envelope,
        "reviewer": reviewer,
        "status": status,
        "verdict": verdict,
        "findings_count": len(findings),
        "critical_or_high_count": len(critical_or_high),
        "is_judge": reviewer in {"judge", "review_judge"},
        "raw_test_evidence": raw_test_evidence,
        "test_evidence_passed": test_evidence_passed,
        "snapshot_sha": str(snapshot_sha) if snapshot_sha else None,
        "snapshot_tree": str(snapshot_tree) if snapshot_tree else None,
        "snapshot_fingerprint": str(snapshot_fingerprint) if snapshot_fingerprint else None,
        "change": str(change).strip() if change else None,
        "judge_report_valid": judge_report_valid,
        "judge_report_errors": judge_report_errors,
    }


def inspect_audit_reports(
    repo_root: Path,
    change: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    target = change
    report_names = ("delivery_evidence.json", "review_report.json", "audit_report.json")
    candidate_paths: List[Path] = []
    if target:
        for name in report_names:
            candidate_paths.extend([
                repo_root / ".scratch" / target / name,
                repo_root / "scratch" / target / name,
                repo_root / ".scratch" / f"{Path(name).stem}_{target}.json",
                repo_root / "scratch" / f"{Path(name).stem}_{target}.json",
            ])
    for name in report_names:
        candidate_paths.extend([
            repo_root / ".scratch" / name,
            repo_root / "scratch" / name,
        ])
    candidate_paths.append(repo_root / "report.json")

    for p in candidate_paths:
        if p.exists():
            return parse_audit_report_file(p, repo_root)

    return None


# ---------------------------------------------------------------------------
# Tier 1: State Ledger (.ship/state.json)
# ---------------------------------------------------------------------------

def get_ledger_path(repo_root: Path) -> Path:
    """Return path to .ship/state.json."""
    return repo_root / ".ship" / "state.json"


def ensure_gitignore_has_ship(repo_root: Path) -> None:
    """Ensure .ship/ is ignored in git without creating unwanted untracked working-tree files."""
    git_dir = repo_root / ".git"
    if git_dir.is_dir():
        exclude_file = git_dir / "info" / "exclude"
        try:
            exclude_file.parent.mkdir(parents=True, exist_ok=True)
            content = exclude_file.read_text(encoding="utf-8") if exclude_file.exists() else ""
            lines = [l.strip() for l in content.splitlines()]
            if ".ship" not in lines and ".ship/" not in lines:
                with exclude_file.open("a", encoding="utf-8") as f:
                    if content and not content.endswith("\n"):
                        f.write("\n")
                    f.write(".ship/\n")
        except Exception:
            pass

    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        try:
            content = gitignore.read_text(encoding="utf-8")
            lines = [l.strip() for l in content.splitlines()]
            if ".ship" not in lines and ".ship/" not in lines:
                with gitignore.open("a", encoding="utf-8") as f:
                    if content and not content.endswith("\n"):
                        f.write("\n")
                    f.write(".ship/\n")
        except Exception:
            pass


def make_default_audit_evidence() -> Dict[str, Any]:
    """Default audit evidence structure."""
    return {
        "verdict": None,
        "status": None,
        "reviewer": None,
        "findings_count": 0,
        "critical_or_high_count": 0,
        "test_evidence_passed": None,
        "report_path": None,
        "git_note_oid": None,
        "snapshot_fingerprint": None,
    }


def make_default_evidence() -> Dict[str, Any]:
    """Default lifecycle evidence structure."""
    return {
        "design": {"adr": None, "status": None},
        "spike": {"status": "NONE", "verdict": None, "dir": None},
        "implementation": {
            "status": "PENDING",
            "tests_passed": None,
            "failed_count": 0,
            "evidence_ref": None,
        },
        "simplify": {"status": "PENDING", "debt_count": 0},
        "audit": make_default_audit_evidence(),
        "delivery": {
            "status": "PENDING",
            "archived_path": None,
            "commit": None,
            "trailers": [],
        },
    }


def create_empty_change_entry(change_id: str) -> Dict[str, Any]:
    """Create a default ChangeState entry according to the lifecycle schema."""
    return {
        "change_id": change_id,
        "phase": "design",
        "task_status": {
            "total": 0,
            "completed": 0,
            "pending": 0,
            "in_progress": None,
            "next": None,
        },
        "blockers": [],
        "revision_counter": 0,
        "evidence": make_default_evidence(),
        "checkpoints": {},
    }


def save_ledger(repo_root: Path, ledger: Dict[str, Any]) -> None:
    """Atomically write ledger to .ship/state.json using NamedTemporaryFile + os.replace."""
    ship_dir = repo_root / ".ship"
    ship_dir.mkdir(parents=True, exist_ok=True)
    ensure_gitignore_has_ship(repo_root)
    ledger_path = get_ledger_path(repo_root)

    temp_fd, temp_path = tempfile.mkstemp(prefix="state_", suffix=".json.tmp", dir=str(ship_dir))
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, ledger_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise


def sync_ledger_from_workspace(repo_root: Path, target_change_id: Optional[str] = None) -> Dict[str, Any]:
    """Reconcile and self-heal .ship/state.json from disk artifacts (OpenSpec, ADRs, Spikes, Audits)."""
    ledger_path = get_ledger_path(repo_root)
    loaded = read_json_file(ledger_path)
    existing: Dict[str, Any] = loaded if isinstance(loaded, dict) and "changes" in loaded else {}

    changes: Dict[str, Any] = existing.get("changes", {})
    active_change_id = target_change_id or existing.get("active_change_id") or get_active_change(repo_root)

    packages = inspect_openspec(repo_root, target_change=None)
    adrs = inspect_adrs(repo_root)
    spikes = inspect_spikes(repo_root)

    discovered_changes = [p["change"] for p in packages]
    if not discovered_changes:
        if active_change_id and existing.get("changes", {}).get(active_change_id, {}).get("evidence", {}).get("delivery", {}).get("status") != "ARCHIVED":
            discovered_changes = [active_change_id]
        elif adrs:
            discovered_changes = [adrs[0]["name"].replace(".md", "").lower()]
        else:
            discovered_changes = ["default"]

    for change in discovered_changes:
        if change not in changes:
            changes[change] = create_empty_change_entry(change)
        entry = changes[change]

        # Do not demote already archived changes
        if entry.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
            entry["phase"] = "delivery"
            continue

        matched_pkg = next((p for p in packages if p["change"] == change), None)
        if matched_pkg:
            entry["task_status"]["total"] = matched_pkg["total_tasks"]
            entry["task_status"]["completed"] = matched_pkg["completed_tasks"]
            entry["task_status"]["pending"] = matched_pkg["pending_tasks"]
            entry["task_status"]["next"] = matched_pkg["next_task"]
            entry["task_status"]["in_progress"] = matched_pkg["next_task"]

        if adrs:
            entry["evidence"]["design"]["adr"] = adrs[0]["name"]
            entry["evidence"]["design"]["status"] = adrs[0].get("status")

        if spikes:
            entry["evidence"]["spike"]["status"] = "ACTIVE"
            entry["evidence"]["spike"]["dir"] = spikes[0]
        else:
            if entry["evidence"]["spike"].get("status") == "ACTIVE":
                entry["evidence"]["spike"]["status"] = "PASSED"

        audit = inspect_audit_reports(repo_root, change=change)
        if audit:
            verdict = audit.get("verdict") or audit.get("status")
            entry["evidence"]["audit"]["verdict"] = verdict
            entry["evidence"]["audit"]["status"] = audit.get("status")
            entry["evidence"]["audit"]["reviewer"] = audit.get("reviewer")
            entry["evidence"]["audit"]["findings_count"] = audit.get("findings_count", 0)
            entry["evidence"]["audit"]["critical_or_high_count"] = audit.get("critical_or_high_count", 0)
            entry["evidence"]["audit"]["test_evidence_passed"] = audit.get("test_evidence_passed")
            entry["evidence"]["audit"]["report_path"] = audit.get("path") or audit.get("report_file")
            entry["evidence"]["audit"]["snapshot_fingerprint"] = audit.get("snapshot_fingerprint")

        chk_dir = repo_root / ".scratch" / "checkpoints"
        if chk_dir.exists():
            for cf in chk_dir.glob(f"{change}_*.json"):
                cdata = read_json_file(cf)
                if isinstance(cdata, dict):
                    gate_k = cdata.get("gate", cf.stem.replace(f"{change}_", ""))
                    entry["checkpoints"][gate_k] = cdata

        existing_test_blockers = [b for b in entry.get("blockers", []) if b.startswith("Tests:")]
        if entry.get("evidence", {}).get("implementation", {}).get("tests_passed") is False:
            failed_cnt = entry["evidence"]["implementation"].get("failed_count", 1)
            t_blocker = f"Tests: {failed_cnt} test(s) failing"
            if t_blocker not in existing_test_blockers:
                existing_test_blockers.append(t_blocker)

        blockers: List[str] = list(existing_test_blockers)
        if spikes:
            entry["phase"] = "spike"
            blockers.append(f"Spike active in {spikes[0]}")
        elif not matched_pkg or matched_pkg["total_tasks"] == 0:
            entry["phase"] = "design"
        elif matched_pkg["pending_tasks"] > 0 or any(b.startswith("Tests:") for b in blockers):
            entry["phase"] = "implementation"
        else:
            audit_ev = entry["evidence"]["audit"]
            crit = audit_ev.get("critical_or_high_count", 0)
            verd = audit_ev.get("verdict", "")
            if crit > 0:
                blockers.append(f"Audit has {crit} unresolved CRITICAL/HIGH finding(s)")
            if verd in {"FAIL", "FAILED", "REJECTED"}:
                blockers.append(f"Audit verdict is {verd}")

            if audit_ev.get("verdict") in {"PASS", "APPROVED"} and crit == 0 and not blockers:
                entry["phase"] = "delivery"
            else:
                entry["phase"] = "audit"

        entry["blockers"] = blockers
        if entry.get("revision_counter", 0) == 0:
            entry["revision_counter"] = 1

    if not active_change_id and discovered_changes and discovered_changes != ["default"]:
        active_change_id = discovered_changes[0]

    new_ledger = {
        "version": 1,
        "active_change_id": active_change_id,
        "changes": changes,
    }
    try:
        save_ledger(repo_root, new_ledger)
    except Exception:
        pass
    return new_ledger


def load_ledger(repo_root: Path, auto_sync: bool = True) -> Dict[str, Any]:
    """Load authoritative workflow state from .ship/state.json, self-healing if missing."""
    ledger_path = get_ledger_path(repo_root)
    data = read_json_file(ledger_path)
    if isinstance(data, dict) and "changes" in data:
        return data
    if auto_sync:
        return sync_ledger_from_workspace(repo_root)
    return {"version": 1, "active_change_id": None, "changes": {}}


def mutate_change_state(
    repo_root: Path,
    change_id: str,
    updater: Any,
    set_active: bool = True,
) -> Dict[str, Any]:
    """Safely mutate a specific change in .ship/state.json with file locking and increment revision counter."""
    with ledger_lock(repo_root):
        ledger = load_ledger(repo_root, auto_sync=False)
        ledger_path = get_ledger_path(repo_root)
        if not ledger.get("changes") and not ledger_path.exists():
            ledger = sync_ledger_from_workspace(repo_root)
        changes = ledger.setdefault("changes", {})
        if change_id not in changes:
            changes[change_id] = create_empty_change_entry(change_id)
        entry = changes[change_id]
        updater(entry)
        entry["revision_counter"] = entry.get("revision_counter", 0) + 1
        if set_active:
            ledger["active_change_id"] = change_id
        elif ledger.get("active_change_id") == change_id:
            ledger["active_change_id"] = None
        save_ledger(repo_root, ledger)
        return entry


# ---------------------------------------------------------------------------
# Tier 2: Git Notes (refs/notes/ship-evidence)
# ---------------------------------------------------------------------------

GIT_NOTES_REF = "refs/notes/ship-evidence"


def attach_git_note_evidence(
    repo_root: Path,
    commit_sha: str,
    evidence_type: str,
    data: Dict[str, Any],
    ref: str = GIT_NOTES_REF,
    change_id: Optional[str] = None,
) -> Optional[str]:
    """Attach structured JSON validation evidence to a commit object via git notes, namespaced by change ID."""
    if not get_git_info(repo_root).get("is_git") or not commit_sha:
        return None
    resolved_sha = git_out(repo_root, "rev-parse", "--verify", commit_sha)
    if not resolved_sha:
        return None

    raw_note = git_out(repo_root, "notes", f"--ref={ref}", "show", resolved_sha)
    try:
        existing_evidence = json.loads(raw_note) if raw_note else {}
    except Exception:
        existing_evidence = {"raw_previous_note": raw_note}

    cid = change_id or data.get("change") or get_active_change(repo_root) or "default"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    fingerprint = compute_working_tree_fingerprint(repo_root)

    changes = existing_evidence.setdefault("changes", {})
    change_entry = changes.setdefault(cid, {})

    runs = change_entry.setdefault(f"{evidence_type}_runs", [])
    runs.append({
        "timestamp": now_iso,
        "commit": resolved_sha,
        "fingerprint": fingerprint,
        "change_id": cid,
        "evidence_type": evidence_type,
        "data": data,
    })

    change_entry[evidence_type] = data
    change_entry["last_updated"] = now_iso
    existing_evidence[evidence_type] = data
    existing_evidence["last_change_id"] = cid
    existing_evidence["last_updated"] = now_iso

    res = git_cmd(repo_root, "notes", f"--ref={ref}", "add", "-f", "-m", json.dumps(existing_evidence, indent=2), resolved_sha)
    return resolved_sha if res.returncode == 0 else None


def read_git_note_evidence(
    repo_root: Path,
    commit_sha: str,
    ref: str = GIT_NOTES_REF,
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read and parse structured JSON evidence from git notes on a commit."""
    if not get_git_info(repo_root).get("is_git") or not commit_sha:
        return {}
    resolved_sha = git_out(repo_root, "rev-parse", "--verify", commit_sha)
    if not resolved_sha:
        return {}
    raw_note = git_out(repo_root, "notes", f"--ref={ref}", "show", resolved_sha)
    try:
        data = json.loads(raw_note) if raw_note else {}
        if isinstance(data, dict):
            if change_id and "changes" in data and change_id in data["changes"]:
                return data["changes"][change_id]
            return data
    except Exception:
        pass
    return {}


def merge_note_payloads(local_payload: Dict[str, Any], remote_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Non-destructively merge two structured JSON note payloads."""
    merged = dict(local_payload)
    for k, v in remote_payload.items():
        if k not in merged:
            merged[k] = v

    local_changes = merged.setdefault("changes", {})
    remote_changes = remote_payload.get("changes", {})
    if isinstance(remote_changes, dict):
        for cid, r_entry in remote_changes.items():
            if cid not in local_changes:
                local_changes[cid] = r_entry
            else:
                l_entry = local_changes[cid]
                if isinstance(l_entry, dict) and isinstance(r_entry, dict):
                    for ek, ev in r_entry.items():
                        if ek.endswith("_runs") and isinstance(ev, list):
                            l_runs = l_entry.setdefault(ek, [])
                            seen = {(r.get("timestamp"), r.get("commit")) for r in l_runs if isinstance(r, dict)}
                            for r in ev:
                                if isinstance(r, dict) and (r.get("timestamp"), r.get("commit")) not in seen:
                                    l_runs.append(r)
                        elif ek not in l_entry:
                            l_entry[ek] = ev
                        elif ek == "last_updated":
                            l_entry["last_updated"] = max(str(l_entry.get("last_updated", "")), str(ev))
                        else:
                            if str(r_entry.get("last_updated", "")) > str(l_entry.get("last_updated", "")):
                                l_entry[ek] = ev

    l_lu = str(local_payload.get("last_updated", ""))
    r_lu = str(remote_payload.get("last_updated", ""))
    merged["last_updated"] = max(l_lu, r_lu) if (l_lu or r_lu) else None
    return merged


def reconcile_git_notes(
    repo_root: Path,
    remote: str = "origin",
    ref_name: str = "ship-evidence",
) -> int:
    """Reconcile remote tracking notes with local notes, performing a non-destructive merge."""
    short_name = ref_name.replace("refs/notes/", "")
    remote_ref, local_ref = f"refs/notes/{remote}/{short_name}", f"refs/notes/{short_name}"

    list_output = git_out(repo_root, "notes", f"--ref={remote_ref}", "list")
    if not list_output:
        return 0

    reconciled_count = 0
    for line in list_output.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        _blob_oid, commit_sha = parts

        r_note = git_out(repo_root, "notes", f"--ref={remote_ref}", "show", commit_sha)
        if not r_note:
            continue
        try:
            remote_json = json.loads(r_note)
        except Exception:
            remote_json = {"raw": r_note}

        l_note = git_out(repo_root, "notes", f"--ref={local_ref}", "show", commit_sha)
        if not l_note:
            git_cmd(repo_root, "notes", f"--ref={local_ref}", "add", "-f", "-m", r_note, commit_sha)
            reconciled_count += 1
        else:
            try:
                local_json = json.loads(l_note)
            except Exception:
                local_json = {"raw": l_note}
            if isinstance(local_json, dict) and isinstance(remote_json, dict):
                merged = merge_note_payloads(local_json, remote_json)
                git_cmd(repo_root, "notes", f"--ref={local_ref}", "add", "-f", "-m", json.dumps(merged, indent=2), commit_sha)
                reconciled_count += 1

    return reconciled_count


def configure_git_notes_sync(
    repo_root: Path,
    remote: str = "origin",
) -> Dict[str, Any]:
    """Configure git fetch refspecs into a separate tracking namespace and ensure branch push remains untouched."""
    if not get_git_info(repo_root).get("is_git"):
        return {"configured": False, "error": "Not a git repository"}

    # 1. REMOVE any push refspecs that override default branch push behavior
    for line in git_out(repo_root, "config", "--get-all", f"remote.{remote}.push").splitlines():
        if "refs/notes" in line:
            git_cmd(repo_root, "config", "--unset-all", f"remote.{remote}.push", line.strip())

    # 2. REMOVE destructive forced fetch refspecs like +refs/notes/*:refs/notes/*
    fetch_cfg = git_out(repo_root, "config", "--get-all", f"remote.{remote}.fetch")
    for line in fetch_cfg.splitlines():
        if line.strip() in {"+refs/notes/*:refs/notes/*", "refs/notes/*:refs/notes/*"}:
            git_cmd(repo_root, "config", "--unset-all", f"remote.{remote}.fetch", line.strip())

    # 3. Add non-destructive remote tracking fetch refspec: refs/notes/*:refs/notes/{remote}/*
    tracking_refspec = f"refs/notes/*:refs/notes/{remote}/*"
    fetch_lines = [l.strip() for l in fetch_cfg.splitlines() if l.strip() not in {"+refs/notes/*:refs/notes/*", "refs/notes/*:refs/notes/*"}]
    if tracking_refspec not in fetch_lines:
        git_cmd(repo_root, "config", "--add", f"remote.{remote}.fetch", tracking_refspec)

    return {"configured": True, "remote": remote, "fetch_refspec": tracking_refspec, "push_refspec": None}


def sync_git_notes(
    repo_root: Path,
    remote: str = "origin",
    ref_name: str = "ship-evidence",
) -> Dict[str, Any]:
    """Explicitly fetch into tracking namespace, reconcile divergence, and push notes without affecting branch push."""
    configure_git_notes_sync(repo_root, remote=remote)
    short_name = ref_name.replace("refs/notes/", "")
    results: Dict[str, Any] = {"remote": remote, "fetch": "skipped", "reconciled": 0, "push": "skipped"}

    fetch_res = git_cmd(repo_root, "fetch", remote, f"refs/notes/{short_name}:refs/notes/{remote}/{short_name}")
    results["fetch"] = "success" if fetch_res.returncode == 0 else f"skipped/empty: {fetch_res.stderr.strip()}"

    results["reconciled"] = reconcile_git_notes(repo_root, remote=remote, ref_name=short_name)

    push_res = git_cmd(repo_root, "push", remote, f"refs/notes/{short_name}:refs/notes/{short_name}")
    results["push"] = "success" if push_res.returncode == 0 else f"failed: {push_res.stderr.strip()}"

    return results


# ---------------------------------------------------------------------------
# Tier 3: Gate Commit Trailers (Ship-Change, Ship-<GateName>)
# ---------------------------------------------------------------------------

def generate_gate_trailers(
    repo_root: Path,
    change_id: Optional[str] = None,
    ledger: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Generate compact RFC 5133 Git commit trailers matching ship.json gates."""
    if ledger is None:
        ledger = load_ledger(repo_root, auto_sync=False)
    if config is None:
        config = load_ship_config(repo_root)

    cid = change_id or ledger.get("active_change_id") or get_active_change(repo_root) or "default"
    change_entry = ledger.get("changes", {}).get(cid, create_empty_change_entry(cid))
    evidence = change_entry.get("evidence", {})

    trailers: List[str] = []
    trailers.append(f"Ship-Change: {cid}")

    gates_cfg = config.get("gates", {})

    # 1. Gate: Design
    design_ev = evidence.get("design", {})
    if design_ev.get("adr"):
        adr_name = Path(design_ev["adr"]).stem
        status = design_ev.get("status", "ACCEPTED")
        trailers.append(f"Ship-Design: {adr_name} ({status})")
    elif "design" in gates_cfg:
        cur_phase = change_entry.get("phase", "design")
        if cur_phase in {"implementation", "audit", "delivery"}:
            trailers.append("Ship-Design: PASSED")
        elif cur_phase == "spike":
            trailers.append("Ship-Design: SPIKE")
        else:
            trailers.append("Ship-Design: IN_PROGRESS")

    # 2. Gate: Spike
    spike_ev = evidence.get("spike", {})
    if spike_ev.get("status") and spike_ev.get("status") != "NONE":
        verdict = spike_ev.get("verdict")
        v_str = f" ({verdict})" if verdict else ""
        trailers.append(f"Ship-Spike: {spike_ev['status']}{v_str}")

    # 3. Gate: Implementation
    impl_ev = evidence.get("implementation", {})
    tasks = change_entry.get("task_status", {})
    blockers = change_entry.get("blockers", [])
    has_test_failures = (
        impl_ev.get("tests_passed") is False
        or impl_ev.get("status") == "FAILED"
        or any(b.startswith("Tests:") for b in blockers)
    )

    if tasks.get("total", 0) > 0:
        if has_test_failures:
            trailers.append(f"Ship-Implementation: FAILED ({tasks['completed']}/{tasks['total']} tasks)")
        elif tasks.get("pending", 0) == 0:
            trailers.append(f"Ship-Implementation: PASSED ({tasks['completed']}/{tasks['total']} tasks)")
        else:
            trailers.append(f"Ship-Implementation: IN_PROGRESS ({tasks['completed']}/{tasks['total']} tasks)")
    elif has_test_failures:
        trailers.append("Ship-Implementation: FAILED")
    elif impl_ev.get("status") and impl_ev.get("status") != "PENDING":
        trailers.append(f"Ship-Implementation: {impl_ev['status']}")

    # 4. Gate: Simplify
    simp_ev = evidence.get("simplify", {})
    debt_cnt = simp_ev.get("debt_count", 0)
    trailers.append(f"Ship-Simplify: DEBT-{debt_cnt}")

    # 5. Gate: Audit
    audit_ev = evidence.get("audit", {})
    verdict = audit_ev.get("verdict")
    reviewer = audit_ev.get("reviewer") or "judge"
    if verdict:
        trailers.append(f"Ship-Audit: {verdict} (by {reviewer})")
    else:
        trailers.append("Ship-Audit: PENDING")

    # 6. Gate: Delivery
    deliv_ev = evidence.get("delivery", {})
    deliv_status = deliv_ev.get("status", "PENDING")
    if has_test_failures or blockers:
        if deliv_status == "ARCHIVED":
            trailers.append("Ship-Delivery: ARCHIVED")
        elif change_entry.get("phase") == "delivery" or deliv_status == "READY":
            trailers.append("Ship-Delivery: BLOCKED")
    elif change_entry.get("phase") == "delivery" or deliv_status in {"READY", "ARCHIVED"}:
        trailers.append(f"Ship-Delivery: {deliv_status if deliv_status != 'PENDING' else 'READY'}")

    return trailers


def record_audit_to_ledger(
    repo_root: Path,
    report_path_or_dict: Any,
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record Judge audit verdict to ledger and attach evidence note to commit."""
    if isinstance(report_path_or_dict, (str, Path)):
        p = Path(report_path_or_dict)
        if not p.is_absolute():
            p = repo_root / p
        report = parse_audit_report_file(p, repo_root)
    else:
        report = report_path_or_dict

    cid = change_id or report.get("change") or get_active_change(repo_root) or "default"

    def updater(entry: Dict[str, Any]) -> None:
        ev = entry["evidence"]["audit"]
        ev["verdict"] = report.get("verdict")
        ev["status"] = report.get("status")
        ev["reviewer"] = report.get("reviewer")
        ev["findings_count"] = report.get("findings_count", 0)
        ev["critical_or_high_count"] = report.get("critical_or_high_count", 0)
        ev["test_evidence_passed"] = report.get("test_evidence_passed")
        ev["report_path"] = report.get("path") or report.get("report_file")
        ev["snapshot_fingerprint"] = report.get("snapshot_fingerprint")

        git_info = get_git_info(repo_root)
        commit = git_info.get("commit")
        if commit:
            note_oid = attach_git_note_evidence(repo_root, commit, "audit_report", report, change_id=cid)
            ev["git_note_oid"] = note_oid

        blockers = [b for b in entry.get("blockers", []) if not b.startswith("Audit:")]
        crit = ev.get("critical_or_high_count", 0)
        if crit > 0:
            blockers.append(f"Audit: {crit} unresolved CRITICAL/HIGH finding(s)")
        if ev.get("verdict") in {"FAIL", "FAILED", "REJECTED"}:
            blockers.append(f"Audit: verdict is {ev.get('verdict')}")
        entry["blockers"] = blockers

        if ev.get("verdict") in {"PASS", "APPROVED"} and crit == 0 and not blockers:
            entry["phase"] = "delivery"
        else:
            entry["phase"] = "audit"

    return mutate_change_state(repo_root, cid, updater)


def record_test_run_to_ledger(
    repo_root: Path,
    test_summary: Dict[str, Any],
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Record test run evidence to ledger and attach to commit notes."""
    cid = change_id or get_active_change(repo_root) or "default"

    def updater(entry: Dict[str, Any]) -> None:
        impl = entry["evidence"]["implementation"]
        impl["status"] = "PASSED" if test_summary.get("passed", False) else "FAILED"
        impl["tests_passed"] = test_summary.get("passed", False)
        impl["failed_count"] = test_summary.get("failed_count", 0)
        impl["command"] = test_summary.get("command")

        git_info = get_git_info(repo_root)
        commit = git_info.get("commit")
        if commit:
            attach_git_note_evidence(repo_root, commit, "test_evidence", test_summary, change_id=cid)
            impl["evidence_ref"] = GIT_NOTES_REF

        blockers = [b for b in entry.get("blockers", []) if not b.startswith("Tests:")]
        if not test_summary.get("passed", False):
            blockers.append(f"Tests: {test_summary.get('failed_count', 1)} test(s) failing")
        entry["blockers"] = blockers

    return mutate_change_state(repo_root, cid, updater)


def validate_audit_approval(
    audit_report: Dict[str, Any],
    change_name: str,
    git_info: Dict[str, Any],
    package_spec_names: Optional[Set[str]] = None,
) -> Optional[str]:
    """Verify that an audit report strictly satisfies delivery/archive requirements. Returns error string or None."""
    # 1. Judge report contract check for envelopes
    if audit_report.get("is_envelope") and not audit_report.get("judge_report_valid"):
        err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
        return f"Judge report in delivery envelope is malformed: {err_msg}. Re-run review to produce a valid Judge report."

    # 2. Reviewer must be Judge
    if not audit_report.get("is_judge"):
        return f"Audit report is from '{audit_report.get('reviewer', 'unknown')}', not Judge. Requires explicit Judge adjudication before shipping."

    # 3. Must not contain unresolved CRITICAL or HIGH findings
    crit_count = audit_report.get("critical_or_high_count", 0)
    if crit_count > 0:
        return f"Audit has {crit_count} unresolved CRITICAL/HIGH finding(s). Must remediate defects before shipping."

    # 4. Must have explicit passing verdict and clean findings
    verdict = audit_report.get("verdict", "")
    status = audit_report.get("status", "")
    findings_count = audit_report.get("findings_count", 0)

    if verdict in {"FAIL", "FAILED", "REJECTED"}:
        return f"Audit verdict '{verdict}' is rejected. Remediate findings or re-run review."
    if status in {"fail", "failed", "rejected", "incomplete", "skipped"}:
        return f"Audit status '{status}' is not complete/passing (requires 'complete'). Remediate findings."
    if not (verdict in {"PASS", "APPROVED"} or (verdict == "" and status in {"complete", "pass", "approved"} and findings_count == 0)):
        return f"Audit verdict '{verdict or status}' is not PASS. Remediate findings or re-run review."

    # 5. Require explicit verified passing test evidence
    if not audit_report.get("test_evidence_passed"):
        return "Audit report lacks verified test evidence. Run test suite and record passing test results."

    # 6. Package / Change exact match check
    report_change = audit_report.get("change")
    if not report_change:
        return f"Audit approval lacks 'change'. Requires exact match with active package '{change_name}' before shipping."
    if report_change != change_name:
        return f"Audit approval is for change '{report_change}', but active package is '{change_name}'. Requires audit approval for '{change_name}' before shipping."

    # 7. Judge report contract check for non-envelopes
    if not audit_report.get("judge_report_valid"):
        err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
        env_text = " in delivery envelope" if audit_report.get("is_envelope") else ""
        return f"Judge report{env_text} is malformed: {err_msg}. Re-run review to produce a valid Judge report."

    # 7. Snapshot binding check
    snapshot_sha = audit_report.get("snapshot_sha")
    snapshot_fingerprint = audit_report.get("snapshot_fingerprint")
    current_commit = git_info.get("commit")
    current_fingerprint = git_info.get("working_tree_fingerprint")

    if git_info.get("is_git"):
        if current_commit:
            if not snapshot_sha and not snapshot_fingerprint:
                return "Audit report lacks commit snapshot SHA or tree fingerprint. Audit must be bound to reviewed snapshot."
            if snapshot_sha:
                if not bool(re.match(r"^[0-9a-f]{7,40}$", snapshot_sha, re.IGNORECASE)):
                    if not snapshot_fingerprint or (current_fingerprint and snapshot_fingerprint != current_fingerprint):
                        return f"Audit snapshot commit '{snapshot_sha}' is symbolic or unresolved. Must be a resolved, immutable commit SHA or accompanied by a matching working-tree fingerprint."
                elif not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                    return f"Audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'. Re-run audit on current code."
        else:
            if not snapshot_fingerprint:
                return "Audit report in repository before first commit lacks working-tree fingerprint. Audit must be bound to reviewed snapshot fingerprint."
            if snapshot_sha and snapshot_sha != "none":
                return f"Audit report snapshot commit '{snapshot_sha}' does not exist (repository has no commits yet). Re-run audit on current code."

    # 8. Working tree consistency check
    if snapshot_fingerprint:
        if not current_fingerprint or snapshot_fingerprint != current_fingerprint:
            return "Working tree has been modified since review (fingerprint mismatch). Re-run adversarial audit on current code before shipping."
    else:
        modified_sources = git_info.get("modified_source_files", [])
        if package_spec_names is not None:
            modified_sources = [
                f for f in modified_sources
                if not (f.startswith("openspec/specs/") and Path(f).name in package_spec_names)
            ]
        if modified_sources:
            mod_str = ", ".join(modified_sources[:3]) + (f" (+{len(modified_sources)-3} more)" if len(modified_sources) > 3 else "")
            return f"Working tree has unreviewed source modifications ({mod_str}). Re-run adversarial audit on current code before shipping."

    return None


def validate_delivery_readiness(
    audit_report: Dict[str, Any],
    active_pkg: Dict[str, Any],
    git_info: Dict[str, Any],
    active_change: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Validate that audit and ledger requirements are met before advancing to delivery."""
    def audit_blocked(reason: str) -> Tuple[str, str, str]:
        return ("audit", "AUDIT_ACTIVE", reason)

    pkg_change = active_pkg.get("change", "")
    err = validate_audit_approval(audit_report, pkg_change, git_info)
    if err:
        return audit_blocked(err)

    # 9. Ledger readiness validation
    if active_change:
        blockers = active_change.get("blockers", [])
        if blockers:
            test_b = [b for b in blockers if b.startswith("Tests:")]
            if test_b:
                return ("implementation", "TDD_ACTIVE", f"Blocked by test failure in ledger: {test_b[0]}. Run Red-Green-Refactor.")
            return audit_blocked(f"Blocked by active ledger blockers: {'; '.join(blockers)}. Remediate findings before shipping.")
        impl_ev = active_change.get("evidence", {}).get("implementation", {})
        if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED":
            return ("implementation", "TDD_ACTIVE", "Blocked by failing test evidence in ledger. Run Red-Green-Refactor.")
        audit_ev = active_change.get("evidence", {}).get("audit", {})
        if audit_ev.get("verdict") in {"FAIL", "FAILED", "REJECTED"}:
            return audit_blocked(f"Audit verdict recorded in ledger is '{audit_ev.get('verdict')}'. Remediate findings or re-run review.")
        if audit_ev.get("critical_or_high_count", 0) > 0:
            return audit_blocked(f"Ledger records {audit_ev['critical_or_high_count']} unresolved CRITICAL/HIGH finding(s). Remediate defects before shipping.")

    return (
        "delivery",
        "DELIVERY_READY",
        f"All tasks complete, tests verified green, and Judge audit PASSED. Ready to deliver Delivery Walkthrough. Run 'python3 skills/ship/scripts/inspect_lifecycle.py --archive' to sync living specs and archive '{pkg_change}'.",
    )


def determine_lifecycle_state(
    git_info: Dict[str, Any],
    adrs: List[Dict[str, Any]],
    openspec_packages: List[Dict[str, Any]],
    spikes: List[str],
    audit_report: Optional[Dict[str, Any]],
    active_change: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str]:
    """Determine the active gate, status label, and recommended next action."""
    # Check for active spikes
    if spikes:
        spike_name = spikes[0]
        return (
            "spike",
            "SPIKE_ACTIVE",
            f"Complete empirical spike in '{spike_name}'. Deliver verdict to settle design frontier.",
        )

    # Check if active change is archived
    if active_change and active_change.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
        cid = active_change.get("change_id", "active")
        arch_path = active_change.get("evidence", {}).get("delivery", {}).get("archived_path")
        path_str = f" in '{arch_path}'" if arch_path else ""
        return (
            "delivery",
            "ARCHIVED",
            f"Change '{cid}' has been delivered and archived{path_str}.",
        )

    # If no OpenSpec packages and no ADRs, we are at design gate
    if not openspec_packages and not adrs:
        return (
            "design",
            "INITIAL_PROPOSAL",
            "Run '/design' or '/ship <change>'. Explore workspace facts and present Frontier Rounds.",
        )

    # If OpenSpec package exists, check tasks
    if openspec_packages:
        active_pkg = openspec_packages[0]
        pkg_change_name = active_pkg.get("change")
        if not active_pkg["has_tasks"] or active_pkg["total_tasks"] == 0:
            return (
                "design",
                "SPEC_UNFINISHED",
                f"Compile tasks.md and specs/ for '{pkg_change_name}'. Seek user confirmation to proceed.",
            )

        if active_pkg["pending_tasks"] > 0:
            next_task_str = f" Next: '{active_pkg['next_task']}'." if active_pkg["next_task"] else ""
            return (
                "implementation",
                "TDD_ACTIVE",
                f"Implement pending tasks ({active_pkg['completed_tasks']}/{active_pkg['total_tasks']} tasks complete).{next_task_str} Run Red-Green-Refactor.",
            )

        # All tasks completed!
        if active_pkg["pending_tasks"] == 0 and active_pkg["total_tasks"] > 0:
            # Check authoritative ledger evidence & blockers before advancing beyond implementation gate
            if active_change:
                impl_ev = active_change.get("evidence", {}).get("implementation", {})
                blockers = active_change.get("blockers", [])
                test_blockers = [b for b in blockers if b.startswith("Tests:")]
                if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED" or test_blockers:
                    reason = test_blockers[0] if test_blockers else f"{impl_ev.get('failed_count', 1)} test(s) failing"
                    return (
                        "implementation",
                        "TDD_ACTIVE",
                        f"Blocked by failing tests recorded in ledger ({reason}). Run Red-Green-Refactor to fix failing tests before advancing.",
                    )

            if not audit_report:
                return (
                    "audit",
                    "AUDIT_ACTIVE",
                    "All implementation tasks marked complete. Run 'audit' in review-loop mode against base branch.",
                )

            return validate_delivery_readiness(audit_report, active_pkg, git_info, active_change)

    # Only ADRs exist
    has_accepted = any(a.get("status") in {"ACCEPTED", "APPROVED"} for a in adrs)
    if has_accepted:
        return (
            "design",
            "ADR_ACCEPTED",
            "ADR accepted. Compile OpenSpec change package (specs/ and tasks.md) or confirm with user to begin TDD.",
        )
    return (
        "design",
        "ADR_PROPOSED",
        "ADR proposed. Grill design frontier and seek user acceptance before compiling OpenSpec or beginning TDD.",
    )


def apply_and_archive_openspec(
    repo_root: Path,
    change: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Sync delta specs from changes to openspec/specs/, then move change package to openspec/archive/."""
    changes_dir = repo_root / "openspec" / "changes"
    if not changes_dir.exists():
        raise FileNotFoundError(f"No openspec/changes directory found at {changes_dir}")

    resolved_target = change
    # Resolve target package directory
    if resolved_target:
        change_dir = changes_dir / resolved_target
        if not change_dir.exists() or not change_dir.is_dir():
            raise FileNotFoundError(f"OpenSpec change directory '{resolved_target}' not found under {changes_dir}")
    else:
        packages = inspect_openspec(repo_root)
        if not packages:
            raise FileNotFoundError("No active change packages found in openspec/changes/ to archive.")
        change_dir = repo_root / packages[0]["path"]

    change_name = change_dir.name

    if not force:
        # 1. Implementation tasks check
        tasks_file = change_dir / "tasks.md"
        if not tasks_file.exists():
            raise RuntimeError(f"Cannot archive '{change_name}': tasks.md does not exist.")
        content = tasks_file.read_text(encoding="utf-8", errors="replace")
        has_pending = False
        has_tasks = False
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("- [ ]") or s.startswith("* [ ]"):
                has_pending = True
                has_tasks = True
            elif s.startswith(("- [x]", "- [X]", "* [x]", "* [X]")):
                has_tasks = True
        if not has_tasks:
            raise RuntimeError(f"Cannot archive '{change_name}': tasks.md contains no tasks.")
        if has_pending:
            raise RuntimeError(f"Cannot archive '{change_name}': package has pending tasks in tasks.md. Complete all tasks before archiving or use --force.")

        # 2. Authoritative ledger blockers & test evidence check
        ledger = load_ledger(repo_root, auto_sync=False)
        change_entry = ledger.get("changes", {}).get(change_name)
        if change_entry:
            blockers = change_entry.get("blockers", [])
            if blockers:
                raise RuntimeError(
                    f"Cannot archive '{change_name}': active ledger blockers ({'; '.join(blockers)}). Remediate blockers before archiving or use --force."
                )
            impl_ev = change_entry.get("evidence", {}).get("implementation", {})
            if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED":
                failed_cnt = impl_ev.get("failed_count", 1)
                raise RuntimeError(
                    f"Cannot archive '{change_name}': {failed_cnt} test(s) failing recorded in ledger. Fix tests before archiving or use --force."
                )

        # 3. Audit report / Delivery Evidence check
        audit_report = inspect_audit_reports(repo_root, change=change_name)
        if not audit_report:
            raise RuntimeError(f"Cannot archive '{change_name}': no passing audit report found (or delivery evidence in .scratch/).")

        source_specs_dir = change_dir / "specs"
        package_spec_names = {s.name for s in source_specs_dir.glob("*.md")} if source_specs_dir.exists() else set()
        git_info = get_git_info(repo_root)

        audit_err = validate_audit_approval(audit_report, change_name, git_info, package_spec_names=package_spec_names)
        if audit_err:
            msg = audit_err if audit_err.startswith("Judge report") else (audit_err[:1].lower() + audit_err[1:])
            raise RuntimeError(f"Cannot archive '{change_name}': {msg}")

    synced_specs = []
    living_specs_dir = repo_root / "openspec" / "specs"
    source_specs_dir = change_dir / "specs"

    # Step 1: Prepare all spec updates in-memory first
    # Map: dest_spec -> (original_content_or_None, merged_text)
    prepared_updates: Dict[Path, Tuple[Optional[str], str]] = {}
    if source_specs_dir.exists() and source_specs_dir.is_dir():
        for spec_file in sorted(source_specs_dir.glob("*.md")):
            dest_spec = living_specs_dir / spec_file.name
            delta_text = spec_file.read_text(encoding="utf-8", errors="replace")
            if dest_spec.exists():
                living_text = dest_spec.read_text(encoding="utf-8", errors="replace")
                merged_text = merge_spec_requirements(living_text, delta_text)
                prepared_updates[dest_spec] = (living_text, merged_text)
            else:
                prepared_updates[dest_spec] = (None, delta_text)

    # Step 2: Apply updates with rollback protection
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    archive_dir = repo_root / "openspec" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    dest_archive = archive_dir / f"{date_str}-{change_name}"
    if dest_archive.exists():
        dest_archive = archive_dir / f"{date_str}-{change_name}-{int(time.time())}"

    # Track applied mutations for rollback on any failure
    applied_mutations: Dict[Path, Optional[str]] = {}
    package_moved = False
    try:
        living_specs_dir.mkdir(parents=True, exist_ok=True)
        for dest_spec, (original_text, new_text) in prepared_updates.items():
            applied_mutations[dest_spec] = original_text
            dest_spec.write_text(new_text, encoding="utf-8")
            synced_specs.append(dest_spec.name)

        # Move package to archive
        shutil.move(str(change_dir), str(dest_archive))
        package_moved = True
        clear_active_change(repo_root, change_name)

        # Generate Gate Trailers and update ledger
        trailers = generate_gate_trailers(repo_root, change_id=change_name)
        try:
            def update_delivery(entry: Dict[str, Any]) -> None:
                entry["phase"] = "delivery"
                entry["evidence"]["delivery"]["status"] = "ARCHIVED"
                entry["evidence"]["delivery"]["archived_path"] = str(dest_archive.relative_to(repo_root))
                entry["evidence"]["delivery"]["trailers"] = trailers
            mutate_change_state(repo_root, change_name, update_delivery, set_active=False)
        except Exception:
            pass

    except Exception as err:
        # ROLLBACK all living spec mutations!
        for dest_spec, original_text in applied_mutations.items():
            try:
                if original_text is None:
                    dest_spec.unlink(missing_ok=True)
                else:
                    dest_spec.write_text(original_text, encoding="utf-8")
            except Exception:
                pass
        if package_moved and dest_archive.exists() and not change_dir.exists():
            try:
                shutil.move(str(dest_archive), str(change_dir))
            except Exception:
                pass
        raise RuntimeError(f"Archive failed during execution; rolled back living spec updates: {err}") from err

    return {
        "change": change_name,
        "synced_specs": synced_specs,
        "living_specs_dir": str(living_specs_dir.relative_to(repo_root)),
        "archived_path": str(dest_archive.relative_to(repo_root)),
        "trailers": trailers,
    }


def emit_telemetry_event(
    repo_root: Path,
    event_type: str,
    payload: Dict[str, Any],
    sink: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a structured telemetry event to a local file or configured telemetry sink."""
    target_sink = sink
    if not target_sink and config:
        target_sink = config.get("telemetry", {}).get("sink")
    if not target_sink:
        return

    event = {
        "event_type": event_type,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "repo": repo_root.name,
        "payload": payload,
    }
    try:
        sink_path = Path(target_sink)
        if not sink_path.is_absolute():
            sink_path = repo_root / sink_path
        sink_path.parent.mkdir(parents=True, exist_ok=True)
        with open(sink_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass


def canonicalize_gate_name(gate_name: str) -> str:
    """Canonicalize gate name to lowercase dashed identifier."""
    return gate_name.lower().strip().replace(" ", "-")


def _backup_path(src: Path, dest: Path) -> None:
    """Helper to backup a file or directory into destination directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.is_file():
            shutil.copy2(src, dest)
        elif src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
    except Exception:
        pass


def create_checkpoint(
    repo_root: Path,
    gate_name: str,
    change: Optional[str] = None,
    create_git_tag: bool = False,
    telemetry_sink: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a git checkpoint tag/ref and receipt for the given lifecycle gate."""
    resolved_change = change or get_active_change(repo_root) or "default"
    git_info = get_git_info(repo_root)
    cfg = load_ship_config(repo_root)
    allow_git_tag = create_git_tag or cfg.get("create_git_tag", False)

    canonical_tag = canonicalize_gate_name(gate_name)
    ref_name = f"refs/ship/{resolved_change}/{canonical_tag}"
    tag_name = f"ship/{resolved_change}/{canonical_tag}"
    commit_sha = git_info.get("commit")
    fingerprint = git_info.get("working_tree_fingerprint") or compute_working_tree_fingerprint(repo_root)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    ref_created = False
    snapshot_sha: Optional[str] = None
    if git_info.get("is_git") and commit_sha:
        try:
            with tempfile.TemporaryDirectory() as idx_dir:
                env = {**os.environ, "GIT_INDEX_FILE": str(Path(idx_dir) / "index")}
                git_cmd(repo_root, "read-tree", commit_sha, env=env, check=True)
                git_cmd(repo_root, "add", "-A", "--", ".", ":!.scratch", ":!scratch", ":!.gemini", ":!.ship", env=env, check=True)
                tree_sha = git_cmd(repo_root, "write-tree", env=env, check=True).stdout.strip()
                commit_msg = f"ship-checkpoint:{resolved_change}:{canonical_tag}"
                snapshot_sha = git_cmd(repo_root, "commit-tree", tree_sha, "-p", commit_sha, "-m", commit_msg, env=env, check=True).stdout.strip()
        except Exception:
            snapshot_sha = None

        target_ref_sha = snapshot_sha or commit_sha
        try:
            git_cmd(repo_root, "update-ref", ref_name, target_ref_sha, check=True)
            if allow_git_tag:
                git_cmd(repo_root, "tag", "-f", tag_name, target_ref_sha)
            ref_created = True
        except Exception:
            pass

    chk_dir = repo_root / ".scratch" / "checkpoints"
    chk_dir.mkdir(parents=True, exist_ok=True)
    receipt_file = chk_dir / f"{resolved_change}_{canonical_tag}.json"
    receipt_data = {
        "change": resolved_change,
        "gate": canonical_tag,
        "ref": ref_name,
        "tag": tag_name if allow_git_tag else None,
        "tag_created": allow_git_tag,
        "commit": commit_sha or "none",
        "snapshot_commit": snapshot_sha or commit_sha or "none",
        "fingerprint": fingerprint,
        "timestamp": timestamp,
        "is_git": git_info.get("is_git", False),
        "ref_created": ref_created,
    }
    receipt_file.write_text(json.dumps(receipt_data, indent=2), encoding="utf-8")

    try:
        def record_chk(entry: Dict[str, Any]) -> None:
            entry["checkpoints"][canonical_tag] = receipt_data
            entry["phase"] = canonical_tag
        mutate_change_state(repo_root, resolved_change, record_chk)
    except Exception:
        pass

    emit_telemetry_event(repo_root, "checkpoint_created", receipt_data, sink=telemetry_sink, config=cfg)

    return receipt_data


def perform_rollback(
    repo_root: Path,
    target_gate: str,
    change: Optional[str] = None,
    force: bool = False,
    telemetry_sink: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely roll back lifecycle and working state to target checkpoint (e.g. State 5b)."""
    resolved_change = change or get_active_change(repo_root) or "default"
    canonical_tag = canonicalize_gate_name(target_gate)

    git_info = get_git_info(repo_root)
    cfg = load_ship_config(repo_root)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = repo_root / ".scratch" / f"rollback_{timestamp_str}"

    chk_file = repo_root / ".scratch" / "checkpoints" / f"{resolved_change}_{canonical_tag}.json"

    target_tag = f"ship/{resolved_change}/{canonical_tag}"
    target_ref = f"refs/ship/{resolved_change}/{canonical_tag}"
    checkpoint_info: Optional[Dict[str, Any]] = read_json_file(chk_file)

    backed_up_files: List[str] = []
    restored_files: List[str] = []
    removed_files: List[str] = []
    git_reset_performed = False

    if git_info.get("is_git"):
        target_sha: Optional[str] = (
            git_out(repo_root, "rev-parse", "--verify", target_ref)
            or git_out(repo_root, "rev-parse", "--verify", target_tag)
            or (checkpoint_info.get("snapshot_commit") if checkpoint_info else None)
            or (checkpoint_info.get("commit") if checkpoint_info else None)
        )

        base_commit = (
            checkpoint_info.get("commit")
            if checkpoint_info and checkpoint_info.get("commit") and checkpoint_info.get("commit") != "none"
            else None
        )
        current_sha = git_info.get("commit")
        backup_dir.mkdir(parents=True, exist_ok=True)

        working_diff = git_cmd(repo_root, "diff", "--no-renames", "HEAD", text=False).stdout
        if working_diff:
            (backup_dir / "working_diff.patch").write_bytes(working_diff)

        if target_sha and current_sha and current_sha != target_sha and target_sha != "none":
            commit_diff = git_cmd(repo_root, "diff", "--no-renames", target_sha, "HEAD", text=False).stdout
            if commit_diff:
                (backup_dir / "committed_diff.patch").write_bytes(commit_diff)

        for src_path_str in git_info.get("modified_source_files", []):
            full_src = repo_root / src_path_str
            if full_src.is_file():
                _backup_path(full_src, backup_dir / src_path_str)
                if src_path_str not in backed_up_files:
                    backed_up_files.append(src_path_str)

        # Perform scoped restoration of implementation files modified or added since target_sha
        if target_sha and target_sha != "none":
            try:
                diff_files = git_out(repo_root, "diff", "--no-renames", "--name-only", target_sha).splitlines()
                untracked_files = git_out(repo_root, "ls-files", "--others", "--exclude-standard").splitlines()
                changed_files = [f.strip() for f in diff_files if f.strip()]
                for p in [f.strip() for f in untracked_files if f.strip()]:
                    if p not in changed_files:
                        changed_files.append(p)

                ignored_prefixes = (".scratch/", "scratch/", ".ship/", "ship/", ".gemini/", ".git/")
                tasks_rel = f"openspec/changes/{resolved_change}/tasks.md"

                for rel_path in changed_files:
                    if any(rel_path.startswith(p) for p in ignored_prefixes) or rel_path == tasks_rel:
                        continue

                    full_path = repo_root / rel_path
                    if (full_path.is_file() or full_path.is_dir()) and rel_path not in backed_up_files:
                        _backup_path(full_path, backup_dir / rel_path)
                        backed_up_files.append(rel_path)

                    # Check if file existed at target_sha
                    if git_cmd(repo_root, "cat-file", "-e", f"{target_sha}:{rel_path}").returncode == 0:
                        if git_cmd(repo_root, "checkout", target_sha, "--", rel_path).returncode == 0:
                            restored_files.append(rel_path)
                    else:
                        # File was newly created since target_sha: preserve in untracked_removed safety stash before removing
                        safety_stash = backup_dir / "untracked_removed" / rel_path
                        _backup_path(full_path, safety_stash)
                        if full_path.is_file():
                            git_cmd(repo_root, "rm", "-f", "--cached", rel_path)
                            full_path.unlink(missing_ok=True)
                            parent = full_path.parent
                            while parent != repo_root and parent.is_dir():
                                try:
                                    parent.rmdir()
                                    parent = parent.parent
                                except OSError:
                                    break
                        elif full_path.is_dir():
                            git_cmd(repo_root, "rm", "-rf", "--cached", rel_path)
                            shutil.rmtree(full_path, ignore_errors=True)
                        removed_files.append(rel_path)

                # Reset git history and index to base commit or target_sha
                reset_target = base_commit or target_sha
                if current_sha and reset_target and current_sha != reset_target and reset_target != "none":
                    if git_cmd(repo_root, "reset", reset_target).returncode == 0:
                        git_reset_performed = True
                elif restored_files or removed_files:
                    git_reset_performed = True
            except Exception:
                pass

    # Reset tasks in tasks.md for design spec amendment
    pkg_dir = repo_root / "openspec" / "changes" / resolved_change
    tasks_file = pkg_dir / "tasks.md"
    reset_tasks_count = 0
    if tasks_file.exists() and canonical_tag == "design":
        tasks_content = tasks_file.read_text(encoding="utf-8", errors="replace")
        new_lines = []
        for line in tasks_content.splitlines():
            if re.match(r"^(\s*(?:[-*]|\d+\.)\s*\[)[xX](\].*)$", line):
                new_line = re.sub(r"^(\s*(?:[-*]|\d+\.)\s*\[)[xX](\].*)$", r"\g<1> \2", line)
                new_lines.append(new_line)
                reset_tasks_count += 1
            else:
                new_lines.append(line)
        tasks_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    has_backups = bool(backed_up_files) or (backup_dir.exists() and (
        (backup_dir / "working_diff.patch").exists() or (backup_dir / "committed_diff.patch").exists()
    ))
    res_payload = {
        "status": "success",
        "change": resolved_change,
        "target_gate": canonical_tag,
        "backup_directory": str(backup_dir.relative_to(repo_root)) if has_backups else None,
        "has_backups": has_backups,
        "backed_up_files": backed_up_files,
        "restored_files": restored_files,
        "removed_files": removed_files,
        "reset_tasks_count": reset_tasks_count,
        "git_reset_performed": git_reset_performed,
        "checkpoint_found": bool(checkpoint_info),
        "message": f"Successfully rolled back to {canonical_tag}. Restored {len(restored_files)} files, removed {len(removed_files)} new files, backed up to {backup_dir.name}/.",
    }

    try:
        def update_rb(entry: Dict[str, Any]) -> None:
            entry["phase"] = canonical_tag
            entry["evidence"]["audit"] = make_default_audit_evidence()
            if canonical_tag == "design":
                entry["blockers"] = []
                entry["evidence"]["implementation"]["status"] = "PENDING"
                entry["evidence"]["implementation"]["tests_passed"] = None
            else:
                entry["blockers"] = [b for b in entry.get("blockers", []) if not b.startswith("Audit:")]
        mutate_change_state(repo_root, resolved_change, update_rb)
    except Exception:
        pass

    emit_telemetry_event(repo_root, "rollback_executed", res_payload, sink=telemetry_sink, config=cfg)
    return res_payload


def evaluate_repository(
    repo_root: Path,
    target_change: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a full lifecycle evaluation of the repository."""
    config = load_ship_config(repo_root, explicit_path=config_path)
    git_info = get_git_info(repo_root)
    adrs = inspect_adrs(repo_root)
    resolved_target = target_change
    openspec_packages = inspect_openspec(repo_root, target_change=resolved_target)
    archived_packages = inspect_archived_openspec(repo_root)
    living_specs = inspect_living_specs(repo_root)
    spikes = inspect_spikes(repo_root)
    active_pkg_change = openspec_packages[0]["change"] if openspec_packages else None
    audit_report = inspect_audit_reports(repo_root, change=resolved_target or active_pkg_change)

    resolved_change = resolved_target or get_active_change(repo_root) or active_pkg_change
    ledger = load_ledger(repo_root, auto_sync=True)
    active_change = ledger.get("changes", {}).get(resolved_change) if resolved_change else None

    gate, state_key, next_action = determine_lifecycle_state(
        git_info, adrs, openspec_packages, spikes, audit_report, active_change=active_change
    )

    return {
        "repo_root": str(repo_root),
        "target_change": resolved_change,
        "gate": gate,
        "state_key": state_key,
        "next_action": next_action,
        "git": git_info,
        "adrs": adrs,
        "openspec_packages": openspec_packages,
        "openspec_archived": archived_packages,
        "openspec_living_specs": living_specs,
        "active_spikes": spikes,
        "audit_report": audit_report,
        "config": config,
        "ledger": ledger,
        "active_change": active_change,
    }


def format_summary(data: Dict[str, Any]) -> str:
    """Format evaluation data for human/agent reading."""
    lines = []
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f" 🚀 LIFECYCLE STATE: {data['gate'].upper()}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f"• Internal State : {data['state_key']}")
    if data.get("active_change"):
        ac = data["active_change"]
        lines.append(f"• Change ID      : {ac.get('change_id')} (rev: r{ac.get('revision_counter', 0)}, phase: {ac.get('phase')})")
        if ac.get("blockers"):
            lines.append(f"  └─ Blockers    : {', '.join(ac['blockers'])}")
    elif data.get("target_change"):
        lines.append(f"• Active Change  : {data.get('target_change')}")

    git = data["git"]
    if git["is_git"]:
        status_str = "Clean" if git["is_clean"] else f"Dirty ({git['modified_count']} mod, {git['untracked_count']} untracked)"
        commit_str = f" [{git['commit'][:7]}]" if git.get("commit") else ""
        lines.append(f"• Git Branch     : {git['branch']}{commit_str} ({status_str})")
        if git.get("modified_source_files"):
            lines.append(f"  └─ Unreviewed  : {', '.join(git['modified_source_files'][:3])}")
    else:
        lines.append("• Git Branch     : Non-git workspace")

    adrs = data["adrs"]
    if adrs:
        adr_names = [f"{a['name']} ({a['status']})" for a in adrs]
        lines.append(f"• ADRs Found     : {', '.join(adr_names)}")
    else:
        lines.append("• ADRs Found     : None")

    pkgs = data["openspec_packages"]
    if pkgs:
        for p in pkgs:
            marker = " [ACTIVE]" if p.get("is_active_target") else ""
            pkg_name = p.get("change")
            lines.append(
                f"• OpenSpec '{pkg_name}'{marker} : {p['completed_tasks']}/{p['total_tasks']} tasks complete, "
                f"specs={'yes' if p['has_specs'] else 'no'}, proposal={'yes' if p['has_proposal'] else 'no'}"
            )
            if p["next_task"]:
                lines.append(f"  └─ Next Task   : {p['next_task']}")
    else:
        lines.append("• OpenSpec       : None")

    living_specs = data.get("openspec_living_specs", [])
    if living_specs:
        lines.append(f"• Living Specs   : {len(living_specs)} spec(s) in openspec/specs/")

    archived = data.get("openspec_archived", [])
    if archived:
        lines.append(f"• Archived Pkgs  : {len(archived)} package(s) in openspec/archive/")

    spikes = data["active_spikes"]
    if spikes:
        lines.append(f"• Active Spikes  : {', '.join(spikes)}")

    report = data["audit_report"]
    if report:
        env_str = " [Envelope]" if report.get("is_envelope") else ""
        verdict_str = f" verdict={report.get('verdict') or report.get('status')}"
        ev_str = f" tests={'passed' if report.get('test_evidence_passed') else 'failed/missing'}"
        crit_str = f" critical/high={report.get('critical_or_high_count')}"
        lines.append(f"• Audit Report   : {report['path']}{env_str} (by {report['reviewer']},{verdict_str},{ev_str},{crit_str})")

    if data.get("config", {}).get("config_source"):
        cfg = data["config"]
        t_cmd = cfg.get("gates", {}).get("implementation", {}).get("test") or "autodetect"
        lines.append(f"• Config File    : {cfg['config_source']} (test: '{t_cmd}')")

    lines.append("─────────────────────────────────────────────────────────────────────")
    lines.append("👉 RECOMMENDED NEXT ACTION:")
    lines.append(f"   {data['next_action']}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and evaluate repository against the engineering lifecycle."
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Path to repository root (default: current directory).",
    )
    parser.add_argument(
        "--change",
        dest="change",
        default=None,
        help="Target a specific change ID (e.g. feature-login).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to custom .ship.json configuration.",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        metavar="GATE",
        help="Record a git ref and receipt checkpoint for gate (e.g. design, implementation).",
    )
    parser.add_argument(
        "--rollback",
        default=None,
        metavar="GATE",
        help="Safely rollback working state to gate checkpoint (e.g. design for State 5b).",
    )
    parser.add_argument(
        "--status-check",
        action="store_true",
        help="Exit with 0 if ready for delivery, 1 if blocked, 2 if rollback/remediation recommended.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--archive",
        nargs="?",
        const="",
        default=None,
        metavar="CHANGE",
        help="Sync delta specs to openspec/specs/ and move completed change package to openspec/archive/.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force archive even if audit report or task completion checks fail.",
    )
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="Print deterministic working tree fingerprint SHA-256 and exit.",
    )
    parser.add_argument(
        "--create-git-tag",
        action="store_true",
        help="Also create a git tag in refs/tags/ (default: False, records in refs/ship/ only).",
    )
    parser.add_argument(
        "--telemetry-sink",
        default=None,
        help="Path to file for appending structured JSON lifecycle events.",
    )
    parser.add_argument(
        "--set-active-change",
        default=None,
        metavar="CHANGE_ID",
        help="Set the active change ID in .ship/state.json.",
    )
    parser.add_argument(
        "--sync-state",
        action="store_true",
        help="Force re-synchronize .ship/state.json from workspace artifacts.",
    )
    parser.add_argument(
        "--record-audit",
        default=None,
        metavar="REPORT_JSON",
        help="Record an audit report JSON into .ship/state.json and git notes.",
    )
    parser.add_argument(
        "--record-tests",
        default=None,
        metavar="TEST_DATA",
        help="Record test results into .ship/state.json and git notes (passed/failed or path to JSON).",
    )
    parser.add_argument(
        "--sync-notes",
        nargs="?",
        const="origin",
        default=None,
        metavar="REMOTE",
        help="Configure git fetch/push refspecs for notes and synchronize with remote.",
    )
    parser.add_argument(
        "--generate-trailers",
        action="store_true",
        help="Generate and print RFC 5133 commit trailers for the active or specified change.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

    def output_result(payload: Any, text_lines: Optional[Sequence[str]] = None) -> None:
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        elif text_lines is not None:
            for l in text_lines:
                print(l)

    def banner(title: str, lines: Sequence[str]) -> List[str]:
        bar = "═" * 69
        return [bar, f" {title}", bar, *lines, bar]

    if args.set_active_change:
        set_active_change(repo_root, args.set_active_change)
        output_result({"active_change_id": args.set_active_change}, [f"Active change set to: {args.set_active_change}"])
        return 0

    if args.sync_state:
        synced = sync_ledger_from_workspace(repo_root, target_change_id=args.change)
        output_result(synced, ["Successfully synchronized .ship/state.json from workspace artifacts."])
        return 0

    if args.generate_trailers:
        trailers = generate_gate_trailers(repo_root, change_id=args.change)
        output_result({"trailers": trailers}, trailers)
        return 0

    if args.sync_notes is not None:
        remote = args.sync_notes or "origin"
        res = sync_git_notes(repo_root, remote=remote)
        output_result(res, [f"Notes sync ({remote}): fetch={res['fetch']}, push={res['push']}"])
        return 0

    if args.record_audit:
        try:
            res = record_audit_to_ledger(repo_root, args.record_audit, change_id=args.change)
            verdict = res.get("evidence", {}).get("audit", {}).get("verdict")
            rev = res.get("revision_counter", 0)
            output_result(res, [f"Audit recorded for change '{res.get('change_id')}' (verdict: {verdict}, rev: r{rev})"])
            return 0
        except Exception as e:
            print(f"Error recording audit: {e}", file=sys.stderr)
            return 1

    if args.record_tests:
        try:
            test_file = Path(args.record_tests)
            if test_file.exists():
                try:
                    tdata = json.loads(test_file.read_text(encoding="utf-8"))
                except Exception:
                    tdata = {"passed": False, "raw": test_file.read_text(encoding="utf-8", errors="replace")}
            else:
                val = args.record_tests.lower().strip()
                tdata = {"passed": val in {"pass", "passed", "true", "1", "ok"}, "command": args.record_tests}
            res = record_test_run_to_ledger(repo_root, tdata, change_id=args.change)
            st = res.get("evidence", {}).get("implementation", {}).get("status")
            rev = res.get("revision_counter", 0)
            output_result(res, [f"Test run recorded for change '{res.get('change_id')}' (status: {st}, rev: r{rev})"])
            return 0
        except Exception as e:
            print(f"Error recording tests: {e}", file=sys.stderr)
            return 1

    if args.fingerprint:
        print(compute_working_tree_fingerprint(repo_root))
        return 0

    if args.checkpoint:
        try:
            res = create_checkpoint(
                repo_root,
                args.checkpoint,
                change=args.change,
                create_git_tag=args.create_git_tag,
                telemetry_sink=args.telemetry_sink,
            )
            tag_display = f" ({res['tag']})" if res.get("tag") else ""
            output_result(res, banner(f"🏷️  LIFECYCLE CHECKPOINT CREATED: {res['gate']}", [
                f"• Change         : {res.get('change')}",
                f"• Git Ref / Tag  : {res['ref']}{tag_display}",
                f"• Snapshot Commit: {res['commit'][:7] if res.get('commit') else 'none'}",
                f"• Fingerprint    : {res['fingerprint'][:12]}...",
            ]))
            return 0
        except Exception as e:
            print(f"Error creating checkpoint: {e}", file=sys.stderr)
            return 1

    if args.rollback:
        try:
            res = perform_rollback(
                repo_root,
                args.rollback,
                change=args.change,
                force=args.force,
                telemetry_sink=args.telemetry_sink,
            )
            rb_lines = [
                f"• Change         : {res.get('change')}",
                f"• Target Gate    : {res['target_gate']}",
            ]
            if res.get("backup_directory"):
                rb_lines.append(f"• State Backup   : {res['backup_directory']}/")
            if res.get("reset_tasks_count"):
                rb_lines.append(f"• Reset Tasks    : {res['reset_tasks_count']} tasks reverted in tasks.md")
            rb_lines.append(f"• Status         : {res['message']}")
            output_result(res, banner(f"🔄 LIFECYCLE ROLLBACK EXECUTED: {res['target_gate']}", rb_lines))
            return 0
        except Exception as e:
            print(f"Error during rollback: {e}", file=sys.stderr)
            return 1

    if args.archive is not None:
        try:
            change_id = args.archive if args.archive else args.change
            res = apply_and_archive_openspec(repo_root, change=change_id, force=args.force)
            specs_str = f"{', '.join(res['synced_specs'])} -> {res['living_specs_dir']}/" if res["synced_specs"] else "None"
            output_result(res, banner(f"📦 OPENSPEC APPLIED & ARCHIVED: {res.get('change')}", [
                f"• Synced Specs   : {specs_str}",
                f"• Archived To    : {res['archived_path']}",
                "• Lifecycle      : Reset to design (ready for next feature proposal)",
            ]))
            return 0
        except Exception as e:
            print(f"Error archiving OpenSpec package: {e}", file=sys.stderr)
            return 1

    try:
        data = evaluate_repository(repo_root, target_change=args.change, config_path=args.config)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.status_check:
        state_key = data.get("state_key")
        report = data.get("audit_report")
        if state_key == "DELIVERY_READY":
            return 0
        if report:
            verdict = report.get("verdict", "")
            status = report.get("status", "")
            if (
                report.get("critical_or_high_count", 0) > 0
                or verdict in {"FAIL", "FAILED", "REJECTED"}
                or status in {"fail", "failed", "rejected"}
            ):
                return 2
        return 1

    output_result(data, [format_summary(data)])

    return 0


if __name__ == "__main__":
    sys.exit(main())
