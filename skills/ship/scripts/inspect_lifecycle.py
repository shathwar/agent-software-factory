#!/usr/bin/env python3
"""Inspect repository state against the 4-gate engineering lifecycle.

Zero-dependency script (Python 3.10+ standard library).

Evaluates filesystem indicators to determine active gate:
- GATE 1: SPECIFICATION & DESIGN (adversarial-design / prototype)
- GATE 2: IMPLEMENTATION (tdd + ponytail)
- GATE 3: ADVERSARIAL AUDIT (adversarial-review loop)
- GATE 4: READY TO SHIP (delivery & PR sign-off)
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
        else:
            diff_cmd = ["git", "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--cached", "--"]
        diff_res = subprocess.run(
            diff_cmd,
            cwd=repo_root,
            capture_output=True,
        )
        if diff_res.returncode == 0:
            hasher.update(b"DIFF:\n")
            hasher.update(diff_res.stdout)
    except Exception:
        pass

    # 3. Untracked files (excluding scratch, archive, etc.)
    ignored_prefixes = (".scratch/", "scratch/", "openspec/archive/", ".gemini/", ".git/")
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
                if rel_str in {"report.json"}:
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

        # Identify unreviewed source modifications (filtering out scratch and archive)
        ignored_prefixes = (".scratch/", "scratch/", "openspec/archive/", ".gemini/", ".git/")
        modified_sources = []
        for l in lines:
            filename = l[3:].strip()
            if any(filename.startswith(p) for p in ignored_prefixes):
                continue
            if filename in {"report.json", ".gitignore"}:
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


def get_active_topic(repo_root: Path) -> Optional[str]:
    """Read explicitly persisted active topic from openspec/.active if present."""
    active_file = repo_root / "openspec" / ".active"
    if active_file.exists():
        try:
            val = active_file.read_text(encoding="utf-8").strip()
            if val:
                return val
        except Exception:
            pass
    return None


def set_active_topic(repo_root: Path, topic: str) -> None:
    """Persist active topic to openspec/.active."""
    active_file = repo_root / "openspec" / ".active"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(topic.strip() + "\n", encoding="utf-8")


def clear_active_topic(repo_root: Path, topic: Optional[str] = None) -> None:
    """Clear openspec/.active if it matches the topic (or unconditionally if topic is None)."""
    active_file = repo_root / "openspec" / ".active"
    if active_file.exists():
        try:
            if topic is None:
                active_file.unlink(missing_ok=True)
            else:
                current = active_file.read_text(encoding="utf-8").strip()
                if current == topic.strip():
                    active_file.unlink(missing_ok=True)
        except Exception:
            pass


def inspect_openspec(repo_root: Path, target_topic: Optional[str] = None) -> List[Dict[str, Any]]:
    """Scan openspec/changes/ for active change packages and parse tasks.md."""
    changes_dir = repo_root / "openspec" / "changes"
    packages = []
    if not changes_dir.exists():
        if target_topic:
            raise ValueError(f"Specified OpenSpec topic '{target_topic}' not found (openspec/changes does not exist).")
        return packages

    # Explicit topic validation: if target_topic specified, it MUST exist
    if target_topic:
        target_dir = changes_dir / target_topic
        if not target_dir.exists() or not target_dir.is_dir():
            available = [d.name for d in sorted(changes_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
            avail_str = f" Available: {', '.join(available)}" if available else " (no packages found)"
            raise ValueError(f"Specified OpenSpec topic '{target_topic}' not found under openspec/changes/.{avail_str}")

    active_persisted = target_topic or get_active_topic(repo_root)
    # If active_persisted was read from file, verify existence; clear if stale
    if active_persisted and not target_topic:
        if not (changes_dir / active_persisted).is_dir():
            clear_active_topic(repo_root)
            active_persisted = None

    for topic_dir in changes_dir.iterdir():
        if not topic_dir.is_dir() or topic_dir.name.startswith("."):
            continue

        tasks_file = topic_dir / "tasks.md"
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
                elif stripped.startswith("- [x]") or stripped.startswith("- [X]") or stripped.startswith("* [x]"):
                    total_tasks += 1
                    completed_tasks += 1

        proposal_file = topic_dir / "proposal.md"
        specs_dir = topic_dir / "specs"

        try:
            mtime = topic_dir.stat().st_mtime
        except Exception:
            mtime = 0.0

        packages.append({
            "topic": topic_dir.name,
            "path": str(topic_dir.relative_to(repo_root)),
            "has_proposal": proposal_file.exists(),
            "has_specs": specs_dir.exists() and any(specs_dir.iterdir()) if specs_dir.exists() else False,
            "has_tasks": tasks_found,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": total_tasks - completed_tasks,
            "next_task": next_task,
            "mtime": mtime,
            "is_active_target": (topic_dir.name == active_persisted),
        })

    # Sort packages so the true active package is at index 0:
    # 1. Exact match with active target
    # 2. In-progress packages (pending_tasks > 0)
    # 3. Most recently modified (mtime descending)
    # 4. Alphabetical fallback
    packages.sort(
        key=lambda p: (
            1 if p["is_active_target"] else 0,
            1 if p["pending_tasks"] > 0 else 0,
            p["mtime"],
            p["topic"],
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
    """Normalize requirement title for matching, removing only explicit removal markers."""
    cleaned = REMOVAL_TITLE_MARKER.sub("", raw_title).strip()
    return cleaned.lower()


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
        # Explicit rejection of negative phrases
        if re.search(r"\b(?:not\s+passed|failed|errors?:\s*[1-9]|failure|crash)\b", ev_lower):
            return False

        # Parse structured pattern: e.g. "0 failures, 12 passed" or "12 passed, 0 failures"
        m_fail = re.search(r"(\d+)\s*(?:failures?|errors?|failed)", ev_lower)
        m_pass = re.search(r"(\d+)\s*passed", ev_lower)
        if m_fail or m_pass:
            fail_count = int(m_fail.group(1)) if m_fail else 0
            pass_count = int(m_pass.group(1)) if m_pass else 0
            return fail_count == 0 and pass_count > 0

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


def inspect_spikes(repo_root: Path) -> List[str]:
    """Scan .scratch/ or scratch/ for active, uncompleted spikes."""
    spikes = []
    for base in [repo_root / ".scratch", repo_root / "scratch"]:
        if base.exists() and base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    if not is_spike_completed(child):
                        spikes.append(str(child.relative_to(repo_root)))
    return spikes


def inspect_audit_reports(repo_root: Path) -> Optional[Dict[str, Any]]:
    """Look for audit reports or delivery evidence envelopes in .scratch or workspace."""
    search_paths = [
        repo_root / ".scratch" / "delivery_evidence.json",
        repo_root / "scratch" / "delivery_evidence.json",
        repo_root / ".scratch" / "review_report.json",
        repo_root / "scratch" / "review_report.json",
        repo_root / "report.json",
    ]
    for p in search_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue

                # Support Delivery Evidence Envelope format
                is_envelope = "judge_report" in data or "snapshot" in data
                judge_data = data.get("judge_report", data) if is_envelope else data
                snapshot_info = data.get("snapshot") if is_envelope and isinstance(data.get("snapshot"), dict) else {}

                findings = judge_data.get("findings", [])
                critical_or_high = [
                    f for f in findings
                    if isinstance(f, dict) and f.get("severity") in {"CRITICAL", "HIGH"}
                ]
                reviewer = str(judge_data.get("reviewer", data.get("reviewer", "unknown"))).lower()
                status = str(judge_data.get("status", data.get("status", "unknown"))).lower()

                # Verdict and test evidence can be in envelope or top-level
                verdict = str(data.get("verdict", judge_data.get("verdict", ""))).strip().upper()
                raw_test_evidence = data.get("test_evidence") if "test_evidence" in data else data.get("tests_passed")
                if raw_test_evidence is None and "test_evidence" in judge_data:
                    raw_test_evidence = judge_data.get("test_evidence")
                test_evidence_passed = is_test_evidence_passing(raw_test_evidence)

                snapshot_sha = snapshot_info.get("commit") or data.get("commit") or data.get("snapshot") or data.get("head_sha")
                snapshot_tree = snapshot_info.get("tree_hash") or data.get("tree_hash")
                snapshot_fingerprint = snapshot_info.get("working_tree_fingerprint") or data.get("working_tree_fingerprint")

                topic = data.get("topic") or snapshot_info.get("topic") or judge_data.get("topic")

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
                    "topic": str(topic).strip() if topic else None,
                }
            except Exception:
                pass
    return None


def determine_lifecycle_state(
    git_info: Dict[str, Any],
    adrs: List[Dict[str, Any]],
    openspec_packages: List[Dict[str, Any]],
    spikes: List[str],
    audit_report: Optional[Dict[str, Any]],
) -> Tuple[str, str, str]:
    """Determine the active gate, status label, and recommended next action."""
    # Check for active spikes
    if spikes:
        spike_name = spikes[0]
        return (
            "GATE 1b: EMPIRICAL SPIKE ACTIVE",
            "SPIKE_ACTIVE",
            f"Complete empirical prototype in '{spike_name}'. Deliver verdict to settle design frontier.",
        )

    # If no OpenSpec packages and no ADRs, we are at Gate 1
    if not openspec_packages and not adrs:
        return (
            "GATE 1: SPECIFICATION & DESIGN",
            "INITIAL_PROPOSAL",
            "Run '/adversarial-design' or '/ship <topic>'. Explore workspace facts and present Frontier Rounds.",
        )

    # If OpenSpec package exists, check tasks
    if openspec_packages:
        active_pkg = openspec_packages[0]
        if not active_pkg["has_tasks"] or active_pkg["total_tasks"] == 0:
            return (
                "GATE 1: SPECIFICATION & DESIGN",
                "SPEC_UNFINISHED",
                f"Compile tasks.md and specs/ for '{active_pkg['topic']}'. Seek user confirmation to proceed.",
            )

        if active_pkg["pending_tasks"] > 0:
            next_task_str = f" Next: '{active_pkg['next_task']}'." if active_pkg["next_task"] else ""
            return (
                "GATE 2: IMPLEMENTATION (TDD + PONYTAIL)",
                "TDD_ACTIVE",
                f"Implement pending tasks ({active_pkg['completed_tasks']}/{active_pkg['total_tasks']} tasks complete).{next_task_str} Run Red-Green-Refactor.",
            )

        # All tasks completed!
        if active_pkg["pending_tasks"] == 0 and active_pkg["total_tasks"] > 0:
            if not audit_report:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "All implementation tasks marked complete. Run 'adversarial-review' in review-loop mode against base branch.",
                )

            # 1. Package / Topic exact match check
            report_topic = audit_report.get("topic")
            if audit_report.get("is_envelope") and not report_topic:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Delivery evidence envelope lacks 'topic'. Requires exact match with active package '{active_pkg['topic']}' before shipping.",
                )
            if report_topic and report_topic != active_pkg["topic"]:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit approval is for topic '{report_topic}', but active package is '{active_pkg['topic']}'. Requires audit approval for '{active_pkg['topic']}' before shipping.",
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
            if status in {"fail", "failed", "rejected", "incomplete"}:
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

            # 6. Snapshot binding check: commit match
            snapshot_sha = audit_report.get("snapshot_sha")
            snapshot_fingerprint = audit_report.get("snapshot_fingerprint")
            current_commit = git_info.get("commit")
            current_fingerprint = git_info.get("working_tree_fingerprint")

            if current_commit:
                if not snapshot_sha and not snapshot_fingerprint:
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        "Audit report lacks commit snapshot SHA or tree fingerprint. Audit must be bound to reviewed snapshot.",
                    )
                if snapshot_sha and snapshot_sha != "HEAD" and not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'. Re-run audit on current code.",
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

            # All checks pass
            return (
                "GATE 4: READY TO SHIP",
                "DELIVERY_READY",
                f"All tasks complete, tests verified green, and Judge audit PASSED. Ready to deliver Delivery Walkthrough. Run 'python3 skills/ship/scripts/inspect_lifecycle.py --archive' to sync living specs and archive '{active_pkg['topic']}'.",
            )

    # Only ADRs exist
    return (
        "GATE 1: SPECIFICATION & DESIGN",
        "ADR_ACCEPTED",
        "ADR exists. Compile OpenSpec change package (specs/ and tasks.md) or confirm with user to begin TDD.",
    )


def apply_and_archive_openspec(
    repo_root: Path,
    topic: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Sync delta specs from changes to openspec/specs/, then move change package to openspec/archive/."""
    changes_dir = repo_root / "openspec" / "changes"
    if not changes_dir.exists():
        raise FileNotFoundError(f"No openspec/changes directory found at {changes_dir}")

    # Resolve target package directory
    if topic:
        topic_dir = changes_dir / topic
        if not topic_dir.exists() or not topic_dir.is_dir():
            raise FileNotFoundError(f"OpenSpec change directory '{topic}' not found under {changes_dir}")
    else:
        packages = inspect_openspec(repo_root)
        if not packages:
            raise FileNotFoundError("No active change packages found in openspec/changes/ to archive.")
        topic_dir = repo_root / packages[0]["path"]

    topic_name = topic_dir.name

    if not force:
        # 1. Implementation tasks check
        tasks_file = topic_dir / "tasks.md"
        if not tasks_file.exists():
            raise RuntimeError(f"Cannot archive '{topic_name}': tasks.md does not exist.")
        content = tasks_file.read_text(encoding="utf-8", errors="replace")
        has_pending = False
        has_tasks = False
        for line in content.splitlines():
            s = line.strip()
            if s.startswith("- [ ]") or s.startswith("* [ ]"):
                has_pending = True
                has_tasks = True
            elif s.startswith("- [x]") or s.startswith("- [X]") or s.startswith("* [x]"):
                has_tasks = True
        if not has_tasks:
            raise RuntimeError(f"Cannot archive '{topic_name}': tasks.md contains no tasks.")
        if has_pending:
            raise RuntimeError(f"Cannot archive '{topic_name}': package has pending tasks in tasks.md. Complete all tasks before archiving or use --force.")

        # 2. Audit report / Delivery Evidence check
        audit_report = inspect_audit_reports(repo_root)
        if not audit_report:
            raise RuntimeError(f"Cannot archive '{topic_name}': no passing audit report found (or delivery evidence in .scratch/).")

        report_topic = audit_report.get("topic")
        if audit_report.get("is_envelope") and not report_topic:
            raise RuntimeError(
                f"Cannot archive '{topic_name}': delivery evidence envelope lacks 'topic' field to authorise package."
            )
        if report_topic and report_topic != topic_name:
            raise RuntimeError(
                f"Cannot archive '{topic_name}': audit approval is for topic '{report_topic}', not '{topic_name}'."
            )

        if not audit_report.get("is_judge"):
            raise RuntimeError(f"Cannot archive '{topic_name}': audit reviewer is '{audit_report.get('reviewer')}', requires Judge approval.")
        if audit_report.get("critical_or_high_count", 0) > 0:
            raise RuntimeError(f"Cannot archive '{topic_name}': audit has {audit_report.get('critical_or_high_count')} unresolved CRITICAL/HIGH findings.")
        verdict = audit_report.get("verdict", "")
        status = audit_report.get("status", "")
        if verdict in {"FAIL", "FAILED", "REJECTED"} or status in {"fail", "failed", "rejected", "incomplete"}:
            raise RuntimeError(f"Cannot archive '{topic_name}': audit verdict is '{verdict or status}', not PASS.")
        verdict_ok = verdict in {"PASS", "APPROVED"} or (verdict == "" and status in {"complete", "pass", "approved"} and audit_report.get("findings_count", 0) == 0)
        if not verdict_ok:
            raise RuntimeError(f"Cannot archive '{topic_name}': audit verdict is '{verdict or status}', not PASS.")
        if not audit_report.get("test_evidence_passed"):
            raise RuntimeError(f"Cannot archive '{topic_name}': audit report lacks verified passing test evidence.")

        git_info = get_git_info(repo_root)
        current_commit = git_info.get("commit")
        snapshot_sha = audit_report.get("snapshot_sha")
        snapshot_fingerprint = audit_report.get("snapshot_fingerprint")
        current_fingerprint = git_info.get("working_tree_fingerprint")

        if current_commit:
            if not snapshot_sha and not snapshot_fingerprint:
                raise RuntimeError(f"Cannot archive '{topic_name}': audit report lacks commit snapshot SHA or tree fingerprint.")
            if snapshot_sha and snapshot_sha != "HEAD" and not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                raise RuntimeError(f"Cannot archive '{topic_name}': audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'.")

        if snapshot_fingerprint:
            if not current_fingerprint or snapshot_fingerprint != current_fingerprint:
                raise RuntimeError(f"Cannot archive '{topic_name}': working tree has been modified since review (fingerprint mismatch).")
        else:
            modified_sources = git_info.get("modified_source_files", [])
            if modified_sources:
                raise RuntimeError(f"Cannot archive '{topic_name}': working tree has unreviewed source modifications ({', '.join(modified_sources[:3])}).")

    synced_specs = []

    # 1. Sync delta specs to living specs directory (openspec/specs/)
    source_specs = topic_dir / "specs"
    living_specs_dir = repo_root / "openspec" / "specs"
    if source_specs.exists() and source_specs.is_dir():
        living_specs_dir.mkdir(parents=True, exist_ok=True)
        for spec_file in sorted(source_specs.glob("*.md")):
            dest_spec = living_specs_dir / spec_file.name
            if dest_spec.exists():
                living_text = dest_spec.read_text(encoding="utf-8", errors="replace")
                delta_text = spec_file.read_text(encoding="utf-8", errors="replace")
                merged_text = merge_spec_requirements(living_text, delta_text)
                dest_spec.write_text(merged_text, encoding="utf-8")
            else:
                shutil.copy2(spec_file, dest_spec)
            synced_specs.append(spec_file.name)

    # 2. Archive completed change package to openspec/archive/<date>-<topic>
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    archive_dir = repo_root / "openspec" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    dest_archive = archive_dir / f"{date_str}-{topic_name}"
    if dest_archive.exists():
        dest_archive = archive_dir / f"{date_str}-{topic_name}-{int(time.time())}"

    shutil.move(str(topic_dir), str(dest_archive))
    clear_active_topic(repo_root, topic_name)

    return {
        "topic": topic_name,
        "synced_specs": synced_specs,
        "living_specs_dir": str(living_specs_dir.relative_to(repo_root)),
        "archived_path": str(dest_archive.relative_to(repo_root)),
    }


