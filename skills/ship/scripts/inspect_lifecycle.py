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


def apply_and_archive_openspec(repo_root: Path, topic: Optional[str] = None) -> Dict[str, Any]:
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
        active_dirs = [d for d in sorted(changes_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
        if not active_dirs:
            raise FileNotFoundError("No active change packages found in openspec/changes/ to archive.")
        topic_dir = active_dirs[0]

    topic_name = topic_dir.name
    synced_specs = []

    # 1. Sync delta specs to living specs directory (openspec/specs/)
    source_specs = topic_dir / "specs"
    living_specs_dir = repo_root / "openspec" / "specs"
    if source_specs.exists() and source_specs.is_dir():
        living_specs_dir.mkdir(parents=True, exist_ok=True)
        for spec_file in sorted(source_specs.glob("*.md")):
            dest_spec = living_specs_dir / spec_file.name
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

    return {
        "topic": topic_name,
        "synced_specs": synced_specs,
        "living_specs_dir": str(living_specs_dir.relative_to(repo_root)),
        "archived_path": str(dest_archive.relative_to(repo_root)),
    }


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
                findings = data.get("findings", [])
                critical_or_high = [
                    f for f in findings
                    if isinstance(f, dict) and f.get("severity") in {"CRITICAL", "HIGH"}
                ]
                reviewer = str(data.get("reviewer", "unknown")).lower()
                status = str(data.get("status", "unknown")).lower()
                verdict = str(data.get("verdict", "")).strip().upper()
                test_evidence = data.get("test_evidence") or data.get("tests_passed")
                snapshot_sha = data.get("commit") or data.get("snapshot") or data.get("head_sha")

                return {
                    "path": str(p.relative_to(repo_root)),
                    "reviewer": reviewer,
                    "status": status,
                    "verdict": verdict,
                    "findings_count": len(findings),
                    "critical_or_high_count": len(critical_or_high),
                    "is_judge": reviewer in {"judge", "review_judge"},
                    "test_evidence": bool(test_evidence),
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

            # 3. Must have explicit passing verdict or clean findings
            verdict = audit_report.get("verdict", "")
            status = audit_report.get("status", "")
            findings_count = audit_report.get("findings_count", 0)
            verdict_ok = verdict in {"PASS", "APPROVED"} or (status in {"complete", "pass", "approved"} and findings_count == 0)
            if not verdict_ok:
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    f"Audit verdict '{verdict or status}' is not PASS. Remediate findings or re-run review.",
                )

            # 4. Require explicit test evidence
            if not audit_report.get("test_evidence"):
                return (
                    "GATE 3: ADVERSARIAL AUDIT",
                    "AUDIT_ACTIVE",
                    "Audit report lacks verified test evidence. Run test suite and record validation results.",
                )

            # 5. Snapshot binding check
            snapshot_sha = audit_report.get("snapshot_sha")
            current_commit = git_info.get("commit")
            if snapshot_sha and current_commit:
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


def evaluate_repository(repo_root: Path) -> Dict[str, Any]:
    """Perform a full lifecycle evaluation of the repository."""
    git_info = get_git_info(repo_root)
    adrs = inspect_adrs(repo_root)
    openspec_packages = inspect_openspec(repo_root)
    archived_packages = inspect_archived_openspec(repo_root)
    living_specs = inspect_living_specs(repo_root)
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
        "openspec_archived": archived_packages,
        "openspec_living_specs": living_specs,
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
            lines.append(f"• OpenSpec Active: {pkg['topic']} ({progress})")
            if pkg["next_task"]:
                lines.append(f"  └─ Next Task   : {pkg['next_task']}")
    else:
        lines.append(f"• OpenSpec Active: None")

    if data.get("openspec_living_specs"):
        spec_names = ", ".join(s["name"] for s in data["openspec_living_specs"])
        lines.append(f"• Living Specs   : {spec_names}")

    if data.get("openspec_archived"):
        arch_names = ", ".join(a["name"] for a in data["openspec_archived"])
        lines.append(f"• Archive        : {len(data['openspec_archived'])} package(s) ({arch_names})")

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
    parser.add_argument(
        "--archive",
        nargs="?",
        const="",
        default=None,
        metavar="TOPIC",
        help="Sync delta specs to openspec/specs/ and move completed change package to openspec/archive/.",
    )

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

    if args.archive is not None:
        try:
            topic = args.archive if args.archive else None
            res = apply_and_archive_openspec(repo_root, topic)
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

    data = evaluate_repository(repo_root)

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_summary(data))

    return 0


if __name__ == "__main__":
    sys.exit(main())
