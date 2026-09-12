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
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple


def get_git_info(repo_root: Path) -> Dict[str, Any]:
    """Gather git branch, commit SHA, and working tree status."""
    info: Dict[str, Any] = {
        "is_git": False,
        "branch": "unknown",
        "commit": None,
        "is_clean": True,
        "modified_count": 0,
        "untracked_count": 0,
    }
    try:
        branch_res = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        info["branch"] = branch_res.stdout.strip()
        info["is_git"] = True

        commit_res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if commit_res.returncode == 0:
            info["commit"] = commit_res.stdout.strip()

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
        return packages

    active_persisted = target_topic or get_active_topic(repo_root)

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
    # 1. Exact match with active persisted target
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


def normalize_req_title(raw_title: str) -> str:
    """Normalize requirement title for matching."""
    cleaned = re.sub(r"\s*[\[\(](?:REMOVED|DELETED)[\]\)]", "", raw_title, flags=re.IGNORECASE).strip()
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
            is_removal = bool(re.search(r"[\[\(](?:REMOVED|DELETED)[\]\)]", raw_title, re.IGNORECASE))
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
            body_text = "".join(req["body_lines"][:3]).strip()
            if re.match(r"^(?:\[(?:REMOVED|DELETED)\]|STATUS:\s*(?:REMOVED|DELETED)|REMOVED|DELETED)\b", body_text, re.IGNORECASE):
                req["is_removal"] = True

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
        clean_header = re.sub(r"\s*[\[\(](?:REMOVED|DELETED)[\]\)]", "", req["header"], flags=re.IGNORECASE).rstrip()
        body = "".join(req["body_lines"]).strip()
        if body:
            result.append(f"{clean_header}\n{body}")
        else:
            result.append(clean_header)

    return "\n\n".join(result).strip() + "\n"


def is_test_evidence_passing(evidence: Any) -> bool:
    """Validate that test evidence explicitly confirms passing tests."""
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
        # 2. Passed flag must be True
        if "passed" in evidence:
            if not evidence["passed"]:
                return False
        # 3. Failure counts must be 0
        for fail_key in ("failed", "errors", "failures"):
            if fail_key in evidence and isinstance(evidence[fail_key], (int, float)):
                if evidence[fail_key] > 0:
                    return False
        # 4. Status string
        if "status" in evidence:
            st = str(evidence["status"]).lower().strip()
            if st not in {"pass", "passed", "ok", "success", "green"}:
                return False
        # Check that at least one positive assertion is present
        has_positive = (
            ("exit_code" in evidence and evidence["exit_code"] == 0)
            or ("passed" in evidence and evidence["passed"] is True)
            or ("status" in evidence and str(evidence["status"]).lower().strip() in {"pass", "passed", "ok", "success", "green"})
            or ("tests_run" in evidence and evidence.get("failed", 0) == 0 and evidence.get("errors", 0) == 0)
            or ("test_evidence" in evidence and is_test_evidence_passing(evidence["test_evidence"]))
        )
        return has_positive
    if isinstance(evidence, str):
        ev_lower = evidence.lower().strip()
        if not ev_lower or any(bad in ev_lower for bad in ["fail", "error", "exit_code: 1", "exit code 1"]):
            return False
        return any(good in ev_lower for good in ["pass", "ok", "success", "green", "0 failures", "exit_code: 0", "exit code 0"])
    if isinstance(evidence, (int, float)):
        return evidence == 0
    return False


