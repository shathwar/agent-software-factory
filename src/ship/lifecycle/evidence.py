"""Evidence verification components for Spikes, TDD, and Review Judge reports."""

import json
import hashlib
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set

from .models import VerificationResult

NON_SPIKE_SCRATCH_DIRS = {
    "archive", "coverage", "logs", "cache", "tmp", "temp", "dist",
    "build", "node_modules", "venv", ".venv", "__pycache__", "checkpoints",
    "velocity", "sessions", "reports",
}


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
        if "exit_code" in evidence and (type(evidence["exit_code"]) is not int or evidence["exit_code"] != 0):
            return False
        # 2. Passed flag must be boolean True
        if "passed" in evidence and evidence["passed"] is not True:
            return False
        # 3. Tests run count must be positive integer (> 0)
        if "tests_run" in evidence:
            if type(evidence["tests_run"]) is not int or evidence["tests_run"] <= 0:
                return False
        # 4. Failure/error counts must be 0
        for fail_key in ("failed", "failed_count", "errors", "failures"):
            if fail_key in evidence:
                if type(evidence[fail_key]) is not int or evidence[fail_key] != 0:
                    return False
        # 5. Status string
        if "status" in evidence:
            st = str(evidence["status"]).lower().strip()
            if st not in {"pass", "passed", "ok", "success", "green"}:
                return False

        if "test_evidence" in evidence and not is_test_evidence_passing(evidence["test_evidence"]):
            return False

        # Affirmative passing criteria
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
        if ev_lower in {"pass", "passed", "ok", "success", "green"}:
            return True

        if re.search(r"\b(?:not\s+passed|failed|errors?:\s*[1-9]|failure|crash)\b", ev_lower):
            return False

        m_fail = re.search(r"(\d+)\s*(?:tests?\s+)?(?:failures?|errors?|failed)", ev_lower)
        m_pass = re.search(r"(\d+)\s*(?:tests?\s+)?passed", ev_lower)
        if m_fail or m_pass:
            fail_count = int(m_fail.group(1)) if m_fail else 0
            pass_count = int(m_pass.group(1)) if m_pass else 0
            return fail_count == 0 and pass_count > 0

        if re.search(r"\ball\s+(?:\d+\s+)?tests?\s+passed\b", ev_lower):
            return True

        if re.search(r"Ran\s+([1-9][0-9]*)\s+tests?.*?\bOK\b", ev_clean, re.DOTALL):
            return True

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
                return False

    for md_file in spike_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace").strip()
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


def is_evidence_dir(dir_path: Path) -> bool:
    """Distinguish review and delivery evidence directories from empirical spikes."""
    for evidence_name in ("delivery_evidence.json", "review_report.json"):
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


def parse_review_report_file(p: Path, repo_root: Path) -> Dict[str, Any]:
    """Parse and validate a review report file or delivery evidence envelope."""
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


