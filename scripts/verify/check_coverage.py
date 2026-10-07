#!/usr/bin/env python3
"""Validate the skill coverage inventory and report gaps without running its checks.

Uses only the standard library. References are inspected as text/AST, never imported
or executed. A valid manifest is not a passing skill evaluation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path(__file__)).resolve()
    for p in [current] + list(current.parents):
        if (p / "tests/skill_coverage.json").is_file():
            return p
    return current.parents[1]


ROOT = find_repo_root()
MANIFEST = ROOT / "tests/skill_coverage.json"
CASE_KINDS = {"tool_unit", "lifecycle_integration", "static_fixture", "rendered_browser", "manual_agent"}
OBSERVATION_CONTRACT = {
    "capture_kind": "reported",
    "terminal_statuses": ["completed", "failed", "skipped"],
    "completion_is_verified": False,
    "recording_order_is_execution_order": False,
    "affects_delivery_gates": False,
    "fully_observed_meaning": "Every catalog step has a terminal observation; failures and skips count. This is not success.",
}


class CoverageError(ValueError):
    """The inventory is malformed, incomplete, or out of date."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise CoverageError(message)


def text(value: Any, context: str) -> None:
    require(isinstance(value, str) and bool(value.strip()), f"{context}: expected nonempty text")


def fields(value: Any, required: set[str], context: str) -> None:
    require(isinstance(value, dict), f"{context}: expected object")
    require(set(value) == required, f"{context}: expected fields {sorted(required)}")


def strings(value: Any, context: str, *, nonempty: bool = False) -> None:
    require(isinstance(value, list), f"{context}: expected list")
    if nonempty:
        require(bool(value), f"{context}: must not be empty")
    for item in value:
        text(item, context)
    require(len(value) == len(set(value)), f"{context}: duplicate entries")


def local_file(root: Path, value: Any) -> Path:
    text(value, "path")
    relative = Path(value)
    require(not relative.is_absolute() and ".." not in relative.parts,
            f"{value}: reference must be repository-relative")
    target = (root / relative).resolve()
    require(target.is_relative_to(root.resolve()) and target.is_file(),
            f"{value}: missing file or reference outside repository")
    return target


