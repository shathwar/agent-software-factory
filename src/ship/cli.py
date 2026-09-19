"""Unified CLI dispatcher for Ship: Autonomous Engineering Lifecycle & MCP Server."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

from ship.lifecycle.engine import LifecycleEngine, format_summary
from ship.lifecycle.ledger import FileLedgerStore, record_test_run_to_ledger, record_review_to_ledger, record_turn_to_ledger, read_ledger_file
from ship.lifecycle.checkpoints import CheckpointManager
from ship.lifecycle.config import ShipConfigManager
from ship.lifecycle.evidence import design_fingerprint
from ship.lifecycle.vcs import GitClient

compute_working_tree_fingerprint = GitClient().compute_working_tree_fingerprint
from ship.lifecycle.trailers import CommitTrailerGenerator
from ship.lifecycle.operations import doctor, migrate_state, init_agentflow
from ship.lifecycle.paths import repository_path
from ship.lifecycle.turns import get_next_turn_contract, format_turn_contract, format_turns_log

VERSION = "1.0.0"

HELP_BANNER = f"""AgentFlow SDLC CLI v{VERSION} — Autonomous Engineering Lifecycle & MCP Server

USAGE:
  agentflow <command> [options]
  ship <command> [options]

CORE SUBCOMMANDS:
  agentflow init [--profile standard|small-fix|high-risk] [--path <dir>]
      Initialize an AgentFlow workflow in repository (.agentflow.json and .gitignore).
  agentflow status [--change <id>] [--path <dir>]
      Evaluate gate readiness (exits 0=ready, 1=blocked, 2=rollback required).
  agentflow turn [--change <id>] [--format text|json]
      Derive the deterministic Turn Contract for the active change.
  agentflow checkpoint <gate> [--change <id>]
      Create an immutable git ref and receipt for design or implementation.
  agentflow rollback <gate> [--change <id>]
      Safely revert workspace to a prior checkpoint with backup preservation.
  agentflow approve <change> <fingerprint> [--approved-by <id>]
      Record external design specification approval.
  agentflow archive <change> [--force]
      Apply delta specs and archive completed change package to openspec/archive/.
  agentflow trailers <change>
      Generate RFC 5133 Git commit trailers based on current verified evidence.
  agentflow verify [change] [--tier execution|grounding|mutation|coverage|all] [--all]
      Run independent multi-tier verification eliminating circular trust.
  agentflow resume <change>
      Clear non-convergence halt blockers and resume autonomous workflow execution.
  agentflow lease <claim|heartbeat|release|handoff|list|reap> [options]
      Multi-agent coordination: claim exclusive task leases, manage TTLs, and hand off tasks.
  agentflow session <start|end|list> [options]
      Manage agent sessions and track attributable execution lifecycles.
  agentflow identity <register|list> [options]
      Register and inspect agent identities and role assignments.
  agentflow capability <grant|revoke|list|check> [options]
      Evaluate capability policy for trusted host enforcement.
  agentflow approval <request|approve|grant-direct|reject|revoke|list> [options]
      Manage durable authorization objects and scope-limited human approvals.
  agentflow events <list|tail|verify> [options]
      Forensic audit trail: append-only cryptographic hash-chained execution event stream.
  agentflow budget <show|set|record|check> [options]
      Resource & Budget Governor: track and enforce ceilings across 7 economic dimensions.
  agentflow benchmark [--suite all|<category>] [--iterations N] [--json]
      System evaluation harness: run repeatable benchmark scenarios measuring AgentFlow itself.
  agentflow doctor [--path <dir>]
      Run preflight diagnostics (runtime, git, skill directories, ledger).

SPECIALIST TOOLS:
  ship tdd [--strict] [--trim-receipt <file>]
      Audit test-driven development parity, test classifications, and anti-patterns.
  ship simplify [--strict] [paths...]
      Scan codebase for technical debt markers (TODO(simplify):) and ceilings.
  ship spike --cmd "<command>" [--iterations N] [--workers W]
      Run statistical benchmark trials measuring latency percentiles and RPS.
  ship review validate <report.json>
      Validate review report structure against the 12-field finding schema contract.

SERVER:
  ship mcp
      Launch the zero-dependency stdio Model Context Protocol (MCP) server.

PROVENANCE:
  ship record-turn <payload_or_path> [--change <id>] [--harness <id>]
      Record a specialist turn into the ledger provenance history.
  ship turns [--change <id>]
      Display the turn-level provenance audit trail.

LEGACY FLAGS (100% Backward Compatible):
  ship --status-check | --next-turn | --checkpoint <gate> | --rollback <gate>
  ship --approve-design <digest> --change <id> --approved-by <id>
  ship --doctor | --migrate-state | --generate-trailers | --version
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and evaluate repository against the engineering lifecycle.",
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="Show this help message and exit.")
    parser.add_argument("-v", "--version", action="store_true", help="Print the installed suite version.")
    parser.add_argument("--path", default=".", help="Path to repository root (default: current directory).")
    parser.add_argument("--change", dest="change", default=None, help="Target a specific change ID (e.g. feature-login).")
    parser.add_argument("--config", default=None, help="Path to custom .agentflow.json configuration.")
    parser.add_argument("--checkpoint", default=None, metavar="GATE", help="Record a git ref and receipt checkpoint.")
    parser.add_argument("--rollback", default=None, metavar="GATE", help="Safely rollback working state to gate checkpoint.")
    parser.add_argument("--status-check", action="store_true", help="Exit with 0 if ready, 1 if blocked, 2 if rollback required.")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format (default: text).")
    parser.add_argument("--json", action="store_true", help="Shortcut for --format json.")
    parser.add_argument("--archive", nargs="?", const="", default=None, metavar="CHANGE", help="Archive change package.")
    parser.add_argument("--force", action="store_true", help="Force archive even if checks fail.")
    parser.add_argument("--fingerprint", action="store_true", help="Print working tree fingerprint SHA-256 and exit.")
    parser.add_argument("--create-git-tag", action="store_true", help="Also create git tag in refs/tags/.")
    parser.add_argument("--set-active-change", default=None, metavar="CHANGE_ID", help="Set active change ID in ledger.")
    parser.add_argument("--sync-state", action="store_true", help="Force re-sync ledger from workspace.")
    parser.add_argument("--record-review", default=None, metavar="REPORT_JSON", help="Record review report into ledger.")
    parser.add_argument("--record-tests", default=None, metavar="TEST_DATA", help="Record test results into ledger.")
    parser.add_argument("--generate-trailers", action="store_true", help="Generate RFC 5133 commit trailers.")
    parser.add_argument("--design-fingerprint", action="store_true", help="Print design digest for --change.")
    parser.add_argument("--approve-design", metavar="SHA256", help="Record design approval; requires --change and --approved-by.")
    parser.add_argument("--approved-by", help="Identity supplied by approving user.")
    parser.add_argument("--next-turn", action="store_true", help="Output deterministic Turn Contract.")
    parser.add_argument("--record-turn", default=None, metavar="TURN_JSON_OR_PATH", help="Record turn provenance.")
    parser.add_argument("--turns", "--provenance", action="store_true", dest="show_turns", help="Display turn provenance audit.")
    parser.add_argument("--harness", default=None, help="Harness identifier for recorded turn.")
    parser.add_argument("--doctor", action="store_true", help="Check local installation and workspace.")
    parser.add_argument("--migrate-state", action="store_true", help="Migrate legacy versionless ledger to v1.")
    parser.add_argument("--verify", action="store_true", help="Run independent multi-tier verification.")
    parser.add_argument("--tier", choices=["execution", "grounding", "mutation", "coverage", "all"], default=None, help="Specific verification tier.")
    parser.add_argument("--all", dest="verify_all", action="store_true", help="Verify all tiers.")
    parser.add_argument("--resume", nargs="?", const="", default=None, metavar="CHANGE", help="Clear non-convergence halt blockers and resume workflow.")
    return parser