def is_spike_completed(spike_dir: Path) -> bool:
    """Check if a spike directory contains completion evidence or verdict."""
    for marker in [".completed", ".done", "DONE", "done.txt"]:
        if (spike_dir / marker).exists():
            return True

    for report_file in [spike_dir / "report.json", spike_dir / "verdict.json"]:
        if report_file.exists():
            try:
                data = json.loads(report_file.read_text(encoding="utf-8"))
                if data.get("verdict") or data.get("status") in {"complete", "completed", "done", "passed"}:
                    return True
            except Exception:
                return True

    for md_file in spike_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            if re.search(
                r"(?:##\s*🧪\s*Spike Report|###\s*⚖️\s*Architectural Verdict|\bVerdict:\s*(?:CONFIRMED|REFUTED|QUALIFIED)|\bstatus:\s*complete\b)",
                content,
                re.IGNORECASE,
            ):
                return True
        except Exception:
            pass

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
    """Look for audit reports in .scratch or workspace."""
    search_paths = [
        repo_root / ".scratch" / "review_report.json",
        repo_root / "scratch" / "review_report.json",
        repo_root / "report.json",
    ]
    for p in search_paths:
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                findings = data.get("findings", [])
                critical_or_high = [
                    f for f in findings
                    if isinstance(f, dict) and f.get("severity") in {"CRITICAL", "HIGH"}
                ]
                reviewer = str(data.get("reviewer", "unknown")).lower()
                status = str(data.get("status", "unknown")).lower()
                verdict = str(data.get("verdict", "")).strip().upper()
                raw_test_evidence = data.get("test_evidence") if "test_evidence" in data else data.get("tests_passed")
                test_evidence_passed = is_test_evidence_passing(raw_test_evidence)
                snapshot_sha = data.get("commit") or data.get("snapshot") or data.get("head_sha")

                return {
                    "path": str(p.relative_to(repo_root)),
                    "reviewer": reviewer,
                    "status": status,
                    "verdict": verdict,
                    "findings_count": len(findings),
                    "critical_or_high_count": len(critical_or_high),
                    "is_judge": reviewer in {"judge", "review_judge"},
                    "raw_test_evidence": raw_test_evidence,
                    "test_evidence_passed": test_evidence_passed,
                    "snapshot_sha": str(snapshot_sha) if snapshot_sha else None,
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

            # 1. Reviewer must be Judge (not an unadjudicated specialist)
            if not audit_report.get("is_judge"):
                reviewer_name = audit_report.get("reviewer", "unknown")
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit report is from '{reviewer_name}', not Judge. Requires explicit Judge adjudication before shipping.",
                )

            # 2. Must not contain unresolved CRITICAL or HIGH findings
            crit_count = audit_report.get("critical_or_high_count", 0)
            if crit_count > 0:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit has {crit_count} unresolved CRITICAL/HIGH finding(s). Must remediate defects before shipping.",
                )

            # 3. Must have explicit passing verdict and clean findings
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

            # 4. Require explicit verified passing test evidence
            if not audit_report.get("test_evidence_passed"):
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "Audit report lacks verified test evidence. Run test suite and record passing test results.",
                )

            # 5. Snapshot binding check
            snapshot_sha = audit_report.get("snapshot_sha")
            current_commit = git_info.get("commit")
            if current_commit:
                if not snapshot_sha:
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        "Audit report lacks commit snapshot SHA. Audit must be bound to the reviewed commit.",
                    )
                if not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                    return (
                        "GATE 3: ADVERSARIAL AUDIT",
                        "AUDIT_ACTIVE",
                        f"Audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'. Re-run audit on current code.",
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

        # 2. Audit report check
        audit_report = inspect_audit_reports(repo_root)
        if not audit_report:
            raise RuntimeError(f"Cannot archive '{topic_name}': no passing audit report found in .scratch/review_report.json.")
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
        if current_commit:
            if not snapshot_sha:
                raise RuntimeError(f"Cannot archive '{topic_name}': audit report lacks commit snapshot SHA.")
            if not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                raise RuntimeError(f"Cannot archive '{topic_name}': audit snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'.")

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
        verdict_str = f" verdict={report.get('verdict') or report.get('status')}"
        ev_str = f" tests={'passed' if report.get('test_evidence_passed') else 'failed/missing'}"
        crit_str = f" critical/high={report.get('critical_or_high_count')}"
        lines.append(f"• Audit Report   : {report['path']} (by {report['reviewer']},{verdict_str},{ev_str},{crit_str})")

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

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

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

    data = evaluate_repository(repo_root, target_topic=args.topic)

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