def evaluate_repository(
    repo_root: Path,
    target_topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform a full lifecycle evaluation of the repository."""
    git_info = get_git_info(repo_root)
    adrs = inspect_adrs(repo_root)
    openspec_packages = inspect_openspec(repo_root, target_topic=target_topic)
    archived_packages = inspect_archived_openspec(repo_root)
    living_specs = inspect_living_specs(repo_root)
    spikes = inspect_spikes(repo_root)
    audit_report = inspect_audit_reports(repo_root)

    gate, state_key, next_action = determine_lifecycle_state(
        git_info, adrs, openspec_packages, spikes, audit_report
    )

    return {
        "repo_root": str(repo_root),
        "target_topic": target_topic or get_active_topic(repo_root),
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
    }


def format_summary(data: Dict[str, Any]) -> str:
    """Format evaluation data for human/agent reading."""
    lines = []
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f" 🚀 LIFECYCLE STATE: {data['gate']}")
    lines.append("═════════════════════════════════════════════════════════════════════")
    lines.append(f"• Internal State : {data['state_key']}")
    if data.get("target_topic"):
        lines.append(f"• Active Topic   : {data['target_topic']}")

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
            lines.append(
                f"• OpenSpec '{p['topic']}'{marker} : {p['completed_tasks']}/{p['total_tasks']} tasks complete, "
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
        "--topic",
        default=None,
        help="Target a specific OpenSpec topic package.",
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
        metavar="TOPIC",
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

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

    if args.fingerprint:
        print(compute_working_tree_fingerprint(repo_root))
        return 0

    if args.archive is not None:
        try:
            topic = args.archive if args.archive else args.topic
            res = apply_and_archive_openspec(repo_root, topic, force=args.force)
            if args.format == "json":
                print(json.dumps(res, indent=2))
            else:
                print("═════════════════════════════════════════════════════════════════════")
                print(f" 📦 OPENSPEC APPLIED & ARCHIVED: {res['topic']}")
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
        data = evaluate_repository(repo_root, target_topic=args.topic)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
