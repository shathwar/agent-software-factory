#!/usr/bin/env python3
"""inspect_lifecycle.py — CLI front-end and facade for the Ship Lifecycle Engine."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

# Enable both direct script execution and package import
_current_dir = Path(__file__).resolve().parent
if str(_current_dir) not in sys.path:
    sys.path.insert(0, str(_current_dir))

from lifecycle import (
    CheckpointManager,
    CommitTrailerGenerator,
    FileLedgerStore,
    GIT_NOTES_REF,
    GateResult,
    GateStatus,
    GitClient,
    GitInfo,
    LifecycleEngine,
    LifecyclePhase,
    OpenSpecInfo,
    OpenSpecRepository,
    ShipConfig,
    ShipConfigManager,
    VerificationResult,
    canonicalize_gate_name,
    determine_lifecycle_state,
    format_summary,
    format_turn_contract,
    format_turns_log,
    get_next_turn_contract,
    get_turns_from_ledger,
    inspect_review_reports,
    inspect_spikes,
    is_spike_completed,
    is_test_evidence_passing,
    merge_spec_requirements,
    normalize_req_title,
    parse_requirements_doc,
    record_turn_to_ledger,
    resolve_skill_name,
    validate_delivery_readiness,
    validate_judge_report_contract,
    validate_review_approval,
)
from lifecycle.evidence import is_evidence_dir, parse_review_report_file
from lifecycle.ledger import create_empty_change_entry, ensure_gitignore_has_ship

__all__ = [
    "CheckpointManager",
    "CommitTrailerGenerator",
    "FileLedgerStore",
    "GIT_NOTES_REF",
    "GateResult",
    "GateStatus",
    "GitClient",
    "GitInfo",
    "LifecycleEngine",
    "LifecyclePhase",
    "OpenSpecInfo",
    "OpenSpecRepository",
    "ShipConfig",
    "ShipConfigManager",
    "VerificationResult",
    "canonicalize_gate_name",
    "determine_lifecycle_state",
    "format_summary",
    "format_turn_contract",
    "format_turns_log",
    "get_next_turn_contract",
    "get_turns_from_ledger",
    "inspect_review_reports",
    "inspect_spikes",
    "is_spike_completed",
    "is_test_evidence_passing",
    "merge_spec_requirements",
    "normalize_req_title",
    "parse_requirements_doc",
    "record_turn_to_ledger",
    "resolve_skill_name",
    "validate_delivery_readiness",
    "validate_judge_report_contract",
    "validate_review_approval",
    "parse_review_report_file",
    "create_empty_change_entry",
    "is_evidence_dir",
    "ensure_gitignore_has_ship",
]

# Shared singleton instances for default facade delegation
_vcs = GitClient()
_config_mgr = ShipConfigManager()
_spec_repo = OpenSpecRepository()
_ledger_store = FileLedgerStore()
_engine = LifecycleEngine(
    vcs_client=_vcs,
    config_manager=_config_mgr,
    spec_repo=_spec_repo,
    ledger_store=_ledger_store,
)


# ---------------------------------------------------------------------------
# Public Facade Functions (Backwards Compatibility & Direct Script Use)
# ---------------------------------------------------------------------------

def git_cmd(
    repo_root: Path,
    *args: str,
    check: bool = False,
    env: Optional[Dict[str, str]] = None,
    text: bool = True,
) -> Any:
    return _vcs.run_cmd(repo_root, *args, check=check, env=env, text=text)


def git_out(repo_root: Path, *args: str) -> str:
    return _vcs.get_output(repo_root, *args)


def compute_working_tree_fingerprint(repo_root: Path) -> str:
    return _vcs.compute_working_tree_fingerprint(repo_root)


def load_ship_config(repo_root: Path, explicit_path: Optional[str] = None) -> Dict[str, Any]:
    return _config_mgr.load(repo_root, explicit_path=explicit_path)


def get_git_info(repo_root: Path) -> Dict[str, Any]:
    return _vcs.get_info(repo_root)


def inspect_adrs(repo_root: Path) -> List[Dict[str, Any]]:
    return _spec_repo.inspect_adrs(repo_root)


def get_active_change(repo_root: Path) -> Optional[str]:
    return _ledger_store.get_active_change(repo_root)


def ledger_lock(repo_root: Path, timeout_sec: float = 10.0):
    return _ledger_store.lock(repo_root, timeout_sec=timeout_sec)


def set_active_change(repo_root: Path, change: str) -> None:
    _ledger_store.set_active_change(repo_root, change, sync_fn=_engine.sync_ledger)


def clear_active_change(repo_root: Path, change: Optional[str] = None) -> None:
    _ledger_store.clear_active_change(repo_root, change=change)


def inspect_openspec(repo_root: Path, target_change: Optional[str] = None) -> List[Dict[str, Any]]:
    return _spec_repo.inspect_openspec(
        repo_root,
        target_change=target_change,
        get_active_fn=_ledger_store.get_active_change,
        clear_active_fn=_ledger_store.clear_active_change,
    )


def inspect_archived_openspec(repo_root: Path) -> List[Dict[str, Any]]:
    return _spec_repo.inspect_archived_openspec(repo_root)


def inspect_living_specs(repo_root: Path) -> List[Dict[str, Any]]:
    return _spec_repo.inspect_living_specs(repo_root)


def save_ledger(repo_root: Path, ledger: Dict[str, Any]) -> None:
    _ledger_store.save(repo_root, ledger)


def sync_ledger_from_workspace(repo_root: Path, target_change_id: Optional[str] = None) -> Dict[str, Any]:
    return _engine.sync_ledger(repo_root, target_change_id=target_change_id)


def load_ledger(repo_root: Path, auto_sync: bool = True) -> Dict[str, Any]:
    return _ledger_store.load(repo_root, auto_sync=auto_sync, sync_fn=_engine.sync_ledger)


def mutate_change_state(
    repo_root: Path,
    change_id: str,
    updater: Any,
    set_active: bool = True,
) -> Dict[str, Any]:
    return _ledger_store.mutate_change(
        repo_root, change_id, updater, set_active=set_active, sync_fn=_engine.sync_ledger
    )


def attach_git_note_evidence(
    repo_root: Path,
    commit_sha: str,
    evidence_type: str,
    data: Dict[str, Any],
    ref: str = GIT_NOTES_REF,
    change_id: Optional[str] = None,
) -> Optional[str]:
    return _vcs.attach_git_note_evidence(
        repo_root,
        commit_sha,
        evidence_type,
        data,
        ref=ref,
        change_id=change_id,
        active_change=_ledger_store.get_active_change(repo_root),
    )


def read_git_note_evidence(
    repo_root: Path,
    commit_sha: str,
    ref: str = GIT_NOTES_REF,
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _vcs.read_git_note_evidence(repo_root, commit_sha, ref=ref, change_id=change_id)


def generate_gate_trailers(
    repo_root: Path,
    change_id: Optional[str] = None,
    ledger: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    return CommitTrailerGenerator.generate(
        repo_root,
        change_id=change_id,
        ledger=ledger,
        config=config,
        load_ledger_fn=_ledger_store.load,
        load_config_fn=_config_mgr.load,
        get_active_change_fn=_ledger_store.get_active_change,
        create_empty_change_fn=create_empty_change_entry,
        get_git_info_fn=_vcs.get_info,
    )


def record_review_to_ledger(
    repo_root: Path,
    report_path_or_dict: Any,
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _ledger_store.record_review(
        repo_root,
        report_path_or_dict,
        change_id=change_id,
        parse_report_fn=parse_review_report_file,
        get_git_info_fn=_vcs.get_info,
        attach_note_fn=_vcs.attach_git_note_evidence,
        sync_fn=_engine.sync_ledger,
    )


def record_test_run_to_ledger(
    repo_root: Path,
    test_summary: Dict[str, Any],
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _ledger_store.record_test_run(
        repo_root,
        test_summary,
        change_id=change_id,
        get_git_info_fn=_vcs.get_info,
        attach_note_fn=_vcs.attach_git_note_evidence,
        notes_ref=GIT_NOTES_REF,
        sync_fn=_engine.sync_ledger,
    )


def apply_and_archive_openspec(
    repo_root: Path,
    change: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    return _engine.archive_change(repo_root, change=change, force=force)


def create_checkpoint(
    repo_root: Path,
    gate_name: str,
    change: Optional[str] = None,
    create_git_tag: bool = False,
) -> Dict[str, Any]:
    return _engine.checkpoints.create_checkpoint(
        repo_root, gate_name, change=change, create_git_tag=create_git_tag
    )


def perform_rollback(
    repo_root: Path,
    target_gate: str,
    change: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    return _engine.checkpoints.perform_rollback(
        repo_root, target_gate, change=change, force=force
    )


def get_next_turn(
    repo_root: Path,
    target_change: Optional[str] = None,
    config_path: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> Any:
    return _engine.get_next_turn_contract(
        repo_root, target_change=target_change, config_path=config_path, execution_mode=execution_mode
    )


def record_turn(
    repo_root: Path,
    turn_data: Dict[str, Any],
    change_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _ledger_store.record_turn(repo_root, turn_data, change_id=change_id, sync_fn=_engine.sync_ledger)


def get_turns(
    repo_root: Path,
    change_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    return _ledger_store.get_turns(repo_root, change_id=change_id)


def evaluate_repository(
    repo_root: Path,
    target_change: Optional[str] = None,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    return _engine.evaluate_repository(
        repo_root, target_change=target_change, config_path=config_path
    )


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

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
        help="Path to custom .agentflow.json configuration.",
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
        help="Explicitly authorize whole-checkout rollback, or force archive workflow checks.",
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
        "--set-active-change",
        default=None,
        metavar="CHANGE_ID",
        help="Set the active change ID in .agentflow/state.json.",
    )
    parser.add_argument(
        "--sync-state",
        action="store_true",
        help="Force re-synchronize .agentflow/state.json from workspace artifacts.",
    )
    parser.add_argument(
        "--record-review",
        default=None,
        metavar="REPORT_JSON",
        help="Record a review report JSON into .agentflow/state.json and git notes.",
    )
    parser.add_argument(
        "--record-tests",
        default=None,
        metavar="TEST_DATA",
        help="Record test results into .agentflow/state.json and git notes (passed/failed or path to JSON).",
    )
    parser.add_argument(
        "--generate-trailers",
        action="store_true",
        help="Generate and print RFC 5133 commit trailers for the active or specified change.",
    )

    parser.add_argument("--design-fingerprint", action="store_true", help="Print the design digest for --change.")
    parser.add_argument(
        "--approve-design",
        nargs="?",
        const="auto",
        default=None,
        metavar="SHA256",
        help="Record external approval of this design digest; pass SHA256 or 'auto' (default: auto). Uses --change or auto-detected active change.",
    )
    parser.add_argument("--approved-by", help="Identity supplied by the approving user or trusted host (default: session-user).")

    parser.add_argument(
        "--next-turn",
        action="store_true",
        help="Evaluate repository state and output the deterministic Turn Contract for the active change.",
    )
    parser.add_argument(
        "--record-turn",
        default=None,
        metavar="TURN_JSON_OR_PATH",
        help="Record a specialist turn into the ledger turn provenance history.",
    )
    parser.add_argument(
        "--turns",
        "--provenance",
        action="store_true",
        dest="show_turns",
        help="Display the turn-level provenance audit trail for --change.",
    )
    parser.add_argument(
        "--harness",
        default=None,
        help="Harness identifier for recorded turns (e.g. claude-code, opencode, cursor, ci, antigravity).",
    )

    parser.add_argument("--doctor", action="store_true", help="Check the local installation and workspace without modifying them.")
    parser.add_argument("--migrate-state", action="store_true", help="Back up and migrate a supported legacy versionless ledger to v1.")
    parser.add_argument("--version", action="store_true", help="Print the installed suite version.")
    parser.add_argument("--verify", action="store_true", help="Execute independent verification and record its receipt.")
    parser.add_argument("--tier", choices=["execution", "grounding", "mutation", "coverage", "all"],
                        default="execution", help="Verification tier (default: execution).")

    args = parser.parse_args(argv)
    repo_root = Path(args.path).resolve()

    def output_result(payload: Any, text_lines: Optional[Sequence[str]] = None) -> None:
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        elif text_lines is not None:
            for line in text_lines:
                print(line)

    def banner(title: str, lines: Sequence[str]) -> List[str]:
        bar = "═" * 69
        return [bar, f" {title}", bar, *lines, bar]

    if args.version:
        print((Path(__file__).resolve().parent.parent / "VERSION").read_text().strip())
        return 0
    if args.doctor:
        from lifecycle.operations import doctor
        result = doctor(repo_root)
        output_result(result, [f"Ship {result['version']}"] + [f"{'OK' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}" for c in result['checks']])
        return 0 if result["ok"] else 1
    if args.migrate_state:
        from lifecycle.operations import migrate_state
        try:
            result = migrate_state(repo_root)
            output_result(result, [json.dumps(result)])
            return 0
        except (ValueError, OSError) as exc:
            print(f"State migration failed: {exc}", file=sys.stderr)
            return 1

    try:
        load_ship_config(repo_root, explicit_path=args.config)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.verify:
        from lifecycle.verification import format_verification_summary
        try:
            target_change = args.change or _ledger_store.get_active_change(repo_root)
            if not target_change:
                packages = _spec_repo.inspect_openspec(repo_root)
                if len(packages) == 1:
                    target_change = packages[0]["change"]
            records = _engine.verify_change(repo_root, change=target_change, tiers=[args.tier])
            output_result({k: v.to_dict() for k, v in records.items()},
                          [format_verification_summary(records, change=target_change or "")])
            return 0 if records and all(r.verdict == "VERIFIED" for r in records.values()) else 1
        except Exception as exc:
            print(f"Error during verification: {exc}", file=sys.stderr)
            return 1

    if args.next_turn:
        try:
            contract = _engine.get_next_turn_contract(
                repo_root, target_change=args.change, config_path=args.config
            )
            output_result(contract.to_dict(), [format_turn_contract(contract)])
            return 0
        except Exception as e:
            print(f"Error deriving next turn: {e}", file=sys.stderr)
            return 1

    if args.show_turns:
        turns = _ledger_store.get_turns(repo_root, change_id=args.change)
        output_result(turns, None if args.format == "json" else [format_turns_log(turns, change_id=args.change)])
        return 0

    if args.record_turn:
        try:
            raw = args.record_turn.strip()
            if raw.startswith(("{", "[")):
                tdata = json.loads(raw)
            elif Path(raw).is_file():
                tdata = json.loads(Path(raw).read_text(encoding="utf-8"))
            elif raw in {"ship", "design", "spike", "tdd", "simplify", "review", "delivery"}:
                tdata = {"skill": raw}
            else:
                raise ValueError("Supply turn JSON, an existing JSON file, or a known skill name")
            if not isinstance(tdata, dict):
                raise ValueError("Turn record must be a JSON object")
            if args.harness:
                tdata["harness"] = args.harness
            res = _ledger_store.record_turn(repo_root, tdata, change_id=args.change)
            rev = res.get("revision_counter", 0)
            turns_cnt = len(res.get("turns", []))
            output_result(res, [f"Turn recorded for change '{res.get('change_id')}' (total turns: {turns_cnt}, rev: r{rev})"])
            return 0
        except Exception as e:
            print(f"Error recording turn: {e}", file=sys.stderr)
            return 1

    if args.design_fingerprint or args.approve_design is not None:
        from lifecycle.evidence import design_fingerprint
        try:
            target_change = args.change
            if not target_change:
                active = _ledger_store.get_active_change(repo_root)
                if active:
                    target_change = active
                else:
                    packages = _spec_repo.inspect_openspec(repo_root)
                    if len(packages) == 1:
                        target_change = packages[0]["change"]
                    elif packages:
                        raise ValueError("Multiple active changes found. Please specify --change <name>")
                    else:
                        raise ValueError("Design approval requires explicit --change (no active change package found)")
            if args.design_fingerprint:
                digest = design_fingerprint(repo_root, target_change)
                output_result({"fingerprint": digest}, [digest])
            else:
                digest = args.approve_design
                if not digest or digest.lower() == "auto":
                    digest = design_fingerprint(repo_root, target_change)
                approver = args.approved_by or "session-user"
                res = _ledger_store.approve_design(repo_root, target_change, digest, approver)
                output_result(res, [f"Design approval recorded for {target_change}"])
            return 0
        except (ValueError, OSError) as exc:
            print(f"Error recording design approval: {exc}", file=sys.stderr)
            return 1

    if args.set_active_change:
        set_active_change(repo_root, args.set_active_change)
        output_result({"active_change_id": args.set_active_change}, [f"Active change set to: {args.set_active_change}"])
        return 0

    if args.sync_state:
        synced = sync_ledger_from_workspace(repo_root, target_change_id=args.change)
        output_result(synced, ["Successfully synchronized .agentflow/state.json from workspace artifacts."])
        return 0

    if args.generate_trailers:
        try:
            trailers = generate_gate_trailers(repo_root, change_id=args.change)
            output_result({"trailers": trailers}, trailers)
            return 0
        except ValueError as exc:
            print(f"Error generating trailers: {exc}", file=sys.stderr)
            return 1

    if args.record_review:
        try:
            res = record_review_to_ledger(repo_root, args.record_review, change_id=args.change)
            verdict = res.get("evidence", {}).get("review", {}).get("verdict")
            rev = res.get("revision_counter", 0)
            output_result(res, [f"Review recorded for change '{res.get('change_id')}' (verdict: {verdict}, rev: r{rev})"])
            return 0
        except Exception as e:
            print(f"Error recording review: {e}", file=sys.stderr)
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
            target_change = args.change or _ledger_store.get_active_change(repo_root)
            if not target_change:
                packages = _spec_repo.inspect_openspec(repo_root)
                if len(packages) == 1:
                    target_change = packages[0]["change"]
            res = create_checkpoint(
                repo_root,
                args.checkpoint,
                change=target_change,
                create_git_tag=args.create_git_tag,
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
            if res.get("provider"):
                output_result(res, banner(f"SDD DELIVERY RECORDED: {res.get('change')}", [
                    f"Provider: {res['provider']}", f"Finalization report: {res['finalization']}"]))
                return 0
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
        report = data.get("review_report")
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
