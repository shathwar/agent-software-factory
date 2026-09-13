#!/usr/bin/env python3
"""Inspect repository state against the 4-gate engineering lifecycle.

Zero-dependency script (Python 3.10+ standard library).

Evaluates filesystem indicators to determine active gate:
- GATE 1: SPECIFICATION & DESIGN (design / spike)
- GATE 2: IMPLEMENTATION (tdd + simplify)
- GATE 3: ADVERSARIAL AUDIT (audit loop)
- GATE 4: READY TO SHIP (delivery & PR sign-off)
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


def compute_working_tree_fingerprint(repo_root: Path) -> str:
    """Compute a deterministic SHA-256 fingerprint of HEAD commit, working tree diff, and untracked files."""
    hasher = hashlib.sha256()

    # 1. Commit SHA of HEAD if git repo
    head_sha = "none"
    try:
        head_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if head_res.returncode == 0:
            head_sha = head_res.stdout.strip()
    except Exception:
        pass
    hasher.update(f"HEAD:{head_sha}\n".encode("utf-8"))

    # 2. Diff of tracked files (both staged and unstaged)
    try:
        if head_sha != "none":
            diff_cmd = ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", "--"]
            diff_res = subprocess.run(
                diff_cmd,
                cwd=repo_root,
                capture_output=True,
            )
            if diff_res.returncode == 0:
                hasher.update(b"DIFF:\n")
                hasher.update(diff_res.stdout)
        else:
            diff_staged = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--cached", "--"],
                cwd=repo_root,
                capture_output=True,
            )
            diff_unstaged = subprocess.run(
                ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--"],
                cwd=repo_root,
                capture_output=True,
            )
            if diff_staged.returncode == 0:
                hasher.update(b"DIFF_STAGED:\n")
                hasher.update(diff_staged.stdout)
            if diff_unstaged.returncode == 0:
                hasher.update(b"DIFF_UNSTAGED:\n")
                hasher.update(diff_unstaged.stdout)
    except Exception:
        pass

    # 3. Untracked files (excluding scratch, archive, etc.)
    ignored_prefixes = (".scratch/", "scratch/", ".ship/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
    try:
        untracked_res = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo_root,
            capture_output=True,
        )
        if untracked_res.returncode == 0:
            raw_entries = [p for p in untracked_res.stdout.split(b"\0") if p]
            for raw_path in sorted(raw_entries):
                try:
                    rel_str = raw_path.decode("utf-8", errors="replace")
                except Exception:
                    continue
                if any(rel_str.startswith(p) for p in ignored_prefixes):
                    continue
                if rel_str in {"report.json", "openspec/.active"}:
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


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """Zero-dependency parser for simple and nested YAML configurations."""
    result: Dict[str, Any] = {}
    stack: List[Tuple[int, Any, Optional[str]]] = [(-1, result, None)]

    def parse_scalar(val_str: str) -> Any:
        if " #" in val_str and not (
            (val_str.startswith('"') and val_str.endswith('"')) or
            (val_str.startswith("'") and val_str.endswith("'"))
        ):
            val_str = val_str.split(" #", 1)[0].rstrip()

        val_str = val_str.strip()
        if not val_str:
            return ""
        if val_str.startswith("[") and val_str.endswith("]"):
            return [parse_scalar(x.strip()) for x in val_str[1:-1].split(",") if x.strip()]
        if val_str.lower() in {"true", "yes", "on"}:
            return True
        if val_str.lower() in {"false", "no", "off"}:
            return False
        if re.match(r"^-?\d+$", val_str):
            return int(val_str)
        if re.match(r"^-?\d+\.\d+$", val_str):
            try:
                return float(val_str)
            except ValueError:
                pass
        if (val_str.startswith('"') and val_str.endswith('"')) or (val_str.startswith("'") and val_str.endswith("'")):
            return val_str[1:-1]
        return val_str

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip())
        trimmed = line.strip()

        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        _, current_container, active_key = stack[-1]

        if trimmed.startswith("- "):
            item_val_str = trimmed[2:].strip()
            item_val = parse_scalar(item_val_str)
            if isinstance(current_container, list):
                current_container.append(item_val)
            elif active_key is not None and len(stack) > 1:
                parent_container = stack[-2][1]
                if isinstance(parent_container, dict):
                    if not isinstance(parent_container.get(active_key), list):
                        parent_container[active_key] = []
                        stack[-1] = (stack[-1][0], parent_container[active_key], None)
                    parent_container[active_key].append(item_val)
            continue

        if ":" in trimmed:
            key, val = trimmed.split(":", 1)
            key = key.strip().strip("'\"")
            val = val.strip()

            if not val:
                new_dict: Dict[str, Any] = {}
                if isinstance(current_container, dict):
                    current_container[key] = new_dict
                    stack.append((indent, new_dict, key))
            else:
                parsed_val = parse_scalar(val)
                if isinstance(current_container, dict):
                    current_container[key] = parsed_val
    return result


def load_ship_config(repo_root: Path, explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """Load configuration from .ship.json or .ship.yaml/.ship.yml."""
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
        for candidate in [".ship.json", ".ship.yaml", ".ship.yml"]:
            p = repo_root / candidate
            if p.exists() and p.is_file():
                config_file = p
                break

    if not config_file:
        return default_config

    try:
        content = config_file.read_text(encoding="utf-8", errors="replace")
        loaded: Dict[str, Any] = {}
        if config_file.suffix == ".json":
            loaded = json.loads(content)
        else:
            loaded = parse_simple_yaml(content)

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
    try:
        git_check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if git_check.returncode == 0 and git_check.stdout.strip() == "true":
            info["is_git"] = True

        if not info["is_git"]:
            return info

        branch_res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if branch_res.returncode == 0 and branch_res.stdout.strip():
            info["branch"] = branch_res.stdout.strip()
        else:
            rev_abbrev = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if rev_abbrev.returncode == 0:
                info["branch"] = rev_abbrev.stdout.strip()

        commit_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if commit_res.returncode == 0:
            info["commit"] = commit_res.stdout.strip()

        tree_res = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if tree_res.returncode == 0:
            info["tree_hash"] = tree_res.stdout.strip()

        status_res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line for line in status_res.stdout.splitlines() if line.strip()]
        info["is_clean"] = len(lines) == 0
        info["modified_count"] = sum(1 for l in lines if not l.startswith("??"))
        info["untracked_count"] = sum(1 for l in lines if l.startswith("??"))

        # Identify unreviewed source modifications (filtering out scratch, archive, and internal state)
        ignored_prefixes = (".scratch/", "scratch/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
        modified_sources = []
        for l in lines:
            filename = l[3:].strip()
            if " -> " in filename:
                filename = filename.split(" -> ", 1)[1].strip()
            if filename.startswith('"') and filename.endswith('"'):
                filename = filename[1:-1]
            if any(filename.startswith(p) for p in ignored_prefixes):
                continue
            if filename in {"report.json", ".gitignore", "openspec/.active"}:
                continue
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
    """Read explicitly persisted active change ID from .ship/state.json or openspec/.active."""
    state_file = repo_root / ".ship" / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            cid = data.get("active_change_id")
            if cid:
                return cid
        except Exception:
            pass
    active_file = repo_root / "openspec" / ".active"
    if active_file.exists():
        try:
            val = active_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    return None

get_active_topic = get_active_change


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
    """Persist active change to openspec/.active and .ship/state.json."""
    active_file = repo_root / "openspec" / ".active"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(change.strip() + "\n", encoding="utf-8")
    state_file = repo_root / ".ship" / "state.json"
    if state_file.exists():
        with ledger_lock(repo_root):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                data["active_change_id"] = change.strip()
                state_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass


set_active_topic = set_active_change


def clear_active_change(repo_root: Path, change: Optional[str] = None) -> None:
    """Clear openspec/.active and .ship/state.json active_change_id."""
    active_file = repo_root / "openspec" / ".active"
    if active_file.exists():
        try:
            if change is None:
                active_file.unlink(missing_ok=True)
            else:
                current = active_file.read_text(encoding="utf-8").strip()
                if current == change.strip():
                    active_file.unlink(missing_ok=True)
        except Exception:
            pass
    state_file = repo_root / ".ship" / "state.json"
    if state_file.exists():
        with ledger_lock(repo_root):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if change is None or data.get("active_change_id") == (change.strip() if change else None):
                    data["active_change_id"] = None
                    state_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass


clear_active_topic = clear_active_change


def inspect_openspec(
    repo_root: Path,
    target_change: Optional[str] = None,
    target_topic: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Scan openspec/changes/ for active change packages and parse tasks.md."""
    resolved_target = target_change or target_topic
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
            "topic": change_dir.name,  # Alias for backward compatibility
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
                    topic_part = m.group(1)
                    known_packages.add(topic_part)
                    if "-" in topic_part:
                        known_packages.add(re.sub(r"-\d+$", "", topic_part))

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
            "topic", "verdict", "test_evidence", "tests_passed",
            "commit", "head_sha", "snapshot", "tree_hash", "working_tree_fingerprint"
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
    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
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
            "topic": None,
            "judge_report_valid": False,
            "judge_report_errors": [f"Could not read report file: {e}"],
        }

    try:
        data = json.loads(content)
        if not isinstance(data, dict):
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
                "topic": None,
                "judge_report_valid": False,
                "judge_report_errors": ["Report file is not a JSON object"],
            }
    except Exception as e:
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
            "topic": None,
            "judge_report_valid": False,
            "judge_report_errors": [f"Invalid JSON in report file: {e}"],
        }

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
    raw_test_evidence = data.get("test_evidence") if "test_evidence" in data else data.get("tests_passed")
    if raw_test_evidence is None:
        raw_test_evidence = judge_data.get("test_evidence")
    test_evidence_passed = is_test_evidence_passing(raw_test_evidence)

    raw_snapshot = data.get("snapshot")
    legacy_snapshot_str = raw_snapshot if isinstance(raw_snapshot, str) else None
    snapshot_sha = snapshot_info.get("commit") or data.get("commit") or legacy_snapshot_str or data.get("head_sha")
    snapshot_tree = snapshot_info.get("tree_hash") or data.get("tree_hash")
    snapshot_fingerprint = snapshot_info.get("working_tree_fingerprint") or data.get("working_tree_fingerprint")

    change = data.get("change") or data.get("topic") or snapshot_info.get("change") or snapshot_info.get("topic") or judge_data.get("change") or judge_data.get("topic")

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
        "topic": str(change).strip() if change else None,
        "judge_report_valid": judge_report_valid,
        "judge_report_errors": judge_report_errors,
    }


