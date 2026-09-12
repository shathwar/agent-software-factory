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
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple


def get_git_info(repo_root: Path) -> Dict[str, Any]:
    """Gather git branch and working tree status."""
    info: Dict[str, Any] = {
        "is_git": False,
        "branch": "unknown",
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


def inspect_openspec(repo_root: Path) -> List[Dict[str, Any]]:
    """Scan openspec/changes/ for active change packages and parse tasks.md."""
    changes_dir = repo_root / "openspec" / "changes"
    packages = []
    if not changes_dir.exists():
        return packages

    for topic_dir in sorted(changes_dir.iterdir()):
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
        })

    return packages


def inspect_spikes(repo_root: Path) -> List[str]:
    """Scan .scratch/ or scratch/ for active spikes."""
    spikes = []
    for base in [repo_root / ".scratch", repo_root / "scratch"]:
        if base.exists() and base.is_dir():
            for child in base.iterdir():
                if child.is_dir() and not child.name.startswith("."):
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
                return {
                    "path": str(p.relative_to(repo_root)),
                    "reviewer": data.get("reviewer", "unknown"),
                    "status": data.get("status", "unknown"),
                    "findings_count": len(data.get("findings", [])),
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
            # Check if audit is complete
            if audit_report and audit_report.get("status") in {"pass", "approved", "complete"}:
                return (
                    "GATE 4: READY TO SHIP",
                    "DELIVERY_READY",
                    "All tasks complete, tests green, and audit PASSED. Produce Delivery Walkthrough and prepare PR.",
                )
            else:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "All implementation tasks marked complete. Run 'adversarial-review' in review-loop mode against base branch.",
                )

    # Only ADRs exist
    return (
        "GATE 1: SPECIFICATION & DESIGN",
        "ADR_ACCEPTED",
        "ADR exists. Compile OpenSpec change package (specs/ and tasks.md) or confirm with user to begin TDD.",
    )


def evaluate_repository(repo_root: Path) -> Dict[str, Any]:
    """Perform a full lifecycle evaluation of the repository."""
    git_info = get_git_info(repo_root)
    adrs = inspect_adrs(repo_root)
    openspec_packages = inspect_openspec(repo_root)
    spikes = inspect_spikes(repo_root)
    audit_report = inspect_audit_reports(repo_root)

    gate, state_key, next_action = determine_lifecycle_state(
        git_info, adrs, openspec_packages, spikes, audit_report
    )

    return {
        "repo_root": str(repo_root),
        "gate": gate,
        "state_key": state_key,
        "next_action": next_action,
        "git": git_info,
        "adrs": adrs,
        "openspec_packages": openspec_packages,
        "active_spikes": spikes,
        "audit_report": audit_report,
    }


def format_summary(data: Dict[str, Any]) -> str:
    """Format evaluation data for human/agent reading."""
    lines = []
    lines.append(f"═════════════════════════════════════════════════════════════════════")
    lines.append(f" 🚀 LIFECYCLE STATE: {data['gate']}")
    lines.append(f"═════════════════════════════════════════════════════════════════════")
    lines.append(f"• Internal State : {data['state_key']}")
    lines.append(f"• Git Branch     : {data['git']['branch']} ({'Clean' if data['git']['is_clean'] else 'Dirty - ' + str(data['git']['modified_count']) + ' modified, ' + str(data['git']['untracked_count']) + ' untracked'})")

    if data["adrs"]:
        adr_str = ", ".join(f"{a['name']} [{a['status']}]" for a in data["adrs"])
        lines.append(f"• ADRs Found     : {adr_str}")
    else:
        lines.append(f"• ADRs Found     : None")

    if data["openspec_packages"]:
        for pkg in data["openspec_packages"]:
            progress = f"{pkg['completed_tasks']}/{pkg['total_tasks']} tasks complete"
            lines.append(f"• OpenSpec       : {pkg['topic']} ({progress})")
            if pkg["next_task"]:
                lines.append(f"  └─ Next Task   : {pkg['next_task']}")
    else:
        lines.append(f"• OpenSpec       : None")

    if data["active_spikes"]:
        lines.append(f"• Active Spikes  : {', '.join(data['active_spikes'])}")

    if data["audit_report"]:
        lines.append(f"• Audit Report   : {data['audit_report']['path']} ({data['audit_report']['status']})")

    lines.append(f"─────────────────────────────────────────────────────────────────────")
    lines.append(f"👉 RECOMMENDED NEXT ACTION:")
    lines.append(f"   {data['next_action']}")
    lines.append(f"═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect repository state against the 4-gate engineering lifecycle."
    )
    parser.add_argument(
        "--path",
        default=".",
        help="Repository root directory to inspect (default: current directory).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()
    data = evaluate_repository(repo_root)

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