def inspect_review_reports(
    repo_root: Path,
    change: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    target = change
    report_names = ("delivery_evidence.json", "review_report.json")
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
            return parse_review_report_file(p, repo_root)

    return None


def validate_review_approval(
    review_report: Dict[str, Any],
    change_name: str,
    git_info: Dict[str, Any],
    package_spec_names: Optional[Set[str]] = None,
) -> Optional[str]:
    """Verify that a review report strictly satisfies delivery/archive requirements. Returns error string or None."""
    if review_report.get("is_envelope") and not review_report.get("judge_report_valid"):
        err_msg = "; ".join(review_report.get("judge_report_errors", ["Malformed Judge report structure"]))
        return f"Judge report in delivery envelope is malformed: {err_msg}. Re-run review to produce a valid Judge report."

    if not review_report.get("is_judge"):
        return f"Review report is from '{review_report.get('reviewer', 'unknown')}', not Judge. Requires explicit Judge adjudication before shipping."

    crit_count = review_report.get("critical_or_high_count", 0)
    if crit_count > 0:
        return f"Review has {crit_count} unresolved CRITICAL/HIGH finding(s). Must remediate defects before shipping."

    verdict = review_report.get("verdict", "")
    status = review_report.get("status", "")
    findings_count = review_report.get("findings_count", 0)

    if verdict in {"FAIL", "FAILED", "REJECTED"}:
        return f"Review verdict '{verdict}' is rejected. Remediate findings or re-run review."
    if status in {"fail", "failed", "rejected", "incomplete", "skipped"}:
        return f"Review status '{status}' is not complete/passing (requires 'complete'). Remediate findings."
    if not (verdict in {"PASS", "APPROVED"} or (verdict == "" and status in {"complete", "pass", "approved"} and findings_count == 0)):
        return f"Review verdict '{verdict or status}' is not PASS. Remediate findings or re-run review."

    if not review_report.get("test_evidence_passed"):
        return "Review report lacks verified test evidence. Run test suite and record passing test results."

    report_change = review_report.get("change")
    if not report_change:
        return f"Review approval lacks 'change'. Requires exact match with active package '{change_name}' before shipping."
    if report_change != change_name:
        return f"Review approval is for change '{report_change}', but active package is '{change_name}'. Requires review approval for '{change_name}' before shipping."

    if not review_report.get("judge_report_valid"):
        err_msg = "; ".join(review_report.get("judge_report_errors", ["Malformed Judge report structure"]))
        env_text = " in delivery envelope" if review_report.get("is_envelope") else ""
        return f"Judge report{env_text} is malformed: {err_msg}. Re-run review to produce a valid Judge report."

    return validate_review_snapshot(review_report, git_info, package_spec_names)


def validate_review_snapshot(
    review_report: Dict[str, Any],
    git_info: Dict[str, Any],
    package_spec_names: Optional[Set[str]] = None,
) -> Optional[str]:
    """Validate the reviewed code snapshot, excluding workflow evidence artifacts."""
    snapshot_sha = review_report.get("snapshot_sha")
    snapshot_fingerprint = review_report.get("snapshot_fingerprint")
    current_commit = git_info.get("commit")
    current_fingerprint = git_info.get("working_tree_fingerprint")

    if git_info.get("is_git"):
        if current_commit:
            if not snapshot_sha and not snapshot_fingerprint:
                return "Review report lacks commit snapshot SHA or tree fingerprint. Review must be bound to reviewed snapshot."
            if snapshot_sha:
                if not bool(re.match(r"^[0-9a-f]{7,40}$", snapshot_sha, re.IGNORECASE)):
                    if not snapshot_fingerprint or (current_fingerprint and snapshot_fingerprint != current_fingerprint):
                        return f"Review snapshot commit '{snapshot_sha}' is symbolic or unresolved. Must be a resolved, immutable commit SHA or accompanied by a matching working-tree fingerprint."
                elif not current_commit.startswith(snapshot_sha) and not snapshot_sha.startswith(current_commit):
                    return f"Review snapshot '{snapshot_sha[:7]}' does not match current commit '{current_commit[:7]}'. Re-run review on current code."
        else:
            if not snapshot_fingerprint:
                return "Review report in repository before first commit lacks working-tree fingerprint. Review must be bound to reviewed snapshot fingerprint."
            if snapshot_sha and snapshot_sha != "none":
                return f"Review report snapshot commit '{snapshot_sha}' does not exist (repository has no commits yet). Re-run review on current code."

    if snapshot_fingerprint:
        if not current_fingerprint or snapshot_fingerprint != current_fingerprint:
            return "Working tree has been modified since review (fingerprint mismatch). Re-run adversarial review on current code before shipping."
    else:
        modified_sources = git_info.get("modified_source_files", [])
        if package_spec_names is not None:
            modified_sources = [
                f for f in modified_sources
                if not (f.startswith("openspec/specs/") and Path(f).name in package_spec_names)
            ]
        if modified_sources:
            mod_str = ", ".join(modified_sources[:3]) + (f" (+{len(modified_sources)-3} more)" if len(modified_sources) > 3 else "")
            return f"Working tree has unreviewed source modifications ({mod_str}). Re-run adversarial review on current code before shipping."

    return None


def design_fingerprint(repo_root: Path, change: str) -> str:
    """Bind approval to package contents and ADRs; task completion is not design."""
    from .paths import repository_path, resolve_change_path
    package = resolve_change_path(repo_root, change)
    if not package.is_dir():
        raise ValueError(f"Missing design package: {change}")
    records = []
    for directory in (package, repository_path(repo_root, "docs/adr")):
        for candidate in sorted(directory.rglob("*")):
            path = repository_path(repo_root, candidate.relative_to(repo_root).as_posix())
            if not path.is_file():
                continue
            data = path.read_bytes()
            if path == package / "tasks.md":
                data = re.sub(rb"(?m)^(\s*[-*] )\[[xX ]\]", rb"\1[ ]", data)
            records.append((path.relative_to(repo_root).as_posix(), hashlib.sha256(data).hexdigest()))
    if not records:
        raise ValueError("Design package is empty")
    return hashlib.sha256(json.dumps(records, separators=(",", ":")).encode()).hexdigest()


def validate_design_approval(repo_root: Path, change: str, entry: Optional[Dict[str, Any]]) -> Optional[str]:
    receipt = (entry or {}).get("evidence", {}).get("design", {}).get("approval")
    if not isinstance(receipt, dict) or receipt.get("change") != change or not isinstance(receipt.get("approved_by"), str) or not receipt["approved_by"].strip():
        return "Design approval required for this change."
    try:
        if receipt.get("fingerprint") != design_fingerprint(repo_root, change):
            return "Design changed since approval; obtain approval again."
    except (ValueError, OSError) as exc:
        return f"Design cannot be verified: {exc}"
    return None


def implementation_failed(evidence: Dict[str, Any]) -> bool:
    """Check recorded results, including legacy ledgers, using the ingestion rule."""
    if evidence.get("status") == "FAILED":
        return True
    if evidence.get("tests_passed") is None and evidence.get("status", "PENDING") == "PENDING":
        return False
    return not is_test_evidence_passing({
        "passed": evidence.get("tests_passed"),
        "failed_count": evidence.get("failed_count", 0),
    })