def inspect_audit_reports(
    repo_root: Path,
    change: Optional[str] = None,
    topic: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Look for audit reports or delivery evidence envelopes in .scratch or workspace."""
    target = change or topic
    if target:
        change_paths = [
            repo_root / ".scratch" / target / "delivery_evidence.json",
            repo_root / "scratch" / target / "delivery_evidence.json",
            repo_root / ".scratch" / f"delivery_evidence_{target}.json",
            repo_root / "scratch" / f"delivery_evidence_{target}.json",
            repo_root / ".scratch" / target / "review_report.json",
            repo_root / "scratch" / target / "review_report.json",
            repo_root / ".scratch" / f"review_report_{target}.json",
            repo_root / "scratch" / f"review_report_{target}.json",
            repo_root / ".scratch" / target / "audit_report.json",
            repo_root / "scratch" / target / "audit_report.json",
            repo_root / ".scratch" / f"audit_report_{target}.json",
            repo_root / "scratch" / f"audit_report_{target}.json",
        ]
        for p in change_paths:
            if p.exists():
                return parse_audit_report_file(p, repo_root)

    fallback_paths = [
        repo_root / ".scratch" / "delivery_evidence.json",
        repo_root / "scratch" / "delivery_evidence.json",
        repo_root / ".scratch" / "review_report.json",
        repo_root / "scratch" / "review_report.json",
        repo_root / ".scratch" / "audit_report.json",
        repo_root / "scratch" / "audit_report.json",
        repo_root / "report.json",
    ]
    for p in fallback_paths:
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


def create_empty_change_entry(change_id: str) -> Dict[str, Any]:
    """Create a default ChangeState entry according to the lifecycle schema."""
    return {
        "change_id": change_id,
        "phase": "gate-1-design",
        "task_status": {
            "total": 0,
            "completed": 0,
            "pending": 0,
            "in_progress": None,
            "next": None,
        },
        "blockers": [],
        "revision_counter": 0,
        "evidence": {
            "design": {"adr": None, "status": None},
            "spike": {"status": "NONE", "verdict": None, "dir": None},
            "implementation": {
                "status": "PENDING",
                "tests_passed": None,
                "failed_count": 0,
                "evidence_ref": None,
            },
            "simplify": {"status": "PENDING", "debt_count": 0},
            "audit": {
                "verdict": None,
                "status": None,
                "reviewer": None,
                "findings_count": 0,
                "critical_or_high_count": 0,
                "test_evidence_passed": None,
                "report_path": None,
                "git_note_oid": None,
                "snapshot_fingerprint": None,
            },
            "delivery": {
                "status": "PENDING",
                "archived_path": None,
                "commit": None,
                "trailers": [],
            },
        },
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
    existing: Dict[str, Any] = {}
    if ledger_path.exists():
        try:
            loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and "changes" in loaded:
                existing = loaded
        except Exception:
            existing = {}

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
            entry["phase"] = "gate-4-delivery"
            continue

        matched_pkg = next((p for p in packages if p["change"] == change or p.get("topic") == change), None)
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
                try:
                    cdata = json.loads(cf.read_text(encoding="utf-8"))
                    gate_k = cdata.get("gate", cf.stem.replace(f"{change}_", ""))
                    entry["checkpoints"][gate_k] = cdata
                except Exception:
                    pass

        existing_test_blockers = [b for b in entry.get("blockers", []) if b.startswith("Tests:")]
        if entry.get("evidence", {}).get("implementation", {}).get("tests_passed") is False:
            failed_cnt = entry["evidence"]["implementation"].get("failed_count", 1)
            t_blocker = f"Tests: {failed_cnt} test(s) failing"
            if t_blocker not in existing_test_blockers:
                existing_test_blockers.append(t_blocker)

        blockers: List[str] = list(existing_test_blockers)
        if spikes:
            entry["phase"] = "gate-1b-spike"
            blockers.append(f"Spike active in {spikes[0]}")
        elif not matched_pkg or matched_pkg["total_tasks"] == 0:
            entry["phase"] = "gate-1-design"
        elif matched_pkg["pending_tasks"] > 0 or any(b.startswith("Tests:") for b in blockers):
            entry["phase"] = "gate-2-impl"
        else:
            audit_ev = entry["evidence"]["audit"]
            crit = audit_ev.get("critical_or_high_count", 0)
            verd = audit_ev.get("verdict", "")
            if crit > 0:
                blockers.append(f"Audit has {crit} unresolved CRITICAL/HIGH finding(s)")
            if verd in {"FAIL", "FAILED", "REJECTED"}:
                blockers.append(f"Audit verdict is {verd}")

            if audit_ev.get("verdict") in {"PASS", "APPROVED"} and crit == 0 and not blockers:
                entry["phase"] = "gate-4-delivery"
            else:
                entry["phase"] = "gate-3-audit"

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
    if ledger_path.exists():
        try:
            data = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "changes" in data:
                return data
        except Exception:
            pass
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
    git_info = get_git_info(repo_root)
    if not git_info.get("is_git") or not commit_sha:
        return None

    verify_res = subprocess.run(
        ["git", "rev-parse", "--verify", commit_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if verify_res.returncode != 0:
        return None
    resolved_sha = verify_res.stdout.strip()

    existing_evidence: Dict[str, Any] = {}
    read_res = subprocess.run(
        ["git", "notes", f"--ref={ref}", "show", resolved_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if read_res.returncode == 0 and read_res.stdout.strip():
        try:
            loaded = json.loads(read_res.stdout)
            if isinstance(loaded, dict):
                existing_evidence = loaded
        except Exception:
            existing_evidence = {"raw_previous_note": read_res.stdout.strip()}

    cid = change_id or data.get("change") or data.get("topic") or get_active_change(repo_root) or "default"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    fingerprint = compute_working_tree_fingerprint(repo_root)

    changes = existing_evidence.setdefault("changes", {})
    change_entry = changes.setdefault(cid, {})

    runs_key = f"{evidence_type}_runs"
    runs = change_entry.setdefault(runs_key, [])
    run_record = {
        "timestamp": now_iso,
        "commit": resolved_sha,
        "fingerprint": fingerprint,
        "change_id": cid,
        "evidence_type": evidence_type,
        "data": data,
    }
    runs.append(run_record)

    change_entry[evidence_type] = data
    change_entry["last_updated"] = now_iso

    # Maintain top-level evidence_type for backwards compatibility
    existing_evidence[evidence_type] = data
    existing_evidence["last_change_id"] = cid
    existing_evidence["last_updated"] = now_iso

    note_payload = json.dumps(existing_evidence, indent=2)
    add_res = subprocess.run(
        ["git", "notes", f"--ref={ref}", "add", "-f", "-m", note_payload, resolved_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if add_res.returncode == 0:
        return resolved_sha
    return None


def read_git_note_evidence(
    repo_root: Path,
    commit_sha: str,
    ref: str = GIT_NOTES_REF,
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Read and parse structured JSON evidence from git notes on a commit."""
    git_info = get_git_info(repo_root)
    if not git_info.get("is_git") or not commit_sha:
        return {}

    res = subprocess.run(
        ["git", "notes", f"--ref={ref}", "show", commit_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                if change_id:
                    change_data = data.get("changes", {}).get(change_id)
                    if change_data is not None:
                        return change_data
                return data
        except Exception:
            return {"raw": res.stdout.strip()}
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
    remote_ref = f"refs/notes/{remote}/{short_name}"
    local_ref = f"refs/notes/{short_name}"

    list_res = subprocess.run(
        ["git", "notes", f"--ref={remote_ref}", "list"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if list_res.returncode != 0 or not list_res.stdout.strip():
        return 0

    reconciled_count = 0
    for line in list_res.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        _blob_oid, commit_sha = parts

        r_show = subprocess.run(
            ["git", "notes", f"--ref={remote_ref}", "show", commit_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if r_show.returncode != 0 or not r_show.stdout.strip():
            continue

        remote_json = {}
        try:
            remote_json = json.loads(r_show.stdout)
        except Exception:
            remote_json = {"raw": r_show.stdout.strip()}

        l_show = subprocess.run(
            ["git", "notes", f"--ref={local_ref}", "show", commit_sha],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )

        if l_show.returncode != 0 or not l_show.stdout.strip():
            note_content = r_show.stdout.strip()
            subprocess.run(
                ["git", "notes", f"--ref={local_ref}", "add", "-f", "-m", note_content, commit_sha],
                cwd=repo_root,
                capture_output=True,
            )
            reconciled_count += 1
        else:
            local_json = {}
            try:
                local_json = json.loads(l_show.stdout)
            except Exception:
                local_json = {"raw": l_show.stdout.strip()}

            if isinstance(local_json, dict) and isinstance(remote_json, dict):
                merged = merge_note_payloads(local_json, remote_json)
                merged_str = json.dumps(merged, indent=2)
                subprocess.run(
                    ["git", "notes", f"--ref={local_ref}", "add", "-f", "-m", merged_str, commit_sha],
                    cwd=repo_root,
                    capture_output=True,
                )
                reconciled_count += 1

    return reconciled_count


def configure_git_notes_sync(
    repo_root: Path,
    remote: str = "origin",
) -> Dict[str, Any]:
    """Configure git fetch refspecs into a separate tracking namespace and ensure branch push remains untouched."""
    git_info = get_git_info(repo_root)
    if not git_info.get("is_git"):
        return {"configured": False, "error": "Not a git repository"}

    # 1. REMOVE any push refspecs that override default branch push behavior
    push_cfg = subprocess.run(
        ["git", "config", "--get-all", f"remote.{remote}.push"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    for line in push_cfg.stdout.splitlines():
        if "refs/notes" in line:
            try:
                subprocess.run(
                    ["git", "config", "--unset-all", f"remote.{remote}.push", line.strip()],
                    cwd=repo_root,
                    capture_output=True,
                )
            except Exception:
                pass

    # 2. REMOVE destructive forced fetch refspecs like +refs/notes/*:refs/notes/*
    fetch_cfg = subprocess.run(
        ["git", "config", "--get-all", f"remote.{remote}.fetch"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    for line in fetch_cfg.stdout.splitlines():
        if line.strip() in {"+refs/notes/*:refs/notes/*", "refs/notes/*:refs/notes/*"}:
            try:
                subprocess.run(
                    ["git", "config", "--unset-all", f"remote.{remote}.fetch", line.strip()],
                    cwd=repo_root,
                    capture_output=True,
                )
            except Exception:
                pass

    # 3. Add non-destructive remote tracking fetch refspec: refs/notes/*:refs/notes/{remote}/*
    tracking_refspec = f"refs/notes/*:refs/notes/{remote}/*"
    fetch_lines = [l.strip() for l in fetch_cfg.stdout.splitlines() if l.strip() not in {"+refs/notes/*:refs/notes/*", "refs/notes/*:refs/notes/*"}]
    if tracking_refspec not in fetch_lines:
        try:
            subprocess.run(
                ["git", "config", "--add", f"remote.{remote}.fetch", tracking_refspec],
                cwd=repo_root,
                check=True,
                capture_output=True,
            )
        except Exception:
            pass

    return {
        "configured": True,
        "remote": remote,
        "fetch_refspec": tracking_refspec,
        "push_refspec": None,
    }


def sync_git_notes(
    repo_root: Path,
    remote: str = "origin",
    ref_name: str = "ship-evidence",
) -> Dict[str, Any]:
    """Explicitly fetch into tracking namespace, reconcile divergence, and push notes without affecting branch push."""
    configure_git_notes_sync(repo_root, remote=remote)
    short_name = ref_name.replace("refs/notes/", "")
    results: Dict[str, Any] = {"remote": remote, "fetch": "skipped", "reconciled": 0, "push": "skipped"}

    fetch_res = subprocess.run(
        ["git", "fetch", remote, f"refs/notes/{short_name}:refs/notes/{remote}/{short_name}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if fetch_res.returncode == 0:
        results["fetch"] = "success"
    else:
        results["fetch"] = f"skipped/empty: {fetch_res.stderr.strip()}"

    reconciled_cnt = reconcile_git_notes(repo_root, remote=remote, ref_name=short_name)
    results["reconciled"] = reconciled_cnt

    push_res = subprocess.run(
        ["git", "push", remote, f"refs/notes/{short_name}:refs/notes/{short_name}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if push_res.returncode == 0:
        results["push"] = "success"
    else:
        results["push"] = f"failed: {push_res.stderr.strip()}"

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
        trailers.append(f"Ship-Design: {change_entry.get('phase', 'gate-1-design')}")

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
        elif change_entry.get("phase") == "gate-4-delivery" or deliv_status == "READY":
            trailers.append("Ship-Delivery: BLOCKED")
    elif change_entry.get("phase") == "gate-4-delivery" or deliv_status in {"READY", "ARCHIVED"}:
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

    cid = change_id or report.get("change") or report.get("topic") or get_active_change(repo_root) or "default"

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
            entry["phase"] = "gate-4-delivery"

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
            "GATE 1b: EMPIRICAL SPIKE ACTIVE",
            "SPIKE_ACTIVE",
            f"Complete empirical spike in '{spike_name}'. Deliver verdict to settle design frontier.",
        )

    # Check if active change is archived
    if active_change and active_change.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
        cid = active_change.get("change_id", "active")
        arch_path = active_change.get("evidence", {}).get("delivery", {}).get("archived_path")
        path_str = f" in '{arch_path}'" if arch_path else ""
        return (
            "GATE 4: READY TO SHIP",
            "ARCHIVED",
            f"Change '{cid}' has been delivered and archived{path_str}.",
        )

    # If no OpenSpec packages and no ADRs, we are at Gate 1
    if not openspec_packages and not adrs:
        return (
            "GATE 1: SPECIFICATION & DESIGN",
            "INITIAL_PROPOSAL",
            "Run '/design' or '/ship <change>'. Explore workspace facts and present Frontier Rounds.",
        )

    # If OpenSpec package exists, check tasks
    if openspec_packages:
        active_pkg = openspec_packages[0]
        pkg_change_name = active_pkg.get("change") or active_pkg.get("topic")
        if not active_pkg["has_tasks"] or active_pkg["total_tasks"] == 0:
            return (
                "GATE 1: SPECIFICATION & DESIGN",
                "SPEC_UNFINISHED",
                f"Compile tasks.md and specs/ for '{pkg_change_name}'. Seek user confirmation to proceed.",
            )

        if active_pkg["pending_tasks"] > 0:
            next_task_str = f" Next: '{active_pkg['next_task']}'." if active_pkg["next_task"] else ""
            return (
                "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)",
                "TDD_ACTIVE",
                f"Implement pending tasks ({active_pkg['completed_tasks']}/{active_pkg['total_tasks']} tasks complete).{next_task_str} Run Red-Green-Refactor.",
            )

        # All tasks completed!
        if active_pkg["pending_tasks"] == 0 and active_pkg["total_tasks"] > 0:
            # Check authoritative ledger evidence & blockers before advancing beyond Gate 2
            if active_change:
                impl_ev = active_change.get("evidence", {}).get("implementation", {})
                blockers = active_change.get("blockers", [])
                test_blockers = [b for b in blockers if b.startswith("Tests:")]
                if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED" or test_blockers:
                    reason = test_blockers[0] if test_blockers else f"{impl_ev.get('failed_count', 1)} test(s) failing"
                    return (
                        "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)",
                        "TDD_ACTIVE",
                        f"Blocked by failing tests recorded in ledger ({reason}). Run Red-Green-Refactor to fix failing tests before advancing.",
                    )

            if not audit_report:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "All implementation tasks marked complete. Run 'audit' in review-loop mode against base branch.",
                )

            # 1. Judge report contract check for envelopes
            if audit_report.get("is_envelope") and not audit_report.get("judge_report_valid"):
                err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Judge report in delivery envelope is malformed: {err_msg}. Re-run review to produce a valid Judge report.",
                )

            # 2. Reviewer must be Judge (not an unadjudicated specialist)
            if not audit_report.get("is_judge"):
                reviewer_name = audit_report.get("reviewer", "unknown")
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit report is from '{reviewer_name}', not Judge. Requires explicit Judge adjudication before shipping.",
                )

            # 3. Must not contain unresolved CRITICAL or HIGH findings
            crit_count = audit_report.get("critical_or_high_count", 0)
            if crit_count > 0:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit has {crit_count} unresolved CRITICAL/HIGH finding(s). Must remediate defects before shipping.",
                )

            # 4. Must have explicit passing verdict and clean findings
            verdict = audit_report.get("verdict", "")
            status = audit_report.get("status", "")
            findings_count = audit_report.get("findings_count", 0)

            # Reject any explicit FAIL or non-pass verdict immediately
            if verdict in {"FAIL", "FAILED", "REJECTED"}:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit verdict '{verdict}' is rejected. Remediate findings or re-run review.",
                )
            if status in {"fail", "failed", "rejected", "incomplete", "skipped"}:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit status '{status}' is not complete/passing. Complete review and remediate findings.",
                )

            verdict_ok = verdict in {"PASS", "APPROVED"} or (verdict == "" and status in {"complete", "pass", "approved"} and findings_count == 0)
            if not verdict_ok:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit verdict '{verdict or status}' is not PASS. Remediate findings or re-run review.",
                )

            # 5. Require explicit verified passing test evidence
            if not audit_report.get("test_evidence_passed"):
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "Audit report lacks verified test evidence. Run test suite and record passing test results.",
                )

            # 6. Package / Change exact match check (enforced on all reports)
            report_change = audit_report.get("change") or audit_report.get("topic")
            pkg_change = active_pkg.get("change") or active_pkg.get("topic")
            if not report_change:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit approval lacks 'change'. Requires exact match with active package '{pkg_change}' before shipping.",
                )
            if report_change != pkg_change:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit approval is for change '{report_change}', but active package is '{pkg_change}'. Requires audit approval for '{pkg_change}' before shipping.",
                )

            # 7. Judge report contract check (enforced on all reports)
            if not audit_report.get("judge_report_valid"):
                err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
                env_text = " in delivery envelope" if audit_report.get("is_envelope") else ""
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Judge report{env_text} is malformed: {err_msg}. Re-run review to produce a valid Judge report.",
                )

            # 7. Snapshot binding check: commit match
            snapshot_sha = audit_report.get("snapshot_sha")
            snapshot_fingerprint = audit_report.get("snapshot_fingerprint")
            current_commit = git_info.get("commit")
            current_fingerprint = git_info.get("working_tree_fingerprint")

            if git_info.get("is_git"):
                if current_commit:
                    if not snapshot_sha and not snapshot_fingerprint:
                        return (
                            "GATE 3: ADVERSARIAL AUDIT",
                            "AUDIT_ACTIVE",
                            "Audit report lacks commit snapshot SHA or tree fingerprint. Audit must be bound to reviewed snapshot.",
                        )
                    if snapshot_sha:
                        is_hex_sha = bool(re.match(r"^[0-9a-f]{7,40}$", snapshot_sha, re.IGNORECASE))
                        if not is_hex_sha:
                            # Symbolic ref like 'HEAD' requires a matching working-tree fingerprint
                            if not snapshot_fingerprint or (current_fingerprint and snapshot_fingerprint != current_fingerprint):
                                return (
                                    "GATE 3: ADVERSARIAL AUDIT",
                                    "AUDIT_ACTIVE",
                                    f"Audit snapshot commit '{snapshot_sha}' is symbolic or unresolved. Must be a resolved, immutable commit SHA or accompanied by a matching working-tree fingerprint.",
                                )
                        elif not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                            return (
                                "GATE 3: ADVERSARIAL AUDIT",
                                "AUDIT_ACTIVE",
                                f"Audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'. Re-run audit on current code.",
                            )
                else:
                    # Git repository before first commit
                    if not snapshot_fingerprint:
                        return (
                            "GATE 3: ADVERSARIAL AUDIT",
                            "AUDIT_ACTIVE",
                            "Audit report in repository before first commit lacks working-tree fingerprint. Audit must be bound to reviewed snapshot fingerprint.",
                        )
                    if snapshot_sha and snapshot_sha != "none":
                        return (
                            "GATE 3: ADVERSARIAL AUDIT",
                            "AUDIT_ACTIVE",
                            f"Audit report snapshot commit '{snapshot_sha}' does not exist (repository has no commits yet). Re-run audit on current code.",
                        )

            # 7. Working tree consistency check
            if snapshot_fingerprint:
                if not current_fingerprint or snapshot_fingerprint != current_fingerprint:
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        "Working tree has been modified since review (fingerprint mismatch). Re-run adversarial audit on current code before shipping.",
                    )
            else:
                # If no fingerprint provided in envelope, require clean working tree
                modified_sources = git_info.get("modified_source_files", [])
                if modified_sources:
                    mod_str = ", ".join(modified_sources[:3])
                    if len(modified_sources) > 3:
                        mod_str += f" (+{len(modified_sources)-3} more)"
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Working tree has unreviewed source modifications ({mod_str}). Re-run adversarial audit on current code before shipping.",
                    )

            # Ledger readiness validation
            if active_change:
                blockers = active_change.get("blockers", [])
                if blockers:
                    test_b = [b for b in blockers if b.startswith("Tests:")]
                    if test_b:
                        return (
                            "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)",
                            "TDD_ACTIVE",
                            f"Blocked by test failure in ledger: {test_b[0]}. Run Red-Green-Refactor.",
                        )
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Blocked by active ledger blockers: {'; '.join(blockers)}. Remediate findings before shipping.",
                    )
                impl_ev = active_change.get("evidence", {}).get("implementation", {})
                if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED":
                    return (
                        "GATE 2: IMPLEMENTATION (TDD + SIMPLIFY)",
                        "TDD_ACTIVE",
                        "Blocked by failing test evidence in ledger. Run Red-Green-Refactor.",
                    )
                audit_ev = active_change.get("evidence", {}).get("audit", {})
                if audit_ev.get("verdict") in {"FAIL", "FAILED", "REJECTED"}:
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Audit verdict recorded in ledger is '{audit_ev.get('verdict')}'. Remediate findings or re-run review.",
                    )
                if audit_ev.get("critical_or_high_count", 0) > 0:
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Ledger records {audit_ev['critical_or_high_count']} unresolved CRITICAL/HIGH finding(s). Remediate defects before shipping.",
                    )

            # All checks pass
            return (
                "GATE 4: READY TO SHIP",
                "DELIVERY_READY",
                f"All tasks complete, tests verified green, and Judge audit PASSED. Ready to deliver Delivery Walkthrough. Run 'python3 skills/ship/scripts/inspect_lifecycle.py --archive' to sync living specs and archive '{pkg_change}'.",
            )

    # Only ADRs exist
    has_accepted = any(a.get("status") in {"ACCEPTED", "APPROVED"} for a in adrs)
    if has_accepted:
        return (
            "GATE 1: SPECIFICATION & DESIGN",
            "ADR_ACCEPTED",
            "ADR accepted. Compile OpenSpec change package (specs/ and tasks.md) or confirm with user to begin TDD.",
        )
    return (
        "GATE 1: SPECIFICATION & DESIGN",
        "ADR_PROPOSED",
        "ADR proposed. Grill design frontier and seek user acceptance before compiling OpenSpec or beginning TDD.",
    )


