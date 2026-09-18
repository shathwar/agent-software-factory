"""Unified CLI dispatcher for Ship: Autonomous Engineering Lifecycle & MCP Server."""

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence

from ship.lifecycle.engine import LifecycleEngine, format_summary
from ship.lifecycle.ledger import FileLedgerStore, record_test_run_to_ledger, record_review_to_ledger, record_turn_to_ledger, read_ledger_file
from ship.lifecycle.checkpoints import CheckpointManager
from ship.lifecycle.evidence import design_fingerprint
from ship.lifecycle.vcs import GitClient

compute_working_tree_fingerprint = GitClient().compute_working_tree_fingerprint
from ship.lifecycle.trailers import CommitTrailerGenerator
from ship.lifecycle.operations import doctor, migrate_state
from ship.lifecycle.paths import repository_path
from ship.lifecycle.turns import get_next_turn_contract, format_turn_contract, format_turns_log

VERSION = "1.0.0"

HELP_BANNER = f"""Ship SDLC CLI v{VERSION} — Autonomous Engineering Lifecycle & MCP Server

USAGE:
  ship <command> [options]
  ship [legacy-options]

CORE SUBCOMMANDS:
  ship status [--change <id>] [--path <dir>]
      Evaluate gate readiness (exits 0=ready, 1=blocked, 2=rollback required).
  ship turn [--change <id>] [--format text|json]
      Derive the deterministic Turn Contract for the active change.
  ship checkpoint <gate> [--change <id>]
      Create an immutable git ref and receipt for design or implementation.
  ship rollback <gate> [--change <id>]
      Safely revert workspace to a prior checkpoint with backup preservation.
  ship approve <change> <fingerprint> [--approved-by <id>]
      Record external design specification approval.
  ship archive <change> [--force]
      Apply delta specs and archive completed change package to openspec/archive/.
  ship trailers <change>
      Generate RFC 5133 Git commit trailers based on current verified evidence.
  ship doctor [--path <dir>]
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
    parser.add_argument("--config", default=None, help="Path to custom .ship.json configuration.")
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
        output_result(turns, [format_turns_log(turns, change_id=args.change)])
        return 0

    if args.record_turn:
        try:
            t_path = Path(args.record_turn)
            t_payload = json.loads(t_path.read_text(encoding="utf-8")) if t_path.is_file() else json.loads(args.record_turn)
            if not isinstance(t_payload, dict):
                raise ValueError("Turn record payload must be a JSON object.")
        except Exception as exc:
            print(f"Error parsing turn record: {exc}", file=sys.stderr)
            return 1
        if args.harness and "harness" not in t_payload:
            t_payload["harness"] = args.harness
        rec = ledger_store.record_turn(repo_root, t_payload, change_id=args.change, sync_fn=engine.sync_ledger)
        output_result(rec.to_dict(), [f"Recorded turn {rec.turn_id} for skill '{rec.skill}' under harness '{rec.harness}'"])
        return 0

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

    if args.set_active_change:
        ledger_store.set_active_change(repo_root, args.set_active_change)
        output_result({"active_change_id": args.set_active_change}, [f"Active change set to '{args.set_active_change}'."])
        return 0

    if args.fingerprint:
        tfp = compute_working_tree_fingerprint(repo_root)
        output_result({"working_tree_fingerprint": tfp}, [tfp])
        return 0

    if args.checkpoint:
        try:
            mgr = CheckpointManager()
            ref, r_path = mgr.create_checkpoint(repo_root, args.checkpoint, change=args.change, create_git_tag=args.create_git_tag)
            output_result({"ref": ref, "receipt": str(r_path)}, [f"Created checkpoint for {args.checkpoint}: {ref}"])
            return 0
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.rollback:
        try:
            mgr = CheckpointManager()
            restored, b_path = mgr.perform_rollback(repo_root, args.rollback, change=args.change, force=args.force)
            output_result({"restored_ref": restored, "backup": str(b_path)}, [f"Rolled back {args.rollback} to {restored}; backup at {b_path}"])
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
            trailers, a_path = engine.archive_change(repo_root, target, force=args.force)
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

    # If starts with '-' or not a known subcommand, pass directly to lifecycle parser
    return run_lifecycle(argv)


if __name__ == "__main__":
    sys.exit(main())
