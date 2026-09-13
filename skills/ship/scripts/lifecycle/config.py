"""Configuration loading and validation for Ship Lifecycle Engine."""

import json
from pathlib import Path
from typing import Any, Dict, Optional


class ShipConfigManager:
    """Manages discovery, loading, and merging of .ship.json configuration."""

    @staticmethod
    def get_default_config() -> Dict[str, Any]:
        return {
            "version": 1,
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

        config_file: Optional[Path] = None
        if explicit_path:
            p = Path(explicit_path)
            if not p.is_absolute():
                p = repo_root / p
            if p.exists() and p.is_file():
                config_file = p
        else:
            candidate = repo_root / ".ship.json"
            if candidate.exists() and candidate.is_file():
                config_file = candidate

        if not config_file:
            return default_config

        try:
            content = config_file.read_text(encoding="utf-8", errors="replace")
            loaded: Dict[str, Any] = json.loads(content)
            if not isinstance(loaded, dict):
                return default_config

            def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
                for k, v in source.items():
                    if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                        deep_merge(target[k], v)
                    else:
                        target[k] = v

            deep_merge(default_config, loaded)
            try:
                default_config["config_source"] = str(config_file.relative_to(repo_root))
            except ValueError:
                default_config["config_source"] = str(config_file)
        except Exception as e:
            default_config["config_error"] = str(e)

        return default_config
