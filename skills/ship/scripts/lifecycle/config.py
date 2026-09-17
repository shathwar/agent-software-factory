"""Configuration loading and validation for Ship Lifecycle Engine."""

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional


class ShipConfigManager:
    """Manages discovery, loading, and merging of .ship.json configuration."""

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
            "create_git_tag": False,
            "config_source": None,
        }

    @classmethod
    def load(cls, repo_root: Path, explicit_path: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from .ship.json with deep merge onto defaults."""
        default_config = cls.get_default_config()

        config_file = Path(explicit_path) if explicit_path else repo_root / ".ship.json"
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
            schema = json.loads((Path(__file__).resolve().parents[2] / "references/ship.schema.json").read_text(encoding="utf-8"))
            validate(default_config, schema, "config")
            try:
                default_config["config_source"] = str(config_file.relative_to(repo_root))
            except ValueError:
                default_config["config_source"] = str(config_file)
        except (OSError, ValueError) as e:
            raise ValueError(f"Invalid Ship configuration {config_file}: {e}") from e

        return default_config