def apply_and_archive_openspec(
    repo_root: Path,
    change: Optional[str] = None,
    topic: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Sync delta specs from changes to openspec/specs/, then move change package to openspec/archive/."""
    changes_dir = repo_root / "openspec" / "changes"
    if not changes_dir.exists():
        raise FileNotFoundError(f"No openspec/changes directory found at {changes_dir}")

    resolved_target = change or topic
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

        if audit_report.get("is_envelope") and not audit_report.get("judge_report_valid"):
            err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
            raise RuntimeError(f"Cannot archive '{change_name}': Judge report in delivery envelope is malformed ({err_msg}).")

        if not audit_report.get("is_judge"):
            raise RuntimeError(f"Cannot archive '{change_name}': audit reviewer is '{audit_report.get('reviewer')}', requires Judge approval.")
        if audit_report.get("critical_or_high_count", 0) > 0:
            raise RuntimeError(f"Cannot archive '{change_name}': audit has {audit_report.get('critical_or_high_count')} unresolved CRITICAL/HIGH findings.")
        verdict = audit_report.get("verdict", "")
        status = audit_report.get("status", "")
        if verdict in {"FAIL", "FAILED", "REJECTED"} or status in {"fail", "failed", "rejected", "incomplete", "skipped"}:
            raise RuntimeError(f"Cannot archive '{change_name}': audit verdict is '{verdict or status}', not PASS (status is '{status}', requires 'complete').")
        verdict_ok = verdict in {"PASS", "APPROVED"} or (verdict == "" and status in {"complete", "pass", "approved"} and audit_report.get("findings_count", 0) == 0)
        if not verdict_ok:
            raise RuntimeError(f"Cannot archive '{change_name}': audit verdict is '{verdict or status}', not PASS.")
        if not audit_report.get("test_evidence_passed"):
            raise RuntimeError(f"Cannot archive '{change_name}': audit report lacks verified passing test evidence.")

        report_change = audit_report.get("change") or audit_report.get("topic")
        if not report_change:
            raise RuntimeError(
                f"Cannot archive '{change_name}': audit report lacks 'change' field to authorise package."
            )
        if report_change != change_name:
            raise RuntimeError(
                f"Cannot archive '{change_name}': audit approval is for change '{report_change}', not '{change_name}'."
            )

        if not audit_report.get("judge_report_valid"):
            err_msg = "; ".join(audit_report.get("judge_report_errors", ["Malformed Judge report structure"]))
            env_text = " in delivery envelope" if audit_report.get("is_envelope") else ""
            raise RuntimeError(f"Cannot archive '{change_name}': Judge report{env_text} is malformed ({err_msg}).")

        git_info = get_git_info(repo_root)
        current_commit = git_info.get("commit")
        snapshot_sha = audit_report.get("snapshot_sha")
        snapshot_fingerprint = audit_report.get("snapshot_fingerprint")
        current_fingerprint = git_info.get("working_tree_fingerprint")

        if git_info.get("is_git"):
            if current_commit:
                if not snapshot_sha and not snapshot_fingerprint:
                    raise RuntimeError(f"Cannot archive '{change_name}': audit report lacks commit snapshot SHA or tree fingerprint.")
                if snapshot_sha:
                    is_hex_sha = bool(re.match(r"^[0-9a-f]{7,40}$", snapshot_sha, re.IGNORECASE))
                    if not is_hex_sha:
                        if not snapshot_fingerprint or (current_fingerprint and snapshot_fingerprint != current_fingerprint):
                            raise RuntimeError(
                                f"Cannot archive '{change_name}': audit snapshot commit '{snapshot_sha}' is symbolic or unresolved. Must be an immutable commit SHA or accompanied by a matching fingerprint."
                            )
                    elif not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                        raise RuntimeError(f"Cannot archive '{change_name}': audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'.")
            else:
                if not snapshot_fingerprint:
                    raise RuntimeError(f"Cannot archive '{change_name}': audit report in repository before first commit lacks working-tree fingerprint.")
                if snapshot_sha and snapshot_sha != "none":
                    raise RuntimeError(f"Cannot archive '{change_name}': audit report snapshot commit '{snapshot_sha}' does not exist (repository has no commits yet).")

        source_specs_dir = change_dir / "specs"
        package_spec_names = {s.name for s in source_specs_dir.glob("*.md")} if source_specs_dir.exists() else set()

        if snapshot_fingerprint:
            if not current_fingerprint or snapshot_fingerprint != current_fingerprint:
                raise RuntimeError(f"Cannot archive '{change_name}': working tree has been modified since review (fingerprint mismatch).")
        else:
            modified_sources = git_info.get("modified_source_files", [])
            # Resumable recovery: ignore living specs belonging to this package if they were partially modified in an earlier interrupted attempt
            unreviewed = [
                f for f in modified_sources
                if not (f.startswith("openspec/specs/") and Path(f).name in package_spec_names)
                and f != "openspec/.active"
            ]
            if unreviewed:
                raise RuntimeError(f"Cannot archive '{change_name}': working tree has unreviewed source modifications ({', '.join(unreviewed[:3])}).")

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
                entry["phase"] = "gate-4-delivery"
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
        "topic": change_name,
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


def create_checkpoint(
    repo_root: Path,
    gate_name: str,
    change: Optional[str] = None,
    topic: Optional[str] = None,
    create_git_tag: bool = False,
    telemetry_sink: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a git checkpoint tag/ref and receipt for the given lifecycle gate."""
    resolved_change = change or topic or get_active_change(repo_root) or "default"
    git_info = get_git_info(repo_root)
    cfg = load_ship_config(repo_root)
    allow_git_tag = create_git_tag or cfg.get("create_git_tag", False)

    canonical = gate_name.lower().strip()
    if canonical in {"1", "gate1", "gate-1", "spec", "gate-1-spec"}:
        canonical_tag = "gate-1-spec"
    elif canonical in {"2", "gate2", "gate-2", "impl", "gate-2-impl", "tdd"}:
        canonical_tag = "gate-2-impl"
    elif canonical in {"3", "gate3", "gate-3", "audit", "gate-3-audit"}:
        canonical_tag = "gate-3-audit"
    elif canonical in {"4", "gate4", "gate-4", "delivery", "gate-4-delivery"}:
        canonical_tag = "gate-4-delivery"
    else:
        canonical_tag = canonical.replace(" ", "-")

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
                idx_file = Path(idx_dir) / "index"
                env = {**os.environ, "GIT_INDEX_FILE": str(idx_file)}
                subprocess.run(["git", "read-tree", commit_sha], cwd=repo_root, env=env, capture_output=True, check=True)
                add_cmd = ["git", "add", "-A", "--", ".", ":!.scratch", ":!scratch", ":!.gemini", ":!.ship"]
                subprocess.run(add_cmd, cwd=repo_root, env=env, capture_output=True, check=True)
                tree_res = subprocess.run(
                    ["git", "write-tree"],
                    cwd=repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                tree_sha = tree_res.stdout.strip()
                commit_msg = f"ship-checkpoint:{resolved_change}:{canonical_tag}"
                commit_res = subprocess.run(
                    ["git", "commit-tree", tree_sha, "-p", commit_sha, "-m", commit_msg],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                snapshot_sha = commit_res.stdout.strip()
        except Exception:
            snapshot_sha = None

        target_ref_sha = snapshot_sha or commit_sha
        try:
            subprocess.run(
                ["git", "update-ref", ref_name, target_ref_sha],
                cwd=repo_root,
                capture_output=True,
                check=True,
            )
            if allow_git_tag:
                subprocess.run(
                    ["git", "tag", "-f", tag_name, target_ref_sha],
                    cwd=repo_root,
                    capture_output=True,
                )
            ref_created = True
        except Exception:
            pass

    chk_dir = repo_root / ".scratch" / "checkpoints"
    chk_dir.mkdir(parents=True, exist_ok=True)
    receipt_file = chk_dir / f"{resolved_change}_{canonical_tag}.json"
    receipt_data = {
        "change": resolved_change,
        "topic": resolved_change,
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
    topic: Optional[str] = None,
    force: bool = False,
    telemetry_sink: Optional[str] = None,
) -> Dict[str, Any]:
    """Safely roll back lifecycle and working state to target checkpoint (e.g. State 5b)."""
    resolved_change = change or topic or get_active_change(repo_root) or "default"
    canonical = target_gate.lower().strip()
    if canonical in {"1", "gate1", "gate-1", "spec", "gate-1-spec"}:
        canonical_tag = "gate-1-spec"
    elif canonical in {"2", "gate2", "gate-2", "impl", "gate-2-impl", "tdd"}:
        canonical_tag = "gate-2-impl"
    else:
        canonical_tag = canonical.replace(" ", "-")

    git_info = get_git_info(repo_root)
    cfg = load_ship_config(repo_root)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = repo_root / ".scratch" / f"rollback_{timestamp_str}"

    chk_file = repo_root / ".scratch" / "checkpoints" / f"{resolved_change}_{canonical_tag}.json"
    target_tag = f"ship/{resolved_change}/{canonical_tag}"
    target_ref = f"refs/ship/{resolved_change}/{canonical_tag}"
    checkpoint_info: Optional[Dict[str, Any]] = None
    if chk_file.exists():
        try:
            checkpoint_info = json.loads(chk_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    backed_up_files: List[str] = []
    restored_files: List[str] = []
    removed_files: List[str] = []
    git_reset_performed = False

    if git_info.get("is_git"):
        target_sha: Optional[str] = None
        # Check internal private ref first to avoid requiring global tags
        ref_check = subprocess.run(
            ["git", "rev-parse", "--verify", target_ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if ref_check.returncode == 0:
            target_sha = ref_check.stdout.strip()
        else:
            tag_check = subprocess.run(
                ["git", "rev-parse", "--verify", target_tag],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if tag_check.returncode == 0:
                target_sha = tag_check.stdout.strip()
            elif checkpoint_info and checkpoint_info.get("snapshot_commit"):
                target_sha = checkpoint_info["snapshot_commit"]
            elif checkpoint_info and checkpoint_info.get("commit"):
                target_sha = checkpoint_info["commit"]

        base_commit = (
            checkpoint_info.get("commit")
            if checkpoint_info and checkpoint_info.get("commit") and checkpoint_info.get("commit") != "none"
            else None
        )

        current_sha = git_info.get("commit")
        backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            patch_res = subprocess.run(
                ["git", "diff", "--no-renames", "HEAD"],
                cwd=repo_root,
                capture_output=True,
            )
            if patch_res.stdout:
                (backup_dir / "working_diff.patch").write_bytes(patch_res.stdout)
        except Exception:
            pass

        if target_sha and current_sha and current_sha != target_sha and target_sha != "none":
            try:
                commit_diff_res = subprocess.run(
                    ["git", "diff", "--no-renames", target_sha, "HEAD"],
                    cwd=repo_root,
                    capture_output=True,
                )
                if commit_diff_res.stdout:
                    (backup_dir / "committed_diff.patch").write_bytes(commit_diff_res.stdout)
            except Exception:
                pass

        for src_path_str in git_info.get("modified_source_files", []):
            full_src = repo_root / src_path_str
            if full_src.is_file():
                dest = backup_dir / src_path_str
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(full_src, dest)
                    if src_path_str not in backed_up_files:
                        backed_up_files.append(src_path_str)
                except Exception:
                    pass

        # Perform scoped restoration of implementation files modified or added since target_sha
        if target_sha and target_sha != "none":
            try:
                diff_cmd = ["git", "diff", "--no-renames", "--name-only", target_sha]
                diff_proc = subprocess.run(diff_cmd, cwd=repo_root, capture_output=True, text=True)
                changed_files = [line.strip() for line in diff_proc.stdout.splitlines() if line.strip()]

                untracked_proc = subprocess.run(
                    ["git", "ls-files", "--others", "--exclude-standard"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                )
                for line in untracked_proc.stdout.splitlines():
                    p = line.strip()
                    if p and p not in changed_files:
                        changed_files.append(p)

                ignored_prefixes = (".scratch/", "scratch/", ".ship/", "ship/", ".gemini/", ".git/")
                tasks_rel = f"openspec/changes/{resolved_change}/tasks.md"

                for rel_path in changed_files:
                    if any(rel_path.startswith(p) for p in ignored_prefixes):
                        continue
                    if rel_path == tasks_rel:
                        continue

                    full_path = repo_root / rel_path
                    if full_path.is_file() and rel_path not in backed_up_files:
                        dest = backup_dir / rel_path
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(full_path, dest)
                            backed_up_files.append(rel_path)
                        except Exception:
                            pass
                    elif full_path.is_dir() and rel_path not in backed_up_files:
                        dest = backup_dir / rel_path
                        try:
                            shutil.copytree(full_path, dest, dirs_exist_ok=True)
                            backed_up_files.append(rel_path)
                        except Exception:
                            pass

                    # Check if file existed at target_sha
                    cat_check = subprocess.run(
                        ["git", "cat-file", "-e", f"{target_sha}:{rel_path}"],
                        cwd=repo_root,
                        capture_output=True,
                    )
                    if cat_check.returncode == 0:
                        # Restore file from target_sha
                        chk_proc = subprocess.run(
                            ["git", "checkout", target_sha, "--", rel_path],
                            cwd=repo_root,
                            capture_output=True,
                            text=True,
                        )
                        if chk_proc.returncode == 0:
                            restored_files.append(rel_path)
                    else:
                        # File was newly created since target_sha: preserve in untracked_removed safety stash before removing
                        safety_stash = backup_dir / "untracked_removed" / rel_path
                        safety_stash.parent.mkdir(parents=True, exist_ok=True)
                        if full_path.is_file():
                            try:
                                shutil.copy2(full_path, safety_stash)
                            except Exception:
                                pass
                            subprocess.run(["git", "rm", "-f", "--cached", rel_path], cwd=repo_root, capture_output=True)
                            full_path.unlink(missing_ok=True)
                            parent = full_path.parent
                            while parent != repo_root and parent.is_dir():
                                try:
                                    parent.rmdir()
                                    parent = parent.parent
                                except OSError:
                                    break
                        elif full_path.is_dir():
                            try:
                                shutil.copytree(full_path, safety_stash, dirs_exist_ok=True)
                            except Exception:
                                pass
                            subprocess.run(["git", "rm", "-rf", "--cached", rel_path], cwd=repo_root, capture_output=True)
                            shutil.rmtree(full_path, ignore_errors=True)
                        removed_files.append(rel_path)

                # Reset git history and index to base commit or target_sha
                reset_target = base_commit or target_sha
                if current_sha and reset_target and current_sha != reset_target and reset_target != "none":
                    reset_cmd = ["git", "reset", reset_target]
                    res = subprocess.run(reset_cmd, cwd=repo_root, capture_output=True, text=True)
                    if res.returncode == 0:
                        git_reset_performed = True
                elif restored_files or removed_files:
                    git_reset_performed = True
            except Exception:
                pass

    # Reset tasks in tasks.md for Gate 1 spec amendment
    pkg_dir = repo_root / "openspec" / "changes" / resolved_change
    tasks_file = pkg_dir / "tasks.md"
    reset_tasks_count = 0
    if tasks_file.exists() and canonical_tag == "gate-1-spec":
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
        "topic": resolved_change,
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
            entry["evidence"]["audit"] = {
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
            if canonical_tag == "gate-1-spec":
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
    target_topic: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a full lifecycle evaluation of the repository."""
    config = load_ship_config(repo_root, explicit_path=config_path)
    git_info = get_git_info(repo_root)
    adrs = inspect_adrs(repo_root)
    resolved_target = target_change or target_topic
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
        "target_topic": resolved_change,
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
    lines.append(f" 🚀 LIFECYCLE STATE: {data['gate']}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f"• Internal State : {data['state_key']}")
    if data.get("active_change"):
        ac = data["active_change"]
        lines.append(f"• Change ID      : {ac.get('change_id')} (rev: r{ac.get('revision_counter', 0)}, phase: {ac.get('phase')})")
        if ac.get("blockers"):
            lines.append(f"  └─ Blockers    : {', '.join(ac['blockers'])}")
    elif data.get("target_change"):
        lines.append(f"• Active Change  : {data['target_change']}")
    elif data.get("target_topic"):
        lines.append(f"• Active Change  : {data['target_topic']}")

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
            pkg_name = p.get("change") or p.get("topic")
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
        description="Inspect and evaluate repository against the 4-gate engineering lifecycle."
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
        "--topic",
        dest="change",
        default=None,
        help="Target a specific OpenSpec package (alias for --change).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to custom .ship.json or .ship.yaml configuration.",
    )
    parser.add_argument(
        "--checkpoint",
        default=None,
        metavar="GATE",
        help="Record a git ref and receipt checkpoint for GATE (e.g. gate-1-spec, gate-2-impl).",
    )
    parser.add_argument(
        "--rollback",
        default=None,
        metavar="GATE",
        help="Safely rollback working state to GATE checkpoint (e.g. gate-1-spec for State 5b).",
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

    if args.set_active_change:
        ledger = load_ledger(repo_root)
        ledger["active_change_id"] = args.set_active_change
        save_ledger(repo_root, ledger)
        set_active_topic(repo_root, args.set_active_change)
        if args.format == "json":
            print(json.dumps({"active_change_id": args.set_active_change}, indent=2))
        else:
            print(f"Active change set to: {args.set_active_change}")
        return 0

    if args.sync_state:
        synced = sync_ledger_from_workspace(repo_root, target_change_id=args.change)
        if args.format == "json":
            print(json.dumps(synced, indent=2))
        else:
            print("Successfully synchronized .ship/state.json from workspace artifacts.")
        return 0

    if args.generate_trailers:
        trailers = generate_gate_trailers(repo_root, change_id=args.change)
        if args.format == "json":
            print(json.dumps({"trailers": trailers}, indent=2))
        else:
            for t in trailers:
                print(t)
        return 0

    if args.sync_notes is not None:
        remote = args.sync_notes or "origin"
        res = sync_git_notes(repo_root, remote=remote)
        if args.format == "json":
            print(json.dumps(res, indent=2))
        else:
            print(f"Notes sync ({remote}): fetch={res['fetch']}, push={res['push']}")
        return 0

    if args.record_audit:
        try:
            res = record_audit_to_ledger(repo_root, args.record_audit, change_id=args.change)
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                verdict = res.get("evidence", {}).get("audit", {}).get("verdict")
                rev = res.get("revision_counter", 0)
                print(f"Audit recorded for change '{res.get('change_id')}' (verdict: {verdict}, rev: r{rev})")
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
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                st = res.get("evidence", {}).get("implementation", {}).get("status")
                rev = res.get("revision_counter", 0)
                print(f"Test run recorded for change '{res.get('change_id')}' (status: {st}, rev: r{rev})")
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
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                tag_display = f" ({res['tag']})" if res.get("tag") else ""
                print("═════════════════════════════════════════════════════════════════════")
                print(f" 🏷️  LIFECYCLE CHECKPOINT CREATED: {res['gate']}")
                print("═════════════════════════════════════════════════════════════════════")
                print(f"• Change         : {res.get('change') or res.get('topic')}")
                print(f"• Git Ref / Tag  : {res['ref']}{tag_display}")
                print(f"• Snapshot Commit: {res['commit'][:7] if res.get('commit') else 'none'}")
                print(f"• Fingerprint    : {res['fingerprint'][:12]}...")
                print("═════════════════════════════════════════════════════════════════════")
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
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                print("═════════════════════════════════════════════════════════════════════")
                print(f" 🔄 LIFECYCLE ROLLBACK EXECUTED: {res['target_gate']}")
                print("═════════════════════════════════════════════════════════════════════")
                print(f"• Change         : {res.get('change') or res.get('topic')}")
                print(f"• Target Gate    : {res['target_gate']}")
                if res.get("backup_directory"):
                    print(f"• State Backup   : {res['backup_directory']}/")
                if res.get("reset_tasks_count"):
                    print(f"• Reset Tasks    : {res['reset_tasks_count']} tasks reverted in tasks.md")
                print(f"• Status         : {res['message']}")
                print("═════════════════════════════════════════════════════════════════════")
            return 0
        except Exception as e:
            print(f"Error during rollback: {e}", file=sys.stderr)
            return 1

    if args.archive is not None:
        try:
            change_id = args.archive if args.archive else args.change
            res = apply_and_archive_openspec(repo_root, change=change_id, force=args.force)
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                print("═════════════════════════════════════════════════════════════════════")
                print(f" 📦 OPENSPEC APPLIED & ARCHIVED: {res.get('change') or res.get('topic')}")
                print("═════════════════════════════════════════════════════════════════════")
                if res["synced_specs"]:
                    print(f"• Synced Specs   : {', '.join(res['synced_specs'])} -> {res['living_specs_dir']}/")
                else:
                    print("• Synced Specs   : None")
                print(f"• Archived To    : {res['archived_path']}")
                print("• Lifecycle      : Reset to Gate 1 (ready for next feature proposal)")
                print("═════════════════════════════════════════════════════════════════════")
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

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