def run_lifecycle(argv: Sequence[str]) -> int:
    parser = build_parser()
    args, unknown = parser.parse_known_args(argv)

    if args.json:
        args.format = "json"

    if args.help:
        print(HELP_BANNER)
        return 0

    if args.version:
        print(VERSION)
        return 0

    repo_root = Path(args.path).resolve()
    engine = LifecycleEngine()
    ledger_store = FileLedgerStore()

    def output_result(payload: Any, text_lines: Optional[Sequence[str]] = None) -> None:
        if args.format == "json":
            print(json.dumps(payload, indent=2))
        elif text_lines is not None:
            for l in text_lines:
                print(l)

    def banner(title: str, lines: Sequence[str]) -> List[str]:
        bar = "═" * 69
        return [bar, f" {title}", bar, *lines, bar]

    if args.doctor:
        res = doctor(repo_root)
        output_result(res, [f"Ship {res['version']}"] + [f"{'OK' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}" for c in res['checks']])
        return 0 if res["ok"] else 1

    if args.migrate_state:
        try:
            m_res = migrate_state(repo_root)
            output_result(m_res, [f"State migration: {m_res['message']}"])
            return 0 if m_res["ok"] else 1
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.show_turns:
        turns = ledger_store.get_turns(repo_root, change_id=args.change)
        output_result(turns, None if args.format == "json" else [format_turns_log(turns, change_id=args.change)])
        return 0

    if args.record_turn:
        try:
            raw = args.record_turn.strip()
            t_payload = json.loads(raw) if raw.startswith(("{", "[")) else json.loads(Path(raw).read_text(encoding="utf-8"))
            if not isinstance(t_payload, dict):
                raise ValueError("Turn record payload must be a JSON object.")
        except Exception as exc:
            print(f"Error parsing turn record: {exc}", file=sys.stderr)
            return 1
        if args.harness and "harness" not in t_payload:
            t_payload["harness"] = args.harness
        try:
            rec = ledger_store.record_turn(repo_root, t_payload, change_id=args.change, sync_fn=engine.sync_ledger)
            output_result(rec, [f"Recorded turn for change '{rec['change_id']}'"])
            return 0
        except ValueError as exc:
            print(f"Error recording turn: {exc}", file=sys.stderr)
            return 1

    if args.next_turn:
        try:
            contract = engine.get_next_turn_contract(repo_root, target_change=args.change, config_path=args.config)
            output_result(contract.to_dict(), [format_turn_contract(contract)])
            return 0
        except ValueError as exc:
            if args.format == "json":
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.design_fingerprint:
        if not args.change:
            print("Error: --design-fingerprint requires --change <ID>", file=sys.stderr)
            return 1
        fp = design_fingerprint(repo_root, args.change)
        output_result({"change": args.change, "fingerprint": fp}, [fp])
        return 0

    if args.approve_design:
        if not args.change:
            print("Error: --approve-design requires --change <ID>", file=sys.stderr)
            return 1
        if not args.approved_by:
            print("Error: --approve-design requires --approved-by <identity>", file=sys.stderr)
            return 1
        try:
            a_res = ledger_store.approve_design(repo_root, args.change, args.approve_design, args.approved_by)
            output_result(a_res, [f"Design approved for {args.change} ({args.approve_design[:12]}...) by {args.approved_by}"])
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.record_tests:
        val = args.record_tests.strip().lower()
        if val in ("pass", "passed", "true", "1"):
            t_data: Dict[str, Any] = {"passed": True}
        elif val in ("fail", "failed", "false", "0"):
            t_data = {"passed": False}
        else:
            p = Path(args.record_tests)
            if p.is_file():
                try:
                    t_data = json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    print(f"Error reading test json: {exc}", file=sys.stderr)
                    return 1
            else:
                print(f"Error: --record-tests accepts pass/fail or a path to a JSON file.", file=sys.stderr)
                return 1
        res_entry = record_test_run_to_ledger(repo_root, t_data, change_id=args.change)
        output_result(res_entry, [f"Recorded test results for change '{args.change or 'active'}': passed={t_data.get('passed')}"])
        return 0

    if args.record_review:
        try:
            res_entry = record_review_to_ledger(repo_root, args.record_review, change_id=args.change)
            output_result(res_entry, [f"Recorded review report from {args.record_review}"])
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.sync_state:
        res_ledger = engine.sync_ledger(repo_root, active_change_id=args.change)
        output_result(res_ledger, ["State ledger synchronized from workspace."])
        return 0

    if args.verify:
        tiers = ["all"] if args.verify_all or args.tier == "all" else ([args.tier] if args.tier else ["grounding", "execution", "coverage"])
        try:
            records = engine.verify_change(
                repo_root,
                change=args.change,
                tiers=tiers,
                record_to_ledger=True,
            )
            from ship.lifecycle.verification import format_verification_summary
            if args.format == "json":
                payload = {k: (v.to_dict() if hasattr(v, "to_dict") else v) for k, v in records.items()}
                print(json.dumps(payload, indent=2))
            else:
                print(format_verification_summary(records, change=args.change or ""))
            any_failed = any(getattr(r, "verdict", None) == "NOT_VERIFIED" or (isinstance(r, dict) and r.get("verdict") == "NOT_VERIFIED") for r in records.values())
            return 1 if any_failed else 0
        except Exception as exc:
            if args.format == "json":
                print(json.dumps({"error": str(exc)}, indent=2))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.set_active_change:
        ledger_store.set_active_change(repo_root, args.set_active_change)
        output_result({"active_change_id": args.set_active_change}, [f"Active change set to '{args.set_active_change}'."])
        return 0

    if args.resume is not None:
        cid = (args.resume.strip() if args.resume else "") or args.change or ledger_store.get_active_change(repo_root) or "default"
        try:
            from .lifecycle.recovery import RecoveryManager
            decision = RecoveryManager(repo_root).reconcile_and_recover(cid)
            res_entry = ledger_store.load(repo_root, auto_sync=False).get("changes", {}).get(cid, {})
            msg = [
                f"Halt blocker cleared and autonomy resumed for change '{cid}'.",
                f"Recovery strategy: {decision.strategy}",
                f"Restored phase: {decision.restored_phase}",
                f"Next step: {decision.next_step}",
            ]
            if decision.reconciled_items:
                msg.append(f"Reconciled items: {'; '.join(decision.reconciled_items)}")
            output_result(res_entry, msg)
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.fingerprint:
        tfp = compute_working_tree_fingerprint(repo_root)
        output_result({"working_tree_fingerprint": tfp}, [tfp])
        return 0

    if args.checkpoint:
        try:
            mgr = CheckpointManager(GitClient(), ShipConfigManager, ledger_store)
            res = mgr.create_checkpoint(repo_root, args.checkpoint, change=args.change, create_git_tag=args.create_git_tag)
            output_result(res, [f"Created checkpoint for {args.checkpoint}: {res.get('ref')}"])
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.rollback:
        try:
            mgr = CheckpointManager(GitClient(), ShipConfigManager, ledger_store)
            res = mgr.perform_rollback(repo_root, args.rollback, change=args.change, force=args.force)
            output_result(res, [res.get("message") or f"Rolled back {args.rollback} for {args.change or 'active change'}"])
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.status_check:
        try:
            evaluation = engine.evaluate_repository(repo_root, target_change=args.change, config_path=args.config)
        except ValueError as exc:
            if args.format == "json":
                print(json.dumps({"ready": False, "exit_code": 1, "error": str(exc)}, indent=2))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return 1
        state_key = evaluation.get("state_key")
        ready = (state_key == "DELIVERY_READY")
        blockers = (evaluation.get("active_change") or {}).get("blockers", [])
        report = evaluation.get("review_report")

        exit_code = 0 if ready else 1
        if not ready:
            if any("invariant" in b.lower() for b in blockers):
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

        reasons = []
        if not ready:
            if evaluation.get("next_action"):
                reasons.append(evaluation["next_action"])
            if blockers:
                reasons.extend(blockers)

        res_dict = {
            "ready": ready,
            "exit_code": exit_code,
            "gate": evaluation.get("gate"),
            "state_key": state_key,
            "reasons": reasons,
            "blockers": blockers,
            "active_change": evaluation.get("target_change"),
        }
        if args.format == "json":
            print(json.dumps(res_dict, indent=2))
        else:
            cid_disp = evaluation.get("target_change") or "none"
            gate_disp = evaluation.get("gate", "unknown")
            header = f"┌─ AgentFlow Workflow: {cid_disp} "
            header += "─" * max(0, 60 - len(header)) + "┐"
            print(header)
            print(f"│ Gate: {gate_disp:<18} State: {state_key:<27} │")
            pkgs = evaluation.get("openspec_packages", [])
            active_pkg = next((p for p in pkgs if p.get("change") == cid_disp), None) if pkgs else None
            if active_pkg and active_pkg.get("has_tasks"):
                comp = active_pkg.get("completed_tasks", 0)
                tot = active_pkg.get("total_tasks", 0)
                print(f"│ Tasks: [{comp}/{tot}] complete{' ' * max(0, 42 - len(f'{comp}/{tot}'))} │")
            print("└" + "─" * 58 + "┘")
            if ready:
                print("✅ READY: Repository satisfies all lifecycle delivery gates.")
            else:
                print(f"❌ BLOCKED (Exit code {exit_code}):")
                for r in reasons:
                    print(f"  • {r}")
                if blockers and not any(b in reasons for b in blockers):
                    print("Active blockers:")
                    for b in blockers:
                        print(f"  • {b}")
        return exit_code

    if args.archive is not None:
        target = args.archive if args.archive != "" else args.change
        if not target:
            active = ledger_store.get_active_change(repo_root)
            if active:
                target = active
            else:
                pkgs = engine.spec_repo.inspect_openspec(repo_root)
                if len(pkgs) == 1:
                    target = pkgs[0]["change"]
        if not target:
            print("Error: specify --archive <change> or --change <change>", file=sys.stderr)
            return 1
        try:
            res_archive = engine.archive_change(repo_root, target, force=args.force)
            trailers = res_archive.get("trailers", [])
            a_path = res_archive.get("archived_path", "")
            output_result({"trailers": trailers, "archive_path": str(a_path)}, [f"Archived {target} to {a_path}"] + trailers)
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.generate_trailers:
        target = args.change or ledger_store.get_active_change(repo_root)
        if not target:
            pkgs = engine.spec_repo.inspect_openspec(repo_root)
            if len(pkgs) == 1:
                target = pkgs[0]["change"]
        if not target:
            print("Error: specify --change <ID> or set an active change", file=sys.stderr)
            return 1
        try:
            generator = CommitTrailerGenerator()
            trailers = generator.generate_trailers(repo_root, target_change=target)
            output_result({"trailers": trailers}, trailers)
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    # Default: Full Lifecycle Evaluation Banner
    try:
        eval_dict = engine.evaluate_repository(repo_root, target_change=args.change, config_path=args.config)
    except Exception as exc:
        print(f"Error evaluating repository: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(eval_dict, indent=2))
        return 0

    text_lines = banner("ENGINEERING LIFECYCLE EVALUATION", format_summary(eval_dict))
    for l in text_lines:
        print(l)
    return 0


def run_lease_cli(argv: Sequence[str]) -> int:
    """Handle multi-agent task lease coordination CLI commands."""
    if not argv or argv[0] in ("-h", "--help"):
        print("""Usage: agentflow lease <action> [options]

Actions:
  claim <task_id> --owner <agent_id> [--files <f1,f2>] [--ttl <seconds>]
  heartbeat <task_id> --token <lease_token>
  release <task_id> --token <lease_token> [--completed]
  handoff <task_id> --from <agent_id> --to <agent_id> --token <token> [--reason <str>]
  list [change] [--active] [--json]
  reap [change]
""")
        return 0

    action = argv[0].lower()
    rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow lease {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    if action == "claim":
        parser.add_argument("task_id", nargs="?", default=None, help="Task ID to lease (e.g. 1.1 or T1)")
        parser.add_argument("--task", dest="task_opt", default=None, help="Task ID")
        parser.add_argument("--owner", required=True, help="Worker / agent identity claiming the task")
        parser.add_argument("--files", default="", help="Comma-separated target files")
        parser.add_argument("--ttl", type=int, default=None, help="Lease TTL duration in seconds")
        parser.add_argument("--session", default=None, help="Active agent session ID")
        parser.add_argument("--runtime", default=None, help="Agent runtime environment")
        parser.add_argument("--model", default=None, help="Agent model identifier")
        parser.add_argument("--role", default=None, help="Agent role (e.g. MAKER, CHECKER, SPECIALIST)")
        parser.add_argument("--parent-agent", dest="parent_agent", default=None, help="Parent agent ID for delegated subagents")
        args = parser.parse_args(rem)
        task_id = args.task_opt or args.task_id
        if not task_id:
            parser.error("task_id is required (positional or via --task)")
        target_files = [f.strip() for f in args.files.split(",") if f.strip()]
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        res = manager.claim_task(
            task_id,
            args.owner,
            change_id=args.change,
            target_files=target_files,
            ttl_seconds=args.ttl,
            session_id=args.session,
            runtime=args.runtime,
            model=args.model,
            role=args.role,
            parent_agent_id=args.parent_agent,
        )
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        elif res.success and res.lease:
            print(f"✅ Lease acquired for task '{task_id}' by '{args.owner}'")
            print(f"  • Lease Token : {res.lease.lease_token}")
            print(f"  • Expires At  : {res.lease.expires_at} (TTL: {res.lease.ttl_seconds}s)")
            if res.lease.session_id:
                print(f"  • Session ID  : {res.lease.session_id}")
            if res.lease.target_files:
                print(f"  • Files       : {', '.join(res.lease.target_files)}")
        else:
            print(f"❌ Failed to claim task '{task_id}': {res.error}", file=sys.stderr)
        return 0 if res.success else 1

    elif action == "heartbeat":
        parser.add_argument("task_id", nargs="?", default=None, help="Task ID being heartbeated")
        parser.add_argument("--task", dest="task_opt", default=None, help="Task ID")
        parser.add_argument("--token", required=True, help="Active lease token")
        parser.add_argument("--ttl", type=int, default=None, help="Extended TTL in seconds")
        args = parser.parse_args(rem)
        task_id = args.task_opt or args.task_id
        if not task_id:
            parser.error("task_id is required (positional or via --task)")
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        res = manager.heartbeat_lease(task_id, args.token, change_id=args.change, ttl_seconds=args.ttl)
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        elif res.success and res.lease:
            print(f"💓 Heartbeat received for task '{task_id}'. Renewed until {res.lease.expires_at}.")
        else:
            print(f"❌ Heartbeat rejected: {res.error}", file=sys.stderr)
        return 0 if res.success else 1

    elif action == "release":
        parser.add_argument("task_id", nargs="?", default=None, help="Task ID being released")
        parser.add_argument("--task", dest="task_opt", default=None, help="Task ID")
        parser.add_argument("--token", required=True, help="Active lease token")
        parser.add_argument("--completed", action="store_true", help="Mark task completed [x] in tasks.md")
        parser.add_argument("--session", default=None, help="Active agent session ID")
        parser.add_argument("--runtime", default=None, help="Agent runtime environment")
        parser.add_argument("--model", default=None, help="Agent model identifier")
        args = parser.parse_args(rem)
        task_id = args.task_opt or args.task_id
        if not task_id:
            parser.error("task_id is required (positional or via --task)")
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        res = manager.release_task(
            task_id,
            args.token,
            change_id=args.change,
            completed=args.completed,
            session_id=args.session,
            runtime=args.runtime,
            model=args.model,
        )
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        elif res.success:
            status_str = "completed and released" if args.completed else "released"
            print(f"✅ Task '{task_id}' {status_str}.")
        else:
            print(f"❌ Failed to release task: {res.error}", file=sys.stderr)
        return 0 if res.success else 1

    elif action == "handoff":
        parser.add_argument("task_id", nargs="?", default=None, help="Task ID being handed off")
        parser.add_argument("--task", dest="task_opt", default=None, help="Task ID")
        parser.add_argument("--from", dest="from_owner", required=True, help="Current lease owner")
        parser.add_argument("--to", dest="to_owner", required=True, help="New lease owner")
        parser.add_argument("--token", required=True, help="Current lease token")
        parser.add_argument("--reason", default="", help="Reason for handoff")
        parser.add_argument("--notes", default="", help="Handoff notes")
        parser.add_argument("--checklist", default="", help="Comma-separated checklist items")
        parser.add_argument("--session", default=None, help="Active agent session ID")
        parser.add_argument("--runtime", default=None, help="Agent runtime environment")
        parser.add_argument("--model", default=None, help="Agent model identifier")
        args = parser.parse_args(rem)
        task_id = args.task_opt or args.task_id
        if not task_id:
            parser.error("task_id is required (positional or via --task)")
        checklist = [c.strip() for c in args.checklist.split(",") if c.strip()]
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        res = manager.handoff_task(
            task_id=task_id,
            from_owner=args.from_owner,
            to_owner=args.to_owner,
            lease_token=args.token,
            change_id=args.change,
            reason=args.reason or args.notes,
            verification_checklist=checklist,
            notes=args.notes or args.reason,
            session_id=args.session,
            runtime=args.runtime,
            model=args.model,
        )
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        elif res.success and res.lease:
            print(f"🤝 Task '{task_id}' handed off from '{args.from_owner}' -> '{args.to_owner}'")
            print(f"  • New Lease Token : {res.lease.lease_token}")
            print(f"  • Expires At      : {res.lease.expires_at}")
        else:
            print(f"❌ Handoff failed: {res.error}", file=sys.stderr)
        return 0 if res.success else 1

    elif action == "list":
        parser.add_argument("target_change", nargs="?", default=None, help="Target change ID")
        parser.add_argument("--active", action="store_true", help="Show active unexpired leases only")
        args = parser.parse_args(rem)
        cid = args.target_change or args.change
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        leases = manager.list_leases(change_id=cid, active_only=args.active)
        if args.json:
            print(json.dumps([l.to_dict() for l in leases], indent=2))
        else:
            print(f"📋 Task Leases for change '{cid or 'active'}':")
            if not leases:
                print("  (No leases recorded)")
            for l in leases:
                files_str = f" [files: {', '.join(l.target_files)}]" if l.target_files else ""
                print(f"  • Task {l.task_id:6s} | Owner: {l.owner_id:15s} | Status: {l.status:10s} | Expires: {l.expires_at}{files_str}")
        return 0

    elif action == "reap":
        parser.add_argument("target_change", nargs="?", default=None, help="Target change ID")
        args = parser.parse_args(rem)
        cid = args.target_change or args.change
        from .lifecycle.coordination import CoordinationManager
        manager = CoordinationManager(Path(args.path).resolve())
        reaped = manager.reap_stale_leases(change_id=cid)
        if args.json:
            print(json.dumps([l.to_dict() for l in reaped], indent=2))
        else:
            if reaped:
                print(f"🧹 Reaped {len(reaped)} stale lease(s):")
                for l in reaped:
                    print(f"  • Task '{l.task_id}' (owner: '{l.owner_id}') expired at {l.expires_at}")
            else:
                print("🧹 No stale leases found.")
        return 0

    else:
        print(f"Unknown lease action: '{action}'. See 'agentflow lease --help'.", file=sys.stderr)
        return 1


def run_session_cli(argv: Sequence[str]) -> int:
    """Handle agent execution session lifecycle CLI commands."""
    if not argv or argv[0] in ("-h", "--help"):
        print("""Usage: agentflow session <action> [options]

Actions:
  start <agent_id> [--role <role>] [--model <model>] [--runtime <runtime>] [--skill <skill>]
  end <session_id> [--status <status>]
  list [change] [--active] [--json]
""")
        return 0

    action = argv[0].lower()
    rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow session {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    if action == "start":
        parser.add_argument("agent_id", nargs="?", default=None, help="Agent ID principal starting session")
        parser.add_argument("--agent", dest="agent_opt", default=None, help="Agent ID principal")
        parser.add_argument("--role", default="maker", help="Agent role (maker, checker, architect, etc.)")
        parser.add_argument("--model", default="unknown", help="Model identifier")
        parser.add_argument("--runtime", default="cli", help="Agent runtime environment")
        parser.add_argument("--skill", default="", help="Active skill")
        parser.add_argument("--skill-version", default="1.0.0", help="Active skill version")
        parser.add_argument("--parent-session", dest="parent_session", default=None, help="Parent session ID")
        args = parser.parse_args(rem)
        agent_id = args.agent_opt or args.agent_id
        if not agent_id:
            parser.error("agent_id is required (positional or via --agent)")
        from .lifecycle.provenance import ProvenanceManager
        manager = ProvenanceManager(Path(args.path).resolve())
        sess = manager.start_session(
            agent_id=agent_id,
            role=args.role,
            change_id=args.change,
            runtime=args.runtime,
            model=args.model,
            skill=args.skill,
            skill_version=args.skill_version,
            parent_session_id=args.parent_session,
        )
        if args.json:
            print(json.dumps(sess.to_dict(), indent=2))
        else:
            print(f"🚀 Started session '{sess.session_id}' for agent '{agent_id}'")
            print(f"  • Role    : {sess.role}")
            print(f"  • Runtime : {sess.runtime} ({sess.model})")
            if sess.skill:
                print(f"  • Skill   : {sess.skill}@{sess.skill_version}")
        return 0

    elif action == "end":
        parser.add_argument("session_id", nargs="?", default=None, help="Session ID to end")
        parser.add_argument("--session", dest="session_opt", default=None, help="Session ID to end")
        parser.add_argument("--status", default="COMPLETED", help="Final status (COMPLETED, FAILED, CANCELLED)")
        args = parser.parse_args(rem)
        session_id = args.session_opt or args.session_id
        if not session_id:
            parser.error("session_id is required (positional or via --session)")
        from .lifecycle.provenance import ProvenanceManager
        manager = ProvenanceManager(Path(args.path).resolve())
        sess = manager.end_session(session_id, change_id=args.change, status=args.status)
        if not sess:
            print(f"❌ Session '{session_id}' not found.", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(sess.to_dict(), indent=2))
        else:
            print(f"🛑 Ended session '{session_id}' (status: {sess.status}).")
        return 0

    elif action == "list":
        parser.add_argument("target_change", nargs="?", default=None, help="Target change ID")
        parser.add_argument("--active", action="store_true", help="Show active sessions only")
        args = parser.parse_args(rem)
        cid = args.target_change or args.change
        from .lifecycle.provenance import ProvenanceManager
        manager = ProvenanceManager(Path(args.path).resolve())
        sessions = manager.list_sessions(change_id=cid, active_only=args.active)
        if args.json:
            print(json.dumps([s.to_dict() for s in sessions], indent=2))
        else:
            print(f"📋 Agent Sessions for change '{cid or 'active'}':")
            if not sessions:
                print("  (No sessions recorded)")
            for s in sessions:
                ended_str = f" | Ended: {s.ended_at}" if s.ended_at else ""
                print(f"  • {s.session_id} | Agent: {s.agent_id:15s} | Role: {s.role:10s} | Status: {s.status:10s}{ended_str}")
        return 0

    else:
        print(f"Unknown session action: '{action}'. See 'agentflow session --help'.", file=sys.stderr)
        return 1


def run_identity_cli(argv: Sequence[str]) -> int:
    """Handle agent identity principal registration and discovery CLI commands."""
    if not argv or argv[0] in ("-h", "--help"):
        print("""Usage: agentflow identity <action> [options]

Actions:
  register <agent_id> [--role <role>] [--runtime <runtime>] [--model <model>] [--parent <agent_id>]
  list [change] [--json]
""")
        return 0

    action = argv[0].lower()
    rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow identity {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    if action == "register":
        parser.add_argument("agent_id", nargs="?", default=None, help="Agent identity ID to register")
        parser.add_argument("--agent", dest="agent_opt", default=None, help="Agent identity ID")
        parser.add_argument("--role", default="maker", help="Agent role (maker, checker, architect, etc.)")
        parser.add_argument("--runtime", default="cli", help="Agent runtime environment")
        parser.add_argument("--model", default="unknown", help="Model identifier")
        parser.add_argument("--parent", dest="parent_agent", default=None, help="Parent agent ID")
        args = parser.parse_args(rem)
        agent_id = args.agent_opt or args.agent_id
        if not agent_id:
            parser.error("agent_id is required (positional or via --agent)")
        from .lifecycle.provenance import ProvenanceManager
        manager = ProvenanceManager(Path(args.path).resolve())
        ident = manager.register_identity(
            agent_id=agent_id,
            role=args.role,
            runtime=args.runtime,
            model=args.model,
            parent_agent_id=args.parent_agent,
            change_id=args.change,
        )
        if args.json:
            print(json.dumps(ident.to_dict(), indent=2))
        else:
            print(f"👤 Registered agent identity '{ident.agent_id}' (role: {ident.role}, runtime: {ident.runtime}, model: {ident.model})")
        return 0

    elif action == "list":
        parser.add_argument("target_change", nargs="?", default=None, help="Target change ID")
        args = parser.parse_args(rem)
        cid = args.target_change or args.change
        from .lifecycle.provenance import ProvenanceManager
        manager = ProvenanceManager(Path(args.path).resolve())
        identities = manager.list_identities(change_id=cid)
        if args.json:
            print(json.dumps([i.to_dict() for i in identities], indent=2))
        else:
            print(f"📋 Registered Agent Principals for change '{cid or 'active'}':")
            if not identities:
                print("  (No identities registered)")
            for i in identities:
                parent_str = f" (parent: {i.parent_agent_id})" if i.parent_agent_id else ""
                print(f"  • {i.agent_id:15s} | Role: {i.role:10s} | Runtime: {i.runtime:12s} | Model: {i.model}{parent_str}")
        return 0

    else:
        print(f"Unknown identity action: '{action}'. See 'agentflow identity --help'.", file=sys.stderr)
        return 1


def run_capability_cli(argv: Sequence[str]) -> int:
    """Handle fine-grained object capability and Ring authorization CLI commands."""
    if not argv or argv[0] in ("-h", "--help"):
        print("""Usage: agentflow capability <action> [options]

Actions:
  grant <agent_id> --op <operation> --target <target> [--task <id>] [--ttl <sec>] [--approval <ref>]
  revoke <capability_id> [--reason <str>]
  list [change] [--agent <id>] [--active] [--json]
  check <agent_id> --op <operation> --target <target> [--task <id>] [--token <token>] [--json]
""")
        return 0

    action = argv[0].lower()
    rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow capability {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    if action == "grant":
        parser.add_argument("agent_id", nargs="?", default=None, help="Agent ID holding capability")
        parser.add_argument("--agent", dest="agent_opt", default=None, help="Agent ID")
        parser.add_argument("--op", "--operation", dest="operation", default=None, help="Capability operation (READ, WRITE, DELETE, EXECUTE, GIT, NETWORK, NETWORK_READ, NETWORK_WRITE, SECRET_READ, CLOUD_MUTATE, GITHUB_WRITE)")
        parser.add_argument("--target", default=None, help="Target resource path, glob, or command pattern")
        parser.add_argument("--task", dest="task_id", default=None, help="Bound task ID (e.g. 1.1)")
        parser.add_argument("--session", dest="session_id", default=None, help="Bound session ID")
        parser.add_argument("--ttl", type=int, default=None, help="TTL duration in seconds")
        parser.add_argument("--approval", dest="approval_ref", default="", help="Authorization reference (e.g. adr:0002, lease:tok-123)")
        parser.add_argument("--from-approval", dest="from_approval", default=None, help="Grant capability directly from durable authorization ID (e.g. appr-123)")
        args = parser.parse_args(rem)
        from .lifecycle.capabilities import CapabilityManager
        manager = CapabilityManager(Path(args.path).resolve())

        if args.from_approval:
            cap = manager.grant_from_approval(
                approval_id=args.from_approval,
                target=args.target,
                change_id=args.change,
                task_id=args.task_id,
                session_id=args.session_id,
                ttl_seconds=args.ttl,
            )
        else:
            agent_id = args.agent_opt or args.agent_id
            if not agent_id:
                parser.error("agent_id is required (positional or via --agent)")
            if not args.operation:
                parser.error("--op/--operation is required")
            if not args.target:
                parser.error("--target is required")
            cap = manager.grant_capability(
                agent_id=agent_id,
                operation=args.operation,
                target=args.target,
                change_id=args.change,
                task_id=args.task_id,
                session_id=args.session_id,
                ttl_seconds=args.ttl,
                approval_ref=args.approval_ref,
            )
        if args.json:
            print(json.dumps(cap.to_dict(), indent=2))
        else:
            ring = manager.classify_target_ring(cap.target, cap.operation)
            print(f"🔑 Granted capability '{cap.capability_id}' to agent '{cap.agent_id}'")
            print(f"  • Operation : {cap.operation}")
            print(f"  • Target    : {cap.target} ({ring.value})")
            if cap.task_id:
                print(f"  • Task      : {cap.task_id}")
            if cap.expires_at:
                print(f"  • Expires   : {cap.expires_at}")
            if cap.approval_ref:
                print(f"  • Approval  : {cap.approval_ref}")
        return 0

    elif action == "revoke":
        parser.add_argument("capability_id", nargs="?", default=None, help="Capability ID to revoke")
        parser.add_argument("--cap", dest="cap_opt", default=None, help="Capability ID")
        parser.add_argument("--reason", default="", help="Revocation reason")
        args = parser.parse_args(rem)
        cap_id = args.cap_opt or args.capability_id
        if not cap_id:
            parser.error("capability_id is required (positional or via --cap)")
        from .lifecycle.capabilities import CapabilityManager
        manager = CapabilityManager(Path(args.path).resolve())
        cap = manager.revoke_capability(cap_id, change_id=args.change, reason=args.reason)
        if not cap:
            print(f"❌ Capability '{cap_id}' not found.", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(cap.to_dict(), indent=2))
        else:
            print(f"🛑 Revoked capability '{cap.capability_id}' for agent '{cap.agent_id}'.")
        return 0

    elif action == "list":
        parser.add_argument("target_change", nargs="?", default=None, help="Target change ID")
        parser.add_argument("--agent", default=None, help="Filter by agent ID")
        parser.add_argument("--active", action="store_true", help="Show active unexpired capabilities only")
        args = parser.parse_args(rem)
        cid = args.target_change or args.change
        from .lifecycle.capabilities import CapabilityManager
        manager = CapabilityManager(Path(args.path).resolve())
        caps = manager.list_capabilities(change_id=cid, agent_id=args.agent, active_only=args.active)
        if args.json:
            print(json.dumps([c.to_dict() for c in caps], indent=2))
        else:
            print(f"📋 Capabilities for change '{cid or 'active'}':")
            if not caps:
                print("  (No capabilities granted)")
            for c in caps:
                status = "REVOKED" if c.revoked else "ACTIVE"
                task_str = f" [task: {c.task_id}]" if c.task_id else ""
                print(f"  • {c.capability_id} | Agent: {c.agent_id:15s} | {c.operation:10s} -> {c.target:25s} | Status: {status}{task_str}")
        return 0

    elif action == "check":
        parser.add_argument("agent_id", nargs="?", default=None, help="Agent ID to evaluate")
        parser.add_argument("--agent", dest="agent_opt", default=None, help="Agent ID")
        parser.add_argument("--op", "--operation", dest="operation", required=True, help="Requested operation")
        parser.add_argument("--target", required=True, help="Requested target resource")
        parser.add_argument("--task", dest="task_id", default=None, help="Bound task ID")
        parser.add_argument("--session", dest="session_id", default=None, help="Bound session ID")
        parser.add_argument("--token", "--lease-token", dest="lease_token", default=None, help="Lease token")
        args = parser.parse_args(rem)
        agent_id = args.agent_opt or args.agent_id
        if not agent_id:
            parser.error("agent_id is required (positional or via --agent)")
        from .lifecycle.capabilities import CapabilityManager
        manager = CapabilityManager(Path(args.path).resolve())
        decision = manager.evaluate_access(
            agent_id=agent_id,
            operation=args.operation,
            target=args.target,
            task_id=args.task_id,
            session_id=args.session_id,
            change_id=args.change,
            lease_token=args.lease_token,
        )
        if args.json:
            print(json.dumps(decision.to_dict(), indent=2))
        else:
            verdict_icon = "🛡️ ALLOW" if decision.allowed else "⛔ DENY"
            print(f"{verdict_icon}: {decision.reason}")
            print(f"  • Ring        : {decision.ring}")
            print(f"  • Principal   : {decision.agent_id}")
            print(f"  • Operation   : {decision.operation} on '{decision.target}'")
            if decision.capability_id:
                print(f"  • Capability  : {decision.capability_id}")
            if decision.violation_code:
                print(f"  • Violation   : {decision.violation_code}")
        return 0 if decision.allowed else 1

    else:
        print(f"Unknown capability action: '{action}'. See 'agentflow capability --help'.", file=sys.stderr)
        return 1


def run_approval_cli(argv: Sequence[str]) -> int:
    """Handle durable authorization objects and approval lifecycle CLI commands."""
    if not argv or argv[0] in ("-h", "--help"):
        print("""Usage: agentflow approval <action> [options]

Actions:
  request --agent <id> --action <op> --scope <target> --reason <why>
      Create a durable authorization request (status: PENDING).
  approve <request_id> --human <name> [--ttl <sec>] [--reason <why>]
      Human supervisor reviews and approves request, creating signed DurableApproval.
  grant-direct --human <name> --agent <id> --action <op> --scope <target> [--ttl <sec>] [--reason <why>]
      Directly issue a signed DurableApproval without prior request.
  reject <request_id> --human <name> [--reason <why>]
      Reject a pending authorization request.
  revoke <approval_id> --human <name> [--reason <why>]
      Revoke an active DurableApproval object.
  list [--status <pending|approved|rejected>] [--active] [--json]
      List approval requests and authorization objects.
""")
        return 0

    action = argv[0].lower()
    rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow approval {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    from .lifecycle.approvals import ApprovalManager

    if action == "request":
        parser.add_argument("--agent", required=True, help="Agent ID requesting authorization")
        parser.add_argument("--action", required=True, help="Action/operation (e.g. SECRET_READ, NETWORK_WRITE)")
        parser.add_argument("--scope", required=True, help="Resource scope pattern (e.g. AWS_*, https://api.slack.com/*)")
        parser.add_argument("--reason", required=True, help="Justification/reason for request")
        args = parser.parse_args(rem)
        manager = ApprovalManager(Path(args.path).resolve())
        req = manager.create_request(
            agent=args.agent,
            action=args.action,
            scope=args.scope,
            reason=args.reason,
            change=args.change,
        )
        if args.json:
            print(json.dumps(req.to_dict(), indent=2))
        else:
            print(f"📝 Created approval request '{req.request_id}'")
            print(f"  • Agent   : {req.agent}")
            print(f"  • Action  : {req.action}")
            print(f"  • Scope   : {req.scope}")
            print(f"  • Status  : {req.status}")
            print(f"  • Reason  : {req.reason}")
        return 0

    elif action == "approve":
        parser.add_argument("request_id", nargs="?", default=None, help="Request ID to approve")
        parser.add_argument("--req", dest="req_opt", default=None, help="Request ID")
        parser.add_argument("--human", required=True, help="Approving human supervisor")
        parser.add_argument("--ttl", type=int, default=None, help="TTL duration in seconds")
        parser.add_argument("--reason", default="", help="Approval justification")
        args = parser.parse_args(rem)
        req_id = args.req_opt or args.request_id
        if not req_id:
            parser.error("request_id is required")
        manager = ApprovalManager(Path(args.path).resolve())
        appr = manager.approve_request(
            request_id=req_id,
            human=args.human,
            ttl_seconds=args.ttl,
            reason=args.reason,
            change_id=args.change,
        )
        if args.json:
            print(json.dumps(appr.to_dict(), indent=2))
        else:
            print(f"✅ Approved request '{req_id}' -> Issued DurableApproval '{appr.approval_id}'")
            print(f"  • Human    : {appr.human}")
            print(f"  • Agent    : {appr.agent}")
            print(f"  • Action   : {appr.action}")
            print(f"  • Scope    : {appr.scope}")
            print(f"  • Signature: {appr.signature[:16]}...")
            if appr.expires_at:
                print(f"  • Expires  : {appr.expires_at}")
        return 0

    elif action == "grant-direct":
        parser.add_argument("--human", required=True, help="Issuing human supervisor")
        parser.add_argument("--agent", required=True, help="Agent ID holding authorization")
        parser.add_argument("--action", required=True, help="Action/operation (e.g. SECRET_READ)")
        parser.add_argument("--scope", required=True, help="Scope pattern (e.g. AWS_*)")
        parser.add_argument("--reason", required=True, help="Durable rationale")
        parser.add_argument("--ttl", type=int, default=None, help="TTL duration in seconds")
        args = parser.parse_args(rem)
        manager = ApprovalManager(Path(args.path).resolve())
        appr = manager.issue_direct_approval(
            human=args.human,
            agent=args.agent,
            action=args.action,
            scope=args.scope,
            reason=args.reason,
            ttl_seconds=args.ttl,
            change=args.change,
        )
        if args.json:
            print(json.dumps(appr.to_dict(), indent=2))
        else:
            print(f"🛡️  Issued DurableApproval '{appr.approval_id}' directly to agent '{appr.agent}'")
            print(f"  • Human    : {appr.human}")
            print(f"  • Action   : {appr.action}")
            print(f"  • Scope    : {appr.scope}")
            print(f"  • Signature: {appr.signature[:16]}...")
            if appr.expires_at:
                print(f"  • Expires  : {appr.expires_at}")
        return 0

    elif action == "reject":
        parser.add_argument("request_id", nargs="?", default=None, help="Request ID to reject")
        parser.add_argument("--req", dest="req_opt", default=None, help="Request ID")
        parser.add_argument("--human", required=True, help="Rejecting human supervisor")
        parser.add_argument("--reason", default="", help="Rejection rationale")
        args = parser.parse_args(rem)
        req_id = args.req_opt or args.request_id
        if not req_id:
            parser.error("request_id is required")
        manager = ApprovalManager(Path(args.path).resolve())
        req = manager.reject_request(
            request_id=req_id,
            human=args.human,
            reason=args.reason,
            change_id=args.change,
        )
        if args.json:
            print(json.dumps(req.to_dict(), indent=2))
        else:
            print(f"❌ Rejected request '{req.request_id}' by {args.human}")
            if req.rejection_reason:
                print(f"  • Reason  : {req.rejection_reason}")
        return 0

    elif action == "revoke":
        parser.add_argument("approval_id", nargs="?", default=None, help="Approval ID to revoke")
        parser.add_argument("--appr", dest="appr_opt", default=None, help="Approval ID")
        parser.add_argument("--human", required=True, help="Revoking human supervisor")
        parser.add_argument("--reason", default="", help="Revocation rationale")
        args = parser.parse_args(rem)
        appr_id = args.appr_opt or args.approval_id
        if not appr_id:
            parser.error("approval_id is required")
        manager = ApprovalManager(Path(args.path).resolve())
        appr = manager.revoke_approval(
            approval_id=appr_id,
            human=args.human,
            reason=args.reason,
            change_id=args.change,
        )
        if args.json:
            print(json.dumps(appr.to_dict(), indent=2))
        else:
            print(f"🛑 Revoked DurableApproval '{appr.approval_id}' for agent '{appr.agent}' by {args.human}")
        return 0

    elif action == "list":
        parser.add_argument("--status", default=None, help="Filter requests by status (PENDING, APPROVED, REJECTED)")
        parser.add_argument("--active", action="store_true", help="Only list active (unexpired, unrevoked) approvals")
        args = parser.parse_args(rem)
        manager = ApprovalManager(Path(args.path).resolve())
        requests = manager.list_requests(status=args.status, change_id=args.change)
        approvals = manager.list_approvals(active_only=args.active, change_id=args.change)
        if args.json:
            print(json.dumps({
                "requests": [r.to_dict() for r in requests],
                "authorizations": [a.to_dict() for a in approvals],
            }, indent=2))
        else:
            print(f"📋 Requests ({len(requests)}):")
            for r in requests:
                print(f"  • {r.request_id} | Agent: {r.agent:12s} | {r.action:12s} -> {r.scope:20s} | Status: {r.status}")
            print(f"\n🛡️  Authorizations ({len(approvals)}):")
            for a in approvals:
                status = "REVOKED" if a.revoked else "ACTIVE"
                print(f"  • {a.approval_id} | Human: {a.human:12s} -> {a.agent:12s} | {a.action:12s} -> {a.scope:20s} | {status}")
        return 0

    else:
        print(f"Unknown approval action: '{action}'. See 'agentflow approval --help'.", file=sys.stderr)
        return 1


def run_events_cli(argv: Sequence[str]) -> int:
    """Handle forensic audit trail and execution event log CLI commands."""
    if argv and argv[0] in ("-h", "--help"):
        print("""Usage: agentflow events <action> [options]

Actions:
  list [--change <id>] [--type <type>] [--agent <id>] [--limit <n>] [--json]
      Query and list recorded execution events from the forensic audit trail.
  tail [-n <count>] [--change <id>] [--json]
      Tail the most recent execution events.
  verify [--path <dir>] [--json]
      Verify the cryptographic hash-chain integrity of the append-only event log.
  replay [--change <id>] [--verify] [--json]
      Deterministically reconstruct and optionally verify ledger state from the event stream.
""")
        return 0

    action = "list"
    rem = list(argv)
    if argv and argv[0].lower() in ("list", "tail", "verify", "replay"):
        action = argv[0].lower()
        rem = argv[1:]

    parser = argparse.ArgumentParser(prog=f"agentflow events {action}")
    parser.add_argument("--path", "--repo-root", dest="path", default=".", help="Repository root path")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    from .lifecycle.events import EventLogger

    if action == "list":
        parser.add_argument("--type", "--event-type", dest="event_type", default=None, help="Filter by event type")
        parser.add_argument("--agent", default=None, help="Filter by agent ID")
        parser.add_argument("--limit", type=int, default=50, help="Maximum number of events to return")
        args = parser.parse_args(rem)
        logger = EventLogger(Path(args.path).resolve())
        events = logger.query(
            change_id=args.change,
            event_type=args.event_type,
            agent_id=args.agent,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps([e.to_dict() for e in events], indent=2))
        else:
            print(f"📜 Execution Event Log ({len(events)} events):")
            for e in events:
                cid_str = f" [{e.change_id}]" if e.change_id else ""
                agent_str = f" ({e.agent_id})" if e.agent_id else ""
                target_str = f" -> {e.target}" if e.target else ""
                print(f"  • {e.timestamp} | {e.event_type:20s}{cid_str}{agent_str}{target_str}")
        return 0

    elif action == "tail":
        parser.add_argument("-n", "--count", type=int, default=20, help="Number of recent events to display")
        args = parser.parse_args(rem)
        logger = EventLogger(Path(args.path).resolve())
        events = logger.tail(n=args.count, change_id=args.change)
        if args.json:
            print(json.dumps([e.to_dict() for e in events], indent=2))
        else:
            print(f"📜 Recent Events (last {len(events)}):")
            for e in events:
                cid_str = f" [{e.change_id}]" if e.change_id else ""
                agent_str = f" ({e.agent_id})" if e.agent_id else ""
                target_str = f" -> {e.target}" if e.target else ""
                print(f"  • {e.timestamp} | {e.event_type:20s}{cid_str}{agent_str}{target_str}")
        return 0

    elif action == "verify":
        args = parser.parse_args(rem)
        logger = EventLogger(Path(args.path).resolve())
        valid, msg, broken_index = logger.verify_integrity()
        if args.json:
            print(json.dumps({"valid": valid, "message": msg, "broken_index": broken_index}, indent=2))
        else:
            if valid:
                print(f"✅ {msg}")
            else:
                print(f"❌ Event log integrity broken at event #{broken_index}: {msg}", file=sys.stderr)
        return 0 if valid else 1

    elif action == "replay":
        parser.add_argument("--verify", action="store_true", help="Verify replayed state against authoritative ledger")
        args = parser.parse_args(rem)
        repo_root = Path(args.path).resolve()
        from .lifecycle.events import EventReplayer, EventLogger
        if args.verify:
            matches, msg, diffs = EventReplayer.verify_state_matches_events(repo_root, change_id=args.change)
            if args.json:
                print(json.dumps({"matches": matches, "message": msg, "diffs": diffs}, indent=2))
            else:
                if matches:
                    print(f"✅ {msg}")
                else:
                    print(f"❌ Replay divergence: {msg}", file=sys.stderr)
                    for sec, d in diffs.items():
                        print(f"   • {sec}: actual={d.get('actual')} vs replayed={d.get('replayed')}", file=sys.stderr)
            return 0 if matches else 1
        else:
            logger = EventLogger(repo_root)
            events = logger.query(change_id=args.change)
            reconstructed = EventReplayer.replay(events, target_change=args.change)
            print(json.dumps(reconstructed, indent=2))
            return 0

    else:
        print(f"Unknown events action: '{action}'. See 'agentflow events --help'.", file=sys.stderr)
        return 1


def run_budget_cli(argv: Sequence[str]) -> int:
    """Handle agentflow budget commands (show, set, record, check)."""
    parser = argparse.ArgumentParser(prog="agentflow budget", description="Resource & Budget Governor CLI")
    parser.add_argument("action", nargs="?", default="show", choices=["show", "set", "record", "check"], help="Budget action")
    parser.add_argument("--path", default=".", help="Path to repository root")
    parser.add_argument("--change", default=None, help="Target change ID")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    if not argv:
        action = "show"
        rem: List[str] = []
    elif argv[0] in ("show", "set", "record", "check"):
        action = argv[0]
        rem = list(argv[1:])
    else:
        action = "show"
        rem = list(argv)

    from .lifecycle.resources import ResourceGovernor, ChangeBudget

    if action == "show":
        parser = argparse.ArgumentParser(prog="agentflow budget show", description="Show change resource budget status")
        parser.add_argument("--path", default=".", help="Path to repository root")
        parser.add_argument("--change", default=None, help="Target change ID")
        parser.add_argument("--json", action="store_true", help="Output JSON format")
        args = parser.parse_args(rem)

        repo_root = Path(args.path).resolve()
        gov = ResourceGovernor(repo_root)
        cid = gov._resolve_change_id(args.change)
        status = gov.evaluate(cid)

        if args.json:
            print(json.dumps(status.to_dict(), indent=2))
        else:
            print(gov.format_budget_report(cid))
        return 0 if not status.is_exceeded else 1

    elif action == "set":
        parser = argparse.ArgumentParser(prog="agentflow budget set", description="Configure resource budget limits for a change")
        parser.add_argument("--path", default=".", help="Path to repository root")
        parser.add_argument("--change", required=True, help="Target change ID")
        parser.add_argument("--tokens", type=int, default=None, help="Max tokens ceiling")
        parser.add_argument("--model-calls", type=int, default=None, help="Max model calls ceiling")
        parser.add_argument("--turns", type=int, default=None, help="Max turns ceiling")
        parser.add_argument("--time", type=float, default=None, help="Max wall-clock seconds ceiling")
        parser.add_argument("--dollars", type=float, default=None, help="Max monetary dollars (USD) ceiling")
        parser.add_argument("--tools", type=int, default=None, help="Max tool executions ceiling")
        parser.add_argument("--network", type=int, default=None, help="Max network operations ceiling")
        parser.add_argument("--agent", default="human", help="Agent or supervisor setting budget")
        parser.add_argument("--reason", default="Manual budget adjustment", help="Reason for setting budget")
        parser.add_argument("--json", action="store_true", help="Output JSON format")
        args = parser.parse_args(rem)

        repo_root = Path(args.path).resolve()
        gov = ResourceGovernor(repo_root)
        current = gov.get_budget(args.change)

        new_budget = ChangeBudget(
            max_tokens=args.tokens if args.tokens is not None else current.max_tokens,
            max_model_calls=args.model_calls if args.model_calls is not None else current.max_model_calls,
            max_turns=args.turns if args.turns is not None else current.max_turns,
            max_time_seconds=args.time if args.time is not None else current.max_time_seconds,
            max_dollars=args.dollars if args.dollars is not None else current.max_dollars,
            max_tool_executions=args.tools if args.tools is not None else current.max_tool_executions,
            max_network_operations=args.network if args.network is not None else current.max_network_operations,
            max_remediation_attempts=current.max_remediation_attempts,
            max_same_failures=current.max_same_failures,
        )
        gov.set_budget(args.change, new_budget, agent_id=args.agent, reason=args.reason)

        if args.json:
            print(json.dumps({"status": "SUCCESS", "change": args.change, "budget": new_budget.to_dict()}, indent=2))
        else:
            print(f"✅ Resource budget updated for change '{args.change}'")
            print(gov.format_budget_report(args.change))
        return 0

    elif action == "record":
        parser = argparse.ArgumentParser(prog="agentflow budget record", description="Record resource consumption for a change")
        parser.add_argument("--path", default=".", help="Path to repository root")
        parser.add_argument("--change", required=True, help="Target change ID")
        parser.add_argument("--tokens", type=int, default=0, help="Tokens consumed")
        parser.add_argument("--model-calls", type=int, default=0, help="Model calls made")
        parser.add_argument("--dollars", type=float, default=0.0, help="Monetary cost (USD) incurred")
        parser.add_argument("--tools", type=int, default=0, help="Tool executions made")
        parser.add_argument("--network", type=int, default=0, help="Network operations performed")
        parser.add_argument("--turns", type=int, default=0, help="Turns completed")
        parser.add_argument("--time", type=float, default=0.0, help="Wall-clock time elapsed (seconds)")
        parser.add_argument("--agent", default="agent", help="Acting agent ID")
        parser.add_argument("--reason", default="", help="Consumption description")
        parser.add_argument("--json", action="store_true", help="Output JSON format")
        args = parser.parse_args(rem)

        repo_root = Path(args.path).resolve()
        gov = ResourceGovernor(repo_root)
        status = gov.record_consumption(
            change_id=args.change,
            tokens=args.tokens,
            model_calls=args.model_calls,
            dollars=args.dollars,
            tool_executions=args.tools,
            network_operations=args.network,
            turns=args.turns,
            time_seconds=args.time,
            agent_id=args.agent,
            reason=args.reason,
        )

        if args.json:
            print(json.dumps(status.to_dict(), indent=2))
        else:
            if status.is_exceeded:
                print(f"⛔ Consumption recorded, but resource budget EXCEEDED for '{args.change}': {status.reason}", file=sys.stderr)
            else:
                print(f"✅ Consumption recorded for change '{args.change}' (within budget)")
        return 0 if not status.is_exceeded else 1

    elif action == "check":
        parser = argparse.ArgumentParser(prog="agentflow budget check", description="Check if change is within resource budget")
        parser.add_argument("--path", default=".", help="Path to repository root")
        parser.add_argument("--change", default=None, help="Target change ID")
        parser.add_argument("--json", action="store_true", help="Output JSON format")
        args = parser.parse_args(rem)

        repo_root = Path(args.path).resolve()
        gov = ResourceGovernor(repo_root)
        cid = gov._resolve_change_id(args.change)
        status = gov.evaluate(cid)

        if args.json:
            print(json.dumps({"within_budget": not status.is_exceeded, "reason": status.reason, "exceeded_metrics": status.exceeded_metrics}, indent=2))
        else:
            if status.is_exceeded:
                print(f"❌ Budget exceeded for '{cid}': {status.reason}", file=sys.stderr)
            else:
                print(f"✅ Change '{cid}' is within resource budget")
        return 0 if not status.is_exceeded else 1

    else:
        print(f"Unknown budget action: '{action}'. See 'agentflow budget --help'.", file=sys.stderr)
        return 1


def run_benchmark_cli(argv: Sequence[str]) -> int:
    """Handle agentflow benchmark / eval commands."""
    parser = argparse.ArgumentParser(prog="agentflow benchmark", description="Run repeatable benchmark scenarios measuring AgentFlow itself.")
    parser.add_argument("--suite", "--dim", default="all", help="Scenario suite/dimension to run (e.g. all, policy, convergence, verification, recovery, race, latency, cost)")
    parser.add_argument("--iterations", type=int, default=1, help="Number of repetitions per scenario")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--output", default=None, help="Save report to file path")
    args = parser.parse_args(argv)

    from .lifecycle.evaluation import EvaluationRunner, format_terminal_report

    runner = EvaluationRunner()
    report = runner.run_suite(dimension_filter=args.suite, iterations=args.iterations)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_terminal_report(report))

    return 0 if report.failed_scenarios == 0 else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Unified entrypoint for ship CLI with subcommands, specialist tools, and MCP server."""
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return run_lifecycle(["--help"])

    cmd = argv[0].strip().lower()
    sub_args = list(argv[1:])

    # MCP Server dispatch
    if cmd == "mcp":
        from ship.mcp.server import main as mcp_main
        return mcp_main()

    if cmd in ("lease", "coordinate"):
        return run_lease_cli(sub_args)

    if cmd in ("session", "sessions"):
        return run_session_cli(sub_args)

    if cmd in ("identity", "identities"):
        return run_identity_cli(sub_args)

    if cmd in ("capability", "capabilities", "cap"):
        return run_capability_cli(sub_args)

    if cmd in ("approval", "approvals", "authz"):
        return run_approval_cli(sub_args)

    if cmd in ("event", "events", "log", "audit"):
        return run_events_cli(sub_args)

    if cmd in ("budget", "budgets", "resource", "resources"):
        return run_budget_cli(sub_args)

    if cmd in ("benchmark", "bench", "eval", "evaluation"):
        return run_benchmark_cli(sub_args)

    # Specialist tools dispatch
    if cmd == "tdd":
        from ship.tools.tdd import main as tdd_main
        return tdd_main(sub_args)

    if cmd == "simplify":
        from ship.tools.simplify import main as simplify_main
        return simplify_main(sub_args)

    if cmd == "spike":
        from ship.tools.spike import main as spike_main
        return spike_main(sub_args)

    if cmd == "review":
        if sub_args and sub_args[0] == "validate":
            from ship.tools.review import main as review_main
            return review_main(sub_args[1:])
        from ship.tools.review import main as review_main
        return review_main(sub_args)

    # Subcommands mapping to lifecycle operations
    if cmd == "init":
        init_parser = argparse.ArgumentParser(prog="agentflow init", description="Initialize AgentFlow workflow in repository.")
        init_parser.add_argument("--profile", choices=["standard", "small-fix", "high-risk"], default="standard")
        init_parser.add_argument("--scope", default=".")
        init_parser.add_argument("--test", "--test-cmd", default=None, dest="test_cmd", help="Custom test command.")
        init_parser.add_argument("--path", default=".", help="Repository root path.")
        init_parser.add_argument("-f", "--force", action="store_true", help="Overwrite existing .agentflow.json.")
        init_args = init_parser.parse_args(sub_args)
        target_root = Path(init_args.path).resolve()
        try:
            res = init_agentflow(target_root, profile=init_args.profile, scope=init_args.scope, test_cmd=init_args.test_cmd, force=init_args.force)
            print(f"✅ Initialized AgentFlow workflow in {target_root}")
            print(f"  • Created .agentflow.json (profile: {res['profile']}, test: \"{res['test_command']}\")")
            print(f"  • Ensured .agentflow/ is in .gitignore")
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if cmd == "status":
        return run_lifecycle(["--status-check"] + sub_args)

    if cmd in ("turn", "next-turn", "next"):
        return run_lifecycle(["--next-turn"] + sub_args)

    if cmd == "checkpoint":
        if not sub_args or sub_args[0].startswith("-"):
            print("Error: 'ship checkpoint' requires a gate argument (e.g. 'design', 'implementation').", file=sys.stderr)
            return 1
        gate = sub_args[0]
        return run_lifecycle(["--checkpoint", gate] + sub_args[1:])

    if cmd == "rollback":
        if not sub_args or sub_args[0].startswith("-"):
            print("Error: 'ship rollback' requires a gate argument (e.g. 'design', 'implementation').", file=sys.stderr)
            return 1
        gate = sub_args[0]
        return run_lifecycle(["--rollback", gate] + sub_args[1:])

    if cmd == "approve":
        if len(sub_args) < 2:
            print("Error: 'ship approve' requires <change> and <digest> arguments.", file=sys.stderr)
            return 1
        ch, fp = sub_args[0], sub_args[1]
        rem = sub_args[2:]
        if "--approved-by" not in rem:
            rem.extend(["--approved-by", "session-user"])
        return run_lifecycle(["--change", ch, "--approve-design", fp] + rem)

    if cmd in ("turns", "provenance"):
        return run_lifecycle(["--turns"] + sub_args)

    if cmd == "record-turn":
        if not sub_args:
            print("Error: 'ship record-turn' requires a payload or file argument.", file=sys.stderr)
            return 1
        return run_lifecycle(["--record-turn", sub_args[0]] + sub_args[1:])

    if cmd == "record-tests":
        if not sub_args:
            print("Error: 'ship record-tests' requires 'pass', 'fail', or a JSON file path.", file=sys.stderr)
            return 1
        return run_lifecycle(["--record-tests", sub_args[0]] + sub_args[1:])

    if cmd == "record-review":
        if not sub_args:
            print("Error: 'ship record-review' requires a review report JSON file path.", file=sys.stderr)
            return 1
        return run_lifecycle(["--record-review", sub_args[0]] + sub_args[1:])

    if cmd == "archive":
        if sub_args and not sub_args[0].startswith("-"):
            return run_lifecycle(["--archive", sub_args[0]] + sub_args[1:])
        return run_lifecycle(["--archive"] + sub_args)

    if cmd == "trailers":
        if sub_args and not sub_args[0].startswith("-"):
            return run_lifecycle(["--generate-trailers", "--change", sub_args[0]] + sub_args[1:])
        return run_lifecycle(["--generate-trailers"] + sub_args)

    if cmd == "doctor":
        return run_lifecycle(["--doctor"] + sub_args)

    if cmd == "migrate-state":
        return run_lifecycle(["--migrate-state"] + sub_args)

    if cmd == "sync-state":
        return run_lifecycle(["--sync-state"] + sub_args)

    if cmd == "fingerprint":
        return run_lifecycle(["--fingerprint"] + sub_args)

    if cmd == "verify":
        change_arg = None
        rem = []
        if sub_args and not sub_args[0].startswith("-"):
            change_arg = sub_args[0]
            rem = sub_args[1:]
        else:
            rem = sub_args
        args_to_run = ["--verify"]
        if change_arg:
            args_to_run.extend(["--change", change_arg])
        args_to_run.extend(rem)
        return run_lifecycle(args_to_run)

    if cmd == "resume":
        if sub_args and not sub_args[0].startswith("-"):
            return run_lifecycle(["--resume", sub_args[0]] + sub_args[1:])
        return run_lifecycle(["--resume", ""] + sub_args)

    # If starts with '-' or not a known subcommand, pass directly to lifecycle parser
    return run_lifecycle(argv)


if __name__ == "__main__":
    sys.exit(main())
