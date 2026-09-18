"""Dispatch handlers for Ship MCP tools."""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from ship.lifecycle.engine import LifecycleEngine
from ship.lifecycle.turns import format_turn_contract
from ship.lifecycle.ledger import FileLedgerStore, record_test_run_to_ledger, record_review_to_ledger, record_turn_to_ledger
from ship.lifecycle.checkpoints import CheckpointManager
from ship.lifecycle.operations import doctor
from ship.lifecycle.trailers import CommitTrailerGenerator
from ship.lifecycle.specs import OpenSpecRepository

from ship.tools.tdd import verify_tdd, trim_test_receipt
from ship.tools.simplify import scan_debt, format_table
from ship.tools.spike import run_benchmark, format_markdown_table
from ship.tools.review import validate_report, parse_report


def _get_root(args: Dict[str, Any]) -> Path:
    p = args.get("path") or "."
    return Path(p).resolve()


def handle_ship_next_turn(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args.get("change")
    fmt = args.get("format", "text")
    engine = LifecycleEngine()
    contract = engine.get_next_turn_contract(root, target_change=change)
    if fmt == "json":
        return contract.to_dict()
    return {"text": format_turn_contract(contract), "contract": contract.to_dict()}


def handle_ship_status(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args.get("change")
    engine = LifecycleEngine()
    evaluation = engine.evaluate_repository(root, target_change=change)
    gate = evaluation.get("gate", "design")
    state_key = evaluation.get("state_key")
    ready = (state_key == "DELIVERY_READY")
    blockers = (evaluation.get("active_change") or {}).get("blockers", [])
    report = evaluation.get("review_report")

    reasons = []
    if not ready:
        if evaluation.get("next_action"):
            reasons.append(evaluation["next_action"])
        if blockers:
            reasons.extend(blockers)

    status_str = "READY" if ready else ("ROLLBACK_REQUIRED" if any("invariant" in b.lower() for b in blockers) else "BLOCKED")
    exit_code = 0 if ready else 1
    if not ready:
        if status_str == "ROLLBACK_REQUIRED":
            exit_code = 2
        elif report:
            verdict = report.get("verdict", "")
            status = report.get("status", "")
            if (
                report.get("critical_or_high_count", 0) > 0
                or verdict in {"FAIL", "FAILED", "REJECTED"}
                or status in {"fail", "failed", "rejected"}
            ):
                exit_code = 2

    return {
        "status": status_str,
        "exit_code": exit_code,
        "active_gate": gate,
        "state_key": state_key,
        "ready_for_delivery": ready,
        "reasons": reasons,
        "blockers": blockers,
        "next_action": evaluation.get("next_action"),
    }


def handle_ship_evaluate(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args.get("change")
    engine = LifecycleEngine()
    return engine.evaluate_repository(root, target_change=change)


def handle_ship_record_turn(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args.get("change")
    record_payload = {
        "skill": args.get("skill"),
        "inputs": args.get("inputs", {}),
        "evidence": args.get("evidence", {}),
        "state_delta": args.get("state_delta", {}),
        "harness": args.get("harness", "generic"),
        "execution_mode": args.get("execution_mode", "sequential"),
    }
    rec = record_turn_to_ledger(root, record_payload, change_id=change)
    return rec


def handle_ship_checkpoint(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    gate = args["gate"]
    change = args.get("change")
    mgr = CheckpointManager()
    res = mgr.create_checkpoint(root, gate, change=change)
    return {
        "checkpoint_ref": res.get("ref"),
        "receipt": res,
        "gate": gate,
        "change_id": change,
    }


def handle_ship_rollback(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    gate = args["gate"]
    change = args.get("change")
    mgr = CheckpointManager()
    res = mgr.perform_rollback(root, gate, change=change)
    return {
        "status": res.get("status"),
        "target_gate": res.get("target_gate"),
        "change_id": change,
        "backup_directory": res.get("backup_directory"),
        "message": res.get("message"),
        "details": res,
    }


def handle_ship_approve_design(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args["change"]
    fp = args["fingerprint"]
    by = args.get("approved_by") or "session-user"
    res = FileLedgerStore.approve_design(root, change, fp, by)
    return {
        "status": "APPROVED",
        "change_id": change,
        "fingerprint": fp,
        "approved_by": by,
        "ledger_change": res,
    }


def handle_ship_record_tests(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    passed = bool(args["passed"])
    change = args.get("change")
    output = args.get("output", "")
    data = {"passed": passed, "raw_receipt": output}
    entry = record_test_run_to_ledger(root, data, change_id=change)
    return {
        "status": "RECORDED",
        "passed": passed,
        "change_id": change,
        "ledger_change": entry,
    }


def handle_ship_record_review(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args.get("change")
    report_path = args.get("report_path")
    if not report_path and args.get("report_data"):
        scratch = root / ".scratch" / (change or "default")
        scratch.mkdir(parents=True, exist_ok=True)
        tmp_file = scratch / "review_report.json"
        tmp_file.write_text(json.dumps(args["report_data"], indent=2), encoding="utf-8")
        report_path = str(tmp_file)
    if not report_path:
        raise ValueError("Either report_path or report_data must be provided.")
    entry = record_review_to_ledger(root, report_path, change_id=change)
    return {
        "status": "RECORDED",
        "report_path": report_path,
        "change_id": change,
        "ledger_change": entry,
    }


def handle_ship_archive(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args["change"]
    force = bool(args.get("force", False))
    repo = OpenSpecRepository()
    engine = LifecycleEngine(spec_repo=repo)
    res = engine.archive_change(root, change, force=force)
    return {
        "status": "ARCHIVED",
        "change_id": change,
        "archive_path": str(res.get("archived_path", "")),
        "trailers": res.get("trailers", []),
        "details": res,
    }


def handle_ship_trailers(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    change = args["change"]
    generator = CommitTrailerGenerator()
    trailers = generator.generate_trailers(root, target_change=change)
    return {
        "change_id": change,
        "trailers": trailers,
        "formatted": "\n".join(trailers),
    }


def handle_ship_doctor(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    return doctor(root)


def handle_ship_tdd_verify(args: Dict[str, Any]) -> Dict[str, Any]:
    root = _get_root(args)
    trim_text = args.get("trim_receipt")
    if trim_text:
        return {"trimmed_receipt": trim_test_receipt(trim_text)}
    ref_range = args.get("ref_range")
    files = args.get("files")
    strict = bool(args.get("strict", False))
    res = verify_tdd(ref_range=ref_range, files=files, repo_root=root, strict=strict)
    return {
        "passed": res.passed,
        "production_files": res.production_files,
        "test_files": res.test_files,
        "untested_files": res.untested_files,
        "findings": [
            {
                "category": f.category,
                "file": f.file,
                "line": f.line,
                "message": f.message,
                "severity": f.severity,
            }
            for f in res.findings
        ],
        "error": res.error,
    }


def handle_ship_simplify_scan(args: Dict[str, Any]) -> Dict[str, Any]:
    paths = args.get("paths")
    strict = bool(args.get("strict", False))
    root = _get_root(args)
    target_paths = [Path(p) if Path(p).is_absolute() else (root / p) for p in paths] if paths else [root]
    markers, has_errors = scan_debt(target_paths, strict=strict)
    table = format_table(markers, markdown=True)
    return {
        "passed": not has_errors,
        "total_markers": len(markers),
        "markers": markers,
        "table": table,
    }


def handle_ship_spike_run(args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = args["command"]
    iterations = int(args.get("iterations", 10))
    concurrency = int(args.get("concurrency", 1))
    warmup = int(args.get("warmup", 0))
    timeout = float(args.get("timeout_sec", 60.0))
    cwd = Path(args["path"]).resolve() if args.get("path") else None
    result = run_benchmark(cmd, iterations=iterations, concurrency=concurrency, warmup=warmup, timeout_sec=timeout, cwd=cwd)
    table = format_markdown_table(result)
    return {
        "summary": result.to_dict(),
        "table": table,
    }


def handle_ship_review_validate(args: Dict[str, Any]) -> Dict[str, Any]:
    report_data = args.get("report_data")
    if not report_data and args.get("report_path"):
        raw = Path(args["report_path"]).read_text(encoding="utf-8")
        report_data = parse_report(raw)
    if report_data is None:
        raise ValueError("Either report_data or report_path is required.")
    errors = validate_report(report_data)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


HANDLERS: Dict[str, Any] = {
    "ship_next_turn": handle_ship_next_turn,
    "ship_status": handle_ship_status,
    "ship_evaluate": handle_ship_evaluate,
    "ship_record_turn": handle_ship_record_turn,
    "ship_checkpoint": handle_ship_checkpoint,
    "ship_rollback": handle_ship_rollback,
    "ship_approve_design": handle_ship_approve_design,
    "ship_record_tests": handle_ship_record_tests,
    "ship_record_review": handle_ship_record_review,
    "ship_archive": handle_ship_archive,
    "ship_trailers": handle_ship_trailers,
    "ship_doctor": handle_ship_doctor,
    "ship_tdd_verify": handle_ship_tdd_verify,
    "ship_simplify_scan": handle_ship_simplify_scan,
    "ship_spike_run": handle_ship_spike_run,
    "ship_review_validate": handle_ship_review_validate,
}


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    handler = HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Unknown tool: '{name}'. Available tools: {list(HANDLERS.keys())}")
    return handler(arguments)
