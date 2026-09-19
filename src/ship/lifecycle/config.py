"""Configuration loading and validation for Ship Lifecycle Engine."""

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional


class ShipConfigManager:
    """Manages discovery, loading, and merging of .agentflow.json configuration."""

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            "version": 1,
            "workflow": {"profile": "standard", "execution": "auto"},
            "project": {
                "name": "",
                "root": ".",
                "scope": ".",
            },
            "gates": {
                "design": {
                    "adr_dir": "docs/adr",
                    "specs_dir": "openspec/specs",
                },
                "spike": {
                    "timeout": 60.0,
                    "concurrency": 1,
                },
                "implementation": {
                    "test": "",
                    "typecheck": "",
                    "lint": "",
                },
                "simplify": {
                    "max_debt": 0,
                    "strict": True,
                },
                "review": {
                    "base_branch": "main",
                    "reviewers": ["correctness", "concurrency", "design", "judge"],
                    "max_iterations": 3,
                },
                "delivery": {
                    "target_branch": "main",
                    "clean_worktree": True,
                    "sync_specs": True,
                    "archive_packages": True,
                },
            },
            "convergence": {
                "max_remediation_attempts": 3,
                "max_same_failure_count": 2,
                "max_total_turns": 25,
                "max_time_seconds": 1800.0,
                "max_cost_dollars": 10.0,
            },
            "budget": {
                "max_tokens": 1000000,
                "max_model_calls": 100,
                "max_turns": 25,
                "max_time_seconds": 1800.0,
                "max_dollars": 10.0,
                "max_tool_executions": 200,
                "max_network_operations": 50,
                "max_remediation_attempts": 3,
                "max_same_failures": 2,
            },
            "coordination": {
                "default_lease_ttl_seconds": 600,
                "heartbeat_interval_seconds": 120,
                "allow_file_overlap": False,
                "max_concurrent_workers": 4,
            },
            "provenance": {
                "enforce_principal_attribution": True,
                "enforce_maker_checker_separation": True,
                "default_runtime": "antigravity",
            },
            "create_git_tag": False,
            "config_source": None,
        }

    @classmethod
    def load(cls, repo_root: Path, explicit_path: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from .agentflow.json with deep merge onto defaults."""
        default_config = cls.get_default_config()

        config_file = Path(explicit_path) if explicit_path else repo_root / ".agentflow.json"
        if explicit_path and not config_file.is_absolute():
            config_file = repo_root / config_file
        if not explicit_path and not config_file.exists() and not config_file.is_symlink():
            return default_config

        try:
            loaded = json.loads(config_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("configuration must be a JSON object")

            # Validate the schema vocabulary used by the bundled manifest, without
            # adding a runtime dependency or duplicating field rules in Python.
            def validate(value: Any, schema: Dict[str, Any], path: str) -> None:
                types = {"object": dict, "array": list, "string": str,
                         "integer": int, "number": (int, float), "boolean": bool, "null": type(None)}
                allowed = schema["type"]
                allowed = allowed if isinstance(allowed, list) else [allowed]
                if not any(type(value) in (types[t] if isinstance(types[t], tuple) else (types[t],)) for t in allowed):
                    raise ValueError(f"{path} must be {' or '.join(allowed)}")
                if type(value) is float and not math.isfinite(value):
                    raise ValueError(f"{path} must be finite")
                if "enum" in schema and value not in schema["enum"]:
                    raise ValueError(f"{path} must be one of {schema['enum']}")
                if "minimum" in schema and value < schema["minimum"]:
                    raise ValueError(f"{path} must be at least {schema['minimum']}")
                if isinstance(value, dict):
                    properties = schema.get("properties", {})
                    if schema.get("additionalProperties") is False and value.keys() - properties.keys():
                        raise ValueError(f"{path} contains unknown fields: {sorted(value.keys() - properties.keys())}")
                    for required in schema.get("required", []):
                        if required not in value:
                            raise ValueError(f"{path}.{required} is required")
                    for key in value.keys() & properties.keys():
                        validate(value[key], properties[key], f"{path}.{key}")
                elif isinstance(value, list):
                    for item in value:
                        validate(item, schema["items"], path)

            profile = loaded.get("workflow", {}).get("profile", "standard") if isinstance(loaded.get("workflow", {}), dict) else None
            if profile == "small-fix":
                default_config["gates"]["review"]["reviewers"] = ["correctness", "judge"]
            if profile not in ("standard", "small-fix", "high-risk"):
                raise ValueError("workflow.profile must be small-fix, standard, or high-risk")

            def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
                for k, v in source.items():
                    if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                        deep_merge(target[k], v)
                    else:
                        target[k] = v

            deep_merge(default_config, loaded)
            schema = json.loads(get_schema_path().read_text(encoding="utf-8"))
            validate(default_config, schema, "config")
            try:
                default_config["config_source"] = str(config_file.relative_to(repo_root))
            except ValueError:
                default_config["config_source"] = str(config_file)
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid Ship configuration {config_file}: {e}") from e

        return default_config


def get_schema_path() -> Path:
    """Resolve the path to agentflow.schema.json across repo, skill, and package environments."""
    current = Path(__file__).resolve()
    # 1. From skills/ship/scripts/lifecycle/ -> skills/ship/references/agentflow.schema.json
    p1 = current.parents[2] / "references" / "agentflow.schema.json"
    if p1.is_file():
        return p1
    # 2. From src/ship/lifecycle/ -> skills/ship/references/agentflow.schema.json in repo
    p2 = current.parents[3] / "skills" / "ship" / "references" / "agentflow.schema.json"
    if p2.is_file():
        return p2
    # 3. From src/ship/references/agentflow.schema.json (bundled in src)
    p3 = current.parent.parent / "references" / "agentflow.schema.json"
    if p3.is_file():
        return p3
    return p1