def python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()

    def visit(nodes: list[ast.stmt], prefix: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + node.name
                names.add(name)
                visit(node.body, name + ".")

    visit(tree.body)
    return names


def validate_reference(reference: Any, root: Path, context: str) -> None:
    require(isinstance(reference, dict), f"{context}: expected reference object")
    require(set(reference) in ({"path", "text"}, {"path", "symbol"}),
            f"{context}: reference needs path and exactly one text or symbol selector")
    path = local_file(root, reference["path"])
    if "symbol" in reference:
        text(reference["symbol"], context)
        require(path.suffix == ".py", f"{context}: symbol selector requires Python")
        require(reference["symbol"] in python_symbols(path),
                f"{context}: missing symbol {reference['symbol']} in {reference['path']}")
    else:
        text(reference["text"], context)
        require(reference["text"] in path.read_text(encoding="utf-8"),
                f"{context}: missing text selector in {reference['path']}")


def validate_manifest(data: Any, root: Path = ROOT) -> None:
    """Check schema, source drift, all skill contracts, and executable references."""
    fields(data, {"schema_version", "scope", "limitations", "source_digests",
                  "validators", "eval_cases", "skills"}, "manifest")
    require(type(data["schema_version"]) is int and data["schema_version"] == 1,
            "Unsupported coverage schema_version")
    text(data["scope"], "scope")
    strings(data["limitations"], "limitations", nonempty=True)
    for name in ("source_digests", "validators", "eval_cases", "skills"):
        require(isinstance(data[name], dict), f"{name}: expected object")

    for path, digest in data["source_digests"].items():
        text(digest, f"{path} digest")
        actual = hashlib.sha256(local_file(root, path).read_bytes()).hexdigest()
        require(digest == actual, f"{path}: source drift; review step coverage before updating its digest")

    for name in ("validators", "eval_cases"):
        for identifier, entry in data[name].items():
            text(identifier, name)
            keys = {"reference", "scope"} | ({"kind"} if name == "eval_cases" else set())
            fields(entry, keys, identifier)
            text(entry["scope"], f"{identifier} scope")
            validate_reference(entry["reference"], root, identifier)
            if name == "eval_cases":
                require(isinstance(entry["kind"], str) and entry["kind"] in CASE_KINDS,
                        f"{identifier}: unsupported eval kind; component tests cannot claim agent coverage")
                ref = entry["reference"]
                if entry["kind"] == "manual_agent":
                    require("text" in ref and Path(ref["path"]).suffix == ".md",
                            f"{identifier}: manual case must select documented acceptance criteria")
                elif entry['kind'] == 'rendered_browser':
                    require('text' in ref and Path(ref['path']).suffix == '.cjs',
                            f'{identifier}: rendered browser case must select its executable JS check')
                else:
                    require("symbol" in ref and ref["symbol"].split(".")[-1].startswith("test_"),
                            f"{identifier}: automated case must select a test function")

    actual_skills = {p.parent.name for p in (root / "skills").glob("*/SKILL.md")}
    require(bool(actual_skills) and set(data["skills"]) == actual_skills,
            f"skills: must inventory every skill exactly once: {sorted(actual_skills)}")
    referenced_sources = set()
    all_ids = set()
    for name, skill in data["skills"].items():
        fields(skill, {"source", "steps"}, name)
        require(skill["source"] == f"skills/{name}/SKILL.md", f"{name}: unexpected skill source")
        source = local_file(root, skill["source"]).read_text(encoding="utf-8")
        referenced_sources.add(skill["source"])
        contract = re.search(r"<turn_contract>(.*?)</turn_contract>", source, re.DOTALL)
        require(contract is not None, f"{name}: missing turn contract")
        expected_contracts = {int(n) for n in re.findall(r"^✓\s*(\d+)\.", contract.group(1), re.MULTILINE)}
        require(bool(expected_contracts), f"{name}: no numbered turn contracts")
        require(isinstance(skill["steps"], list) and bool(skill["steps"]), f"{name}: missing steps")
        covered_contracts = set()
        for step in skill["steps"]:
            fields(step, {"id", "title", "requirement", "applies_when", "turn_contracts",
                          "expected_evidence", "validators", "eval_cases", "gaps"}, f"{name} step")
            for key in ("id", "title", "applies_when"):
                text(step[key], f"{name} {key}")
            identifier = step["id"]
            require(re.fullmatch(re.escape(name) + r"\.[a-z0-9]+(?:-[a-z0-9]+)*", identifier) is not None,
                    f"{identifier}: expected stable skill.step ID")
            require(identifier not in all_ids, f"{identifier}: duplicate step ID")
            all_ids.add(identifier)
            validate_reference(step["requirement"], root, identifier)
            require("text" in step["requirement"], f"{identifier}: requirement must quote its source")
            require(step["requirement"]["path"].startswith(f"skills/{name}/"),
                    f"{identifier}: requirement must come from the owning skill")
            referenced_sources.add(step["requirement"]["path"])
            for key in ("expected_evidence", "gaps", "validators", "eval_cases"):
                strings(step[key], f"{identifier} {key}", nonempty=key in {"expected_evidence", "gaps"})
            for key in ("validators", "eval_cases"):
                require(set(step[key]) <= set(data[key]), f"{identifier}: unknown {key} reference")
            contracts = step["turn_contracts"]
            require(isinstance(contracts, list) and all(type(n) is int for n in contracts),
                    f"{identifier}: turn_contracts must be an integer list")
            require(len(contracts) == len(set(contracts)) and set(contracts) <= expected_contracts,
                    f"{identifier}: invalid or duplicate turn contract mapping")
            covered_contracts.update(contracts)
        require(covered_contracts == expected_contracts,
                f"{name}: unmapped turn contracts {sorted(expected_contracts - covered_contracts)}")
    require(referenced_sources == set(data["source_digests"]),
            "source_digests must cover exactly all mapped skill and requirement sources")


def inventory_report(data: dict, skill_name: str | None = None) -> dict:
    """Report presence of checks, never infer behavioral success from their presence."""
    summaries = {}
    steps = []
    for name, skill in data["skills"].items():
        if skill_name and name != skill_name:
            continue
        summary = {"steps": len(skill["steps"]), "with_validators": 0,
                   "with_automated_component_cases": 0, "with_manual_agent_cases": 0,
                   "without_agent_cases": 0, "with_gaps": 0}
        for step in skill["steps"]:
            kinds = {data["eval_cases"][key]["kind"] for key in step["eval_cases"]}
            summary["with_validators"] += bool(step["validators"])
            summary["with_automated_component_cases"] += bool(kinds - {"manual_agent"})
            summary["with_manual_agent_cases"] += "manual_agent" in kinds
            summary["without_agent_cases"] += "manual_agent" not in kinds
            summary["with_gaps"] += bool(step["gaps"])
            steps.append({**step, "agent_evaluation": "manual_only" if "manual_agent" in kinds else "missing"})
        summaries[name] = summary
    return {"inventory_status": "valid", "scope": data["scope"], "limitations": data["limitations"],
            "observation_contract": OBSERVATION_CONTRACT.copy(),
            "skills": summaries, "total_steps": len(steps), "steps": steps}


def unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--skill", help="Limit the report; validation still checks every skill")
    parser.add_argument("--json", action="store_true", help="Emit inventory summaries and step mappings as JSON")
    parser.add_argument("--gaps", action="store_true", help="List the gap for each selected step")
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        validate_manifest(data)
        if args.skill and args.skill not in data["skills"]:
            raise CoverageError(f"Unknown skill: {args.skill}")
        report = inventory_report(data, args.skill)
    except (ValueError, OSError, SyntaxError) as exc:
        if args.json:
            print(json.dumps({"inventory_status": "invalid", "error": str(exc)}))
        else:
            print(f"INVALID skill coverage inventory: {exc}")
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("Skill coverage inventory: VALID (not an evaluation result)")
        print(f"{'Skill':<12} {'Steps':>5} {'Validators':>11} {'Component cases':>16} {'Manual agent':>13} {'Gaps':>5}")
        for name, summary in report["skills"].items():
            print(f"{name:<12} {summary['steps']:>5} {summary['with_validators']:>11} "
                  f"{summary['with_automated_component_cases']:>16} {summary['with_manual_agent_cases']:>13} "
                  f"{summary['with_gaps']:>5}")
        print("Counts are steps with mapped checks, not executed tests or pass rates.")
        print("Host-observed agent behavior: not registered. The response harness defaults to stubs.")
        if args.gaps:
            for step in report["steps"]:
                print(f"{step['id']} ({step['applies_when']}): {' '.join(step['gaps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
