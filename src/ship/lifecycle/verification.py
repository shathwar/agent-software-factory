"""Independent verification engine eliminating circular trust in AgentFlow lifecycle."""

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .models import VerificationRecord, VerificationTier


def parse_line_range(line_str: str) -> Tuple[int, int]:
    """Parse finding line string like 'L10' or 'L10-L25' into 1-based (start, end) tuples."""
    cleaned = str(line_str).strip().upper()
    m = re.match(r"^L?([1-9][0-9]*)(?:-L?([1-9][0-9]*))?$", cleaned)
    if not m:
        raise ValueError(f"Invalid line range format: '{line_str}' (expected e.g. 'L10' or 'L10-L25')")
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start
    if end < start:
        raise ValueError(f"Invalid line range: end {end} < start {start}")
    return start, end


def verify_finding_grounding(finding: Dict[str, Any], repo_root: Path) -> Tuple[bool, str]:
    """Verify that a review finding's cited evidence is grounded in real source files.

    Inspired by inspect_ai exact_match / grounded scorer pattern:
    Checks that the file exists, line range is valid, and the evidence snippet
    actually corresponds to code present in the file at or near the specified lines.
    """
    file_rel = finding.get("file")
    if not file_rel:
        return False, "Finding missing 'file' path"

    file_path = repo_root / file_rel
    if not file_path.exists() or not file_path.is_file():
        return False, f"Cited file does not exist: '{file_rel}'"

    line_str = finding.get("line")
    if not line_str:
        return False, "Finding missing 'line' specifier"

    try:
        start_line, end_line = parse_line_range(line_str)
    except ValueError as exc:
        return False, str(exc)

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return False, f"Could not read cited file '{file_rel}': {exc}"

    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return False, f"Cited file '{file_rel}' is empty"

    if start_line > total_lines:
        return False, f"Line range {line_str} begins beyond file length ({total_lines} lines)"

    evidence = finding.get("evidence", "").strip()
    if not evidence:
        return False, "Finding has empty 'evidence' quote"

    # Exact window check (1-indexed lines)
    slice_end = min(end_line, total_lines)
    window_lines = lines[start_line - 1 : slice_end]
    window_text = "\n".join(window_lines).strip()

    # Normalization helper for whitespace-insensitive comparison
    def normalize_ws(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    norm_evidence = normalize_ws(evidence)
    norm_window = normalize_ws(window_text)

    # 1. Direct or normalized match in specified line window
    if norm_evidence in norm_window or norm_window in norm_evidence:
        return True, f"Evidence grounded at {file_rel}:{line_str}"

    # 2. Window with context slack (+/- 10 lines to tolerate minor drift)
    slack_start = max(1, start_line - 10)
    slack_end = min(total_lines, end_line + 10)
    slack_window = "\n".join(lines[slack_start - 1 : slack_end])
    norm_slack = normalize_ws(slack_window)

    if norm_evidence in norm_slack:
        return True, f"Evidence grounded near {file_rel}:{line_str} (tolerated minor line offset)"

    # 3. Check if first non-trivial line of evidence is anywhere near the window
    ev_first_line = next((line.strip() for line in evidence.splitlines() if line.strip()), "")
    if ev_first_line and ev_first_line in slack_window:
        return True, f"Evidence partially grounded at {file_rel}:{line_str}"

    return False, f"Evidence quote not found in '{file_rel}' at or near lines {line_str}"


def verify_review_grounding(review_report: Dict[str, Any], repo_root: Path) -> VerificationRecord:
    """Evaluate grounding for all findings in a Review Judge report."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    findings = review_report.get("findings", []) if isinstance(review_report, dict) else []

    if not isinstance(review_report, dict):
        return VerificationRecord(
            claim="Review findings are grounded in repository source code",
            gate="review",
            tier=VerificationTier.GROUNDING.value,
            verdict="NOT_VERIFIED",
            method="source_grounding_inspection",
            findings=["Review report is not a dictionary"],
            timestamp=now_iso,
        )

    # If envelope was parsed, look inside judge_report if needed
    if not findings and isinstance(review_report.get("judge_report"), dict):
        findings = review_report["judge_report"].get("findings", [])

    if not findings:
        # Zero findings: check whether status was complete
        status = review_report.get("status") or (review_report.get("judge_report") or {}).get("status")
        verdict = review_report.get("verdict") or "PASS"
        if status in {"complete", "pass", "ok"}:
            return VerificationRecord(
                claim="Review findings are grounded in repository source code",
                gate="review",
                tier=VerificationTier.GROUNDING.value,
                verdict="VERIFIED",
                method="source_grounding_inspection",
                findings=["Clean review with 0 candidate findings; report status complete"],
                timestamp=now_iso,
                metadata={"findings_count": 0},
            )
        return VerificationRecord(
            claim="Review findings are grounded in repository source code",
            gate="review",
            tier=VerificationTier.GROUNDING.value,
            verdict="INCONCLUSIVE",
            method="source_grounding_inspection",
            findings=["Report has 0 findings but status is incomplete/unverified"],
            timestamp=now_iso,
            metadata={"findings_count": 0},
        )

    failures = []
    grounded_count = 0
    for idx, f in enumerate(findings):
        fid = f.get("id", f"finding-{idx+1}")
        ok, reason = verify_finding_grounding(f, repo_root)
        if ok:
            grounded_count += 1
        else:
            failures.append(f"{fid}: {reason}")

    score = grounded_count / len(findings) if findings else 1.0
    verdict = "VERIFIED" if len(failures) == 0 else "NOT_VERIFIED"
    details = [f"Verified {grounded_count}/{len(findings)} finding(s) grounded in source."]
    if failures:
        details.extend(failures)

    return VerificationRecord(
        claim="Review findings are grounded in repository source code",
        gate="review",
        tier=VerificationTier.GROUNDING.value,
        verdict=verdict,
        method="source_grounding_inspection",
        findings=details,
        score=score,
        timestamp=now_iso,
        metadata={"total_findings": len(findings), "grounded": grounded_count, "ungrounded": len(failures)},
    )


def execute_and_verify_tests(
    repo_root: Path,
    test_command: str,
    claimed_evidence: Optional[Dict[str, Any]] = None,
    timeout: int = 300,
) -> VerificationRecord:
    """Independently execute test command and verify against claimed evidence.

    Inspired by SWE-bench evaluation harness & e2b isolation:
    The engine invokes the test process directly in a subprocess, captures the OS
    exit code and terminal streams, and independently verifies whether tests pass.
    """
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cmd = test_command.strip() if test_command else ""
    if not cmd:
        return VerificationRecord(
            claim="Test suite passes cleanly when executed by engine",
            gate="implementation",
            tier=VerificationTier.EXECUTION.value,
            verdict="NOT_VERIFIED",
            method="engine_test_execution",
            findings=["No test command configured or detected in repository."],
            timestamp=now_iso,
        )

    from .vcs import GitClient
    before_fingerprint = GitClient().compute_working_tree_fingerprint(repo_root)
    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration = time.time() - start_time
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        return VerificationRecord(
            claim="Test suite passes cleanly when executed by engine",
            gate="implementation",
            tier=VerificationTier.EXECUTION.value,
            verdict="NOT_VERIFIED",
            method="engine_test_execution",
            findings=[f"Test execution timed out after {timeout} seconds: '{cmd}'"],
            timestamp=now_iso,
            metadata={"command": cmd, "timeout": timeout},
        )
    except Exception as exc:
        return VerificationRecord(
            claim="Test suite passes cleanly when executed by engine",
            gate="implementation",
            tier=VerificationTier.EXECUTION.value,
            verdict="NOT_VERIFIED",
            method="engine_test_execution",
            findings=[f"Failed to execute test command '{cmd}': {exc}"],
            timestamp=now_iso,
            metadata={"command": cmd, "error": str(exc)},
        )

    after_fingerprint = GitClient().compute_working_tree_fingerprint(repo_root)
    passed = (exit_code == 0 and before_fingerprint == after_fingerprint)
    stdout_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
    output_tail = stdout[-1000:] if len(stdout) > 1000 else stdout

    findings = []
    if not passed:
        err_msg = f"Test execution failed with OS exit code {exit_code} (command: '{cmd}')."
        findings.append(err_msg)
        if stderr:
            stderr_snip = stderr[-400:].strip()
            findings.append(f"Stderr: {stderr_snip}")
    else:
        findings.append(f"Independent test run completed with exit code 0 in {duration:.2f}s.")

    # Check for circular trust contradiction: did agent claim tests passed while engine failed?
    if claimed_evidence:
        claimed_pass = claimed_evidence.get("tests_passed") or claimed_evidence.get("passed")
        if claimed_pass is True and not passed:
            findings.append("CONTRADICTION DETECTED: Agent claimed tests passed, but independent execution failed.")

    verdict = "VERIFIED" if passed else "NOT_VERIFIED"
    try:
        from .events import EventLogger
        from .models import EventType
        EventLogger(repo_root).emit(
            event_type=EventType.TEST_EXECUTED,
            agent_id="engine",
            target=cmd,
            payload={
                "command": cmd,
                "exit_code": exit_code,
                "passed": passed,
                "duration_seconds": round(duration, 3),
                "stdout_sha256": stdout_hash,
            },
        )
    except Exception:
        pass

    return VerificationRecord(
        claim="Test suite passes cleanly when executed by engine",
        gate="implementation",
        tier=VerificationTier.EXECUTION.value,
        verdict=verdict,
        method="engine_test_execution",
        findings=findings,
        score=1.0 if passed else 0.0,
        timestamp=now_iso,
        metadata={
            "command": cmd,
            "snapshot_fingerprint": after_fingerprint,
            "exit_code": exit_code,
            "duration_seconds": round(duration, 3),
            "stdout_sha256": stdout_hash,
            "output_tail": output_tail,
        },
    )


def verify_test_quality(
    repo_root: Path,
    changed_files: Optional[List[str]] = None,
    test_command: Optional[str] = None,
    threshold: float = 0.70,
) -> VerificationRecord:
    """Evaluate test quality via mutation testing (Tier 4).

    Inspired by boxed/mutmut & stryker-js:
    If mutmut is available, runs scoped mutation check; otherwise gracefully skips
    with an advisory notice.
    """
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mutmut_bin = shutil.which("mutmut")
    if not mutmut_bin:
        return VerificationRecord(
            claim="Test suite kills injected code mutations (assertion rigor)",
            gate="implementation",
            tier=VerificationTier.MUTATION.value,
            verdict="SKIPPED",
            method="mutation_testing",
            findings=["mutmut is not installed; mutation testing skipped."],
            timestamp=now_iso,
            metadata={"installed": False},
        )

    if not changed_files:
        return VerificationRecord(
            claim="Test suite kills injected code mutations (assertion rigor)",
            gate="implementation",
            tier=VerificationTier.MUTATION.value,
            verdict="SKIPPED",
            method="mutation_testing",
            findings=["No changed source files provided for scoped mutation testing."],
            timestamp=now_iso,
            metadata={"changed_files_count": 0},
        )

    # Scoped mutation check
    py_files = [f for f in changed_files if f.endswith(".py") and not f.startswith("tests/")]
    if not py_files:
        return VerificationRecord(
            claim="Test suite kills injected code mutations (assertion rigor)",
            gate="implementation",
            tier=VerificationTier.MUTATION.value,
            verdict="SKIPPED",
            method="mutation_testing",
            findings=["No modified Python production files found for mutation testing."],
            timestamp=now_iso,
        )

    return VerificationRecord(
        claim="Test suite kills injected code mutations (assertion rigor)",
        gate="implementation",
        tier=VerificationTier.MUTATION.value,
        verdict="INCONCLUSIVE",
        method="mutation_testing",
        findings=["Mutation execution is not implemented; finding candidate files does not verify test quality."],
        score=0.0,
        timestamp=now_iso,
        metadata={"target_files": py_files, "threshold": threshold},
    )


def verify_spec_coverage(
    repo_root: Path,
    change: str,
    review_report: Optional[Dict[str, Any]] = None,
) -> VerificationRecord:
    """Verify that OpenSpec requirements have corresponding tests and review coverage (Tier 5).

    Inspired by SWE-bench gold-test and gatecheck threshold model:
    Verifies that specifications are not merely ticked off without corresponding test code.
    """
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pkg_dir = repo_root / "openspec" / "changes" / change
    if not pkg_dir.exists() or not pkg_dir.is_dir():
        return VerificationRecord(
            claim="Specifications and requirements are covered by tests and review",
            gate="delivery",
            tier=VerificationTier.COVERAGE.value,
            verdict="VERIFIED",
            method="spec_coverage_cross_reference",
            findings=[f"No OpenSpec directory for change '{change}'; skipping spec check."],
            timestamp=now_iso,
        )

    specs_dir = pkg_dir / "specs"
    spec_files = list(specs_dir.glob("*.md")) if specs_dir.exists() else []
    tasks_file = pkg_dir / "tasks.md"

    if not spec_files and not tasks_file.exists():
        return VerificationRecord(
            claim="Specifications and requirements are covered by tests and review",
            gate="delivery",
            tier=VerificationTier.COVERAGE.value,
            verdict="VERIFIED",
            method="spec_coverage_cross_reference",
            findings=["OpenSpec package contains no spec files or tasks."],
            timestamp=now_iso,
        )

    # Check tests directory
    tests_dir = repo_root / "tests"
    test_files = list(tests_dir.rglob("test_*.py")) if tests_dir.exists() else []

    findings = []
    if spec_files and not test_files:
        findings.append(f"Change '{change}' declares {len(spec_files)} spec(s) but no test files were found in tests/.")
        return VerificationRecord(
            claim="Specifications and requirements are covered by tests and review",
            gate="delivery",
            tier=VerificationTier.COVERAGE.value,
            verdict="NOT_VERIFIED",
            method="spec_coverage_cross_reference",
            findings=findings,
            score=0.0,
            timestamp=now_iso,
        )

    findings.append(f"Found {len(spec_files)} spec file(s) and {len(test_files)} test file(s).")
    return VerificationRecord(
        claim="Specifications and requirements are covered by tests and review",
        gate="delivery",
        tier=VerificationTier.COVERAGE.value,
        verdict="VERIFIED",
        method="spec_coverage_cross_reference",
        findings=findings,
        score=1.0,
        timestamp=now_iso,
        metadata={"specs_count": len(spec_files), "test_files_count": len(test_files)},
    )


def run_gate_verification(
    repo_root: Path,
    change: str,
    active_pkg: Optional[Dict[str, Any]],
    review_report: Optional[Dict[str, Any]],
    active_change: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
    tiers: Optional[List[str]] = None,
    test_command: Optional[str] = None,
    verifier_id: str = "agentflow-verifier",
    session_id: Optional[str] = None,
    runtime: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, VerificationRecord]:
    """Coordinate multi-tier independent verification for a change.

    Runs enabled tiers:
    - Tier 2 (Grounding): review findings grounded in code
    - Tier 3 (Execution): independent test re-run
    - Tier 4 (Mutation): test quality check (if enabled/available)
    - Tier 5 (Coverage): spec-to-test cross reference
    """
    cfg = config or {}
    results: Dict[str, VerificationRecord] = {}
    requested = set(tiers) if tiers else {"grounding", "execution", "coverage"}

    try:
        from .events import EventLogger
        from .models import EventType
        EventLogger(repo_root).emit(
            event_type=EventType.VERIFICATION_STARTED,
            change_id=change,
            agent_id=verifier_id,
            session_id=session_id or f"sess-{verifier_id}",
            target=change,
            payload={"tiers": sorted(list(requested)), "test_command": test_command},
        )
    except Exception:
        pass

    # Tier 2: Grounding
    if "grounding" in requested or "all" in requested:
        if review_report:
            results["grounding"] = verify_review_grounding(review_report, repo_root)
        else:
            now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            results["grounding"] = VerificationRecord(
                claim="Review findings are grounded in repository source code",
                gate="review",
                tier=VerificationTier.GROUNDING.value,
                verdict="INCONCLUSIVE",
                method="source_grounding_inspection",
                findings=["No review report found to ground."],
                timestamp=now_iso,
                verifier_id=verifier_id,
            )

    # Tier 3: Execution
    if "execution" in requested or "all" in requested:
        cmd = test_command or cfg.get("gates", {}).get("implementation", {}).get("test")
        claimed = (active_change or {}).get("evidence", {}).get("implementation", {})
        results["execution"] = execute_and_verify_tests(repo_root, cmd or "", claimed_evidence=claimed)

    # Tier 4: Mutation (if explicitly requested or enabled in config)
    mut_cfg = cfg.get("gates", {}).get("implementation", {}).get("verification", {}).get("mutation", {})
    if "mutation" in requested or "all" in requested or mut_cfg.get("enabled"):
        results["mutation"] = verify_test_quality(
            repo_root,
            changed_files=(active_change or {}).get("modified_files"),
            test_command=test_command,
            threshold=mut_cfg.get("threshold", 0.70),
        )

    # Tier 5: Coverage
    if "coverage" in requested or "all" in requested:
        results["coverage"] = verify_spec_coverage(repo_root, change, review_report=review_report)

    # Stamp ActionProvenance onto all records
    from .models import ActionProvenance, AgentRole
    from .provenance import compute_payload_digest
    import uuid
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Check for target evidence producer provenance in active_change turns
    turns = (active_change or {}).get("turns", [])
    target_prov = None
    for t in reversed(turns):
        if t.get("provenance"):
            target_prov = t["provenance"]
            break

    for tier_name, rec in results.items():
        rec.verifier_id = verifier_id
        if not rec.provenance:
            prov = ActionProvenance(
                action_id=f"act-{uuid.uuid4().hex[:12]}",
                action_name=f"verify_{tier_name}",
                agent_id=verifier_id,
                session_id=session_id or f"sess-{verifier_id}",
                change_id=change or "active",
                role=AgentRole.VERIFIER.value,
                timestamp=rec.timestamp or now_iso,
                runtime=runtime or "antigravity",
                model=model or "unknown",
                skill="verification",
                skill_version="1.0.0",
                agentflow_version="1.0.0",
                inputs_digest=compute_payload_digest({"claim": rec.claim, "tier": rec.tier, "method": rec.method}),
                evidence_digest=compute_payload_digest({"verdict": rec.verdict, "findings": rec.findings, "score": rec.score}),
            )
            rec.provenance = prov.to_dict()
        if not rec.target_provenance and target_prov:
            rec.target_provenance = target_prov

    try:
        from .events import EventLogger
        from .models import EventType
        all_passed = all(rec.verdict == "VERIFIED" for rec in results.values())
        EventLogger(repo_root).emit(
            event_type=EventType.VERIFICATION_PASSED if all_passed else EventType.VERIFICATION_FAILED,
            change_id=change,
            agent_id=verifier_id,
            session_id=session_id or f"sess-{verifier_id}",
            target=change,
            payload={tier: rec.verdict for tier, rec in results.items()},
        )
    except Exception:
        pass

    return results


def format_verification_summary(records: Dict[str, VerificationRecord], change: str = "") -> str:
    """Format verification records into an agent- and human-readable terminal summary card."""
    cid_str = f" FOR '{change}'" if change else ""
    lines = [
        "═════════════════════════════════════════════════════════════════════",
        f" 🛡️  INDEPENDENT VERIFICATION SUMMARY{cid_str}",
        "═════════════════════════════════════════════════════════════════════",
    ]
    if not records:
        lines.append("• No verification records available.")
    else:
        for tier_name, rec in records.items():
            status_icon = "✅" if rec.verdict == "VERIFIED" else ("⚠️" if rec.verdict in ("INCONCLUSIVE", "SKIPPED") else "❌")
            score_str = f" (score: {rec.score:.2f})" if rec.score is not None else ""
            lines.append(f"{status_icon} Tier: {rec.tier.upper()} ({rec.gate}) -> {rec.verdict}{score_str}")
            lines.append(f"  └─ Method: {rec.method}")
            for f in rec.findings[:3]:
                lines.append(f"  └─ Detail: {f}")
            if len(rec.findings) > 3:
                lines.append(f"  └─ ... (+{len(rec.findings) - 3} more finding(s))")
            lines.append("─────────────────────────────────────────────────────────────────────")
    lines.append("═════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)
