"""
policy.py – Organisation-Wide Enterprise Policy Layer.

Enforces an authoritative organisation-level policy across all skills:
policy:
  skill: ship
  risk: high

  allowed:
    filesystem: workspace
    git: read/write

  requires_approval:
    commit: true
    pull_request: true
    deployment: true

  forbidden:
    production: true
    credentials: true

Guarantees:
1. Every skill inherits organization policy rather than defining its own interpretation.
2. Monotonic Strictness Law: Child skills can only tighten constraints, NEVER relax
   forbidden invariants (credentials, production, force_push) or bypass required approvals.
3. Decoupled, zero-dependency policy engine enforcing filesystem, git, commands, tools,
   and lifecycle operations.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Enums and Data Models
# ---------------------------------------------------------------------------

class PolicyRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecisionStatus(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


class PolicyInheritanceError(PermissionError):
    """Raised when a child or custom skill attempts to relax organization-level policy."""
    pass


class PolicyConfigurationError(ValueError):
    """An invalid policy must never become an implicit permission grant."""


def _validate_policy(data):
    if not isinstance(data, dict):
        raise PolicyConfigurationError("Policy must be a mapping")
    schemas = {
        "allowed": {"filesystem", "git", "network", "tools", "commands"},
        "requires_approval": {"commit", "pull_request", "deployment", "external_call", "secret_access", "custom_actions"},
        "forbidden": {"production", "credentials", "force_push", "network_egress", "paths"},
    }
    unknown = set(data) - {"skill", "risk", "name", "description", "skills", *schemas}
    if unknown:
        raise PolicyConfigurationError(f"Unknown policy fields: {sorted(unknown)}")
    for section, fields in schemas.items():
        block = data.get(section, {})
        if not isinstance(block, dict) or set(block) - fields:
            raise PolicyConfigurationError(f"Invalid {section} policy fields")
        for key, value in block.items():
            if key in {"tools", "commands", "paths", "custom_actions"}:
                if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                    raise PolicyConfigurationError(f"{section}.{key} must be a list of nonempty strings")
            elif section != "allowed" and not isinstance(value, bool):
                raise PolicyConfigurationError(f"{section}.{key} must be a boolean")
    for key, choices in {"filesystem": {"workspace", "read_only", "scratch", "none"},
                         "git": {"read/write", "read", "none"},
                         "network": {"none", "internal", "external"}}.items():
        value = data.get("allowed", {}).get(key)
        if key in data.get("allowed", {}) and (not isinstance(value, str) or value not in choices):
            raise PolicyConfigurationError(f"Invalid allowed.{key}: {value!r}")
    if "risk" in data and data["risk"] not in [r.value for r in PolicyRisk]:
        raise PolicyConfigurationError("Invalid risk")


@dataclass
class AllowedConfig:
    filesystem: str = "workspace"    # "workspace" | "read_only" | "scratch" | "none"
    git: str = "read/write"          # "read/write" | "read" | "none"
    network: str = "none"            # "none" | "internal" | "external"
    tools: List[str] = field(default_factory=lambda: ["*"])
    commands: List[str] = field(default_factory=lambda: ["*"])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filesystem": self.filesystem,
            "git": self.git,
            "network": self.network,
            "tools": list(self.tools),
            "commands": list(self.commands),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AllowedConfig":
        tools_val = data.get("tools", ["*"])
        if isinstance(tools_val, str):
            tools_val = [tools_val]
        cmds_val = data.get("commands", ["*"])
        if isinstance(cmds_val, str):
            cmds_val = [cmds_val]
        return cls(
            filesystem=str(data.get("filesystem", "workspace")),
            git=str(data.get("git", "read/write")),
            network=str(data.get("network", "none")),
            tools=list(tools_val),
            commands=list(cmds_val),
        )


@dataclass
class RequiresApprovalConfig:
    commit: bool = True
    pull_request: bool = True
    deployment: bool = True
    external_call: bool = False
    secret_access: bool = True
    custom_actions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commit": self.commit,
            "pull_request": self.pull_request,
            "deployment": self.deployment,
            "external_call": self.external_call,
            "secret_access": self.secret_access,
            "custom_actions": list(self.custom_actions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RequiresApprovalConfig":
        return cls(
            commit=bool(data.get("commit", True)),
            pull_request=bool(data.get("pull_request", True)),
            deployment=bool(data.get("deployment", True)),
            external_call=bool(data.get("external_call", False)),
            secret_access=bool(data.get("secret_access", True)),
            custom_actions=list(data.get("custom_actions", [])),
        )


DEFAULT_FORBIDDEN_CREDENTIAL_PATTERNS = [
    ".env*",
    "**/.env*",
    "**/*.pem",
    "**/*.key",
    "**/id_rsa*",
    "**/.aws/*",
    "**/.ssh/*",
    "**/.config/gcloud/*",
    "**/credentials.json",
    "**/service-account*.json",
    "**/token.txt",
    "**/secrets.yaml",
    "**/secrets.json",
]


@dataclass
class ForbiddenConfig:
    production: bool = True
    credentials: bool = True
    force_push: bool = True
    network_egress: bool = False
    paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "production": self.production,
            "credentials": self.credentials,
            "force_push": self.force_push,
            "network_egress": self.network_egress,
            "paths": list(self.paths),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForbiddenConfig":
        paths = list(data.get("paths", []))

        return cls(
            production=bool(data.get("production", True)),
            credentials=bool(data.get("credentials", True)),
            force_push=bool(data.get("force_push", True)),
            network_egress=bool(data.get("network_egress", False)),
            paths=paths,
        )


@dataclass
class EnterprisePolicy:
    """An organization or skill-level security policy contract."""

    skill: str = "default"
    risk: PolicyRisk = PolicyRisk.HIGH
    allowed: AllowedConfig = field(default_factory=AllowedConfig)
    requires_approval: RequiresApprovalConfig = field(default_factory=RequiresApprovalConfig)
    forbidden: ForbiddenConfig = field(default_factory=ForbiddenConfig)
    name: str = "enterprise_default"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "skill": self.skill,
            "risk": self.risk.value if hasattr(self.risk, "value") else str(self.risk),
            "allowed": self.allowed.to_dict(),
            "requires_approval": self.requires_approval.to_dict(),
            "forbidden": self.forbidden.to_dict(),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], default_skill: str = "default") -> "EnterprisePolicy":
        _validate_policy(data)
        raw_risk = data.get("risk", "high")
        try:
            risk = PolicyRisk(raw_risk)
        except Exception:
            risk = PolicyRisk.HIGH

        return cls(
            skill=str(data.get("skill", default_skill)),
            risk=risk,
            allowed=AllowedConfig.from_dict(dict(data.get("allowed", {}))),
            requires_approval=RequiresApprovalConfig.from_dict(dict(data.get("requires_approval", {}))),
            forbidden=ForbiddenConfig.from_dict(dict(data.get("forbidden", {}))),
            name=str(data.get("name", f"policy_{data.get('skill', default_skill)}")),
            description=str(data.get("description", "")),
        )


@dataclass
class PolicyDecision:
    """The authoritative result of a policy evaluation."""

    status: PolicyDecisionStatus
    allowed: bool
    reason: str
    rule_violated: Optional[str] = None
    required_approval_type: Optional[str] = None
    skill: str = "default"
    risk: str = "high"
    policy_source: str = "organization"
    timestamp: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "allowed": self.allowed,
            "reason": self.reason,
            "rule_violated": self.rule_violated,
            "required_approval_type": self.required_approval_type,
            "skill": self.skill,
            "risk": self.risk,
            "policy_source": self.policy_source,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Policy Inheritance & Monotonicity Engine
# ---------------------------------------------------------------------------

def merge_and_validate_policy(
    org_policy: EnterprisePolicy,
    skill_policy: EnterprisePolicy,
) -> EnterprisePolicy:
    """
    Merge a skill-level policy into an organization baseline policy.

    Enforces the Enterprise Monotonicity Law:
    Skills CANNOT relax forbidden invariants or bypass required approvals!
    Skills can only specialize or further restrict permissions.
    """
    _validate_policy(org_policy.to_dict())
    _validate_policy(skill_policy.to_dict())
    skill_name = skill_policy.skill
    for key in ("tools", "commands"):
        parent = getattr(org_policy.allowed, key)
        child = getattr(skill_policy.allowed, key)
        if parent != ["*"] and child != ["*"] and not set(child).issubset(parent):
            raise PolicyInheritanceError(f"Skill '{skill_name}' cannot widen allowed.{key}")
    network_levels = {"none": 0, "internal": 1, "external": 2}
    if network_levels[skill_policy.allowed.network] > network_levels[org_policy.allowed.network]:
        raise PolicyInheritanceError(f"Skill '{skill_name}' cannot widen allowed.network")

    # 1. Monotonicity: Forbidden rules can NEVER be relaxed
    if org_policy.forbidden.credentials and not skill_policy.forbidden.credentials:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot relax forbidden.credentials mandated by organization policy."
        )
    if org_policy.forbidden.production and not skill_policy.forbidden.production:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot relax forbidden.production mandated by organization policy."
        )
    if org_policy.forbidden.force_push and not skill_policy.forbidden.force_push:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot relax forbidden.force_push mandated by organization policy."
        )

    # 2. Monotonicity: Required approvals cannot be bypassed
    if org_policy.requires_approval.commit and not skill_policy.requires_approval.commit:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot bypass requires_approval.commit mandated by organization policy."
        )
    if org_policy.requires_approval.pull_request and not skill_policy.requires_approval.pull_request:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot bypass requires_approval.pull_request mandated by organization policy."
        )
    if org_policy.requires_approval.deployment and not skill_policy.requires_approval.deployment:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot bypass requires_approval.deployment mandated by organization policy."
        )

    # 3. Monotonicity: Allowed scopes can only be narrowed (least privilege)
    git_levels = {"none": 0, "read": 1, "read/write": 2}
    org_git_level = git_levels.get(org_policy.allowed.git, 2)
    skill_git_level = git_levels.get(skill_policy.allowed.git, 2)
    if skill_git_level > org_git_level:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot escalate git scope from '{org_policy.allowed.git}' to '{skill_policy.allowed.git}'."
        )

    fs_levels = {"none": 0, "read_only": 1, "scratch": 2, "workspace": 3}
    org_fs_level = fs_levels.get(org_policy.allowed.filesystem, 3)
    skill_fs_level = fs_levels.get(skill_policy.allowed.filesystem, 3)
    if skill_fs_level > org_fs_level:
        raise PolicyInheritanceError(
            f"Skill '{skill_name}' cannot escalate filesystem scope from '{org_policy.allowed.filesystem}' to '{skill_policy.allowed.filesystem}'."
        )

    # Merge combined forbidden paths
    merged_paths = list(set(org_policy.forbidden.paths) | set(skill_policy.forbidden.paths))

    effective = EnterprisePolicy(
        skill=skill_name,
        risk=skill_policy.risk,
        allowed=AllowedConfig(
            filesystem=skill_policy.allowed.filesystem,
            git=skill_policy.allowed.git,
            network=skill_policy.allowed.network if org_policy.allowed.network != "none" else "none",
            tools=skill_policy.allowed.tools if skill_policy.allowed.tools != ["*"] else org_policy.allowed.tools,
            commands=skill_policy.allowed.commands if skill_policy.allowed.commands != ["*"] else org_policy.allowed.commands,
        ),
        requires_approval=RequiresApprovalConfig(
            commit=org_policy.requires_approval.commit or skill_policy.requires_approval.commit,
            pull_request=org_policy.requires_approval.pull_request or skill_policy.requires_approval.pull_request,
            deployment=org_policy.requires_approval.deployment or skill_policy.requires_approval.deployment,
            external_call=org_policy.requires_approval.external_call or skill_policy.requires_approval.external_call,
            secret_access=org_policy.requires_approval.secret_access or skill_policy.requires_approval.secret_access,
            custom_actions=list(set(org_policy.requires_approval.custom_actions) | set(skill_policy.requires_approval.custom_actions)),
        ),
        forbidden=ForbiddenConfig(
            production=org_policy.forbidden.production or skill_policy.forbidden.production,
            credentials=org_policy.forbidden.credentials or skill_policy.forbidden.credentials,
            force_push=org_policy.forbidden.force_push or skill_policy.forbidden.force_push,
            network_egress=org_policy.forbidden.network_egress or skill_policy.forbidden.network_egress,
            paths=merged_paths,
        ),
        name=f"effective_{skill_name}",
        description=f"Effective policy for {skill_name} inherited from organization baseline",
    )
    return effective


# ---------------------------------------------------------------------------
# Zero-Dependency YAML / JSON Policy Parser
# ---------------------------------------------------------------------------

def parse_yaml_subset(text: str) -> Dict[str, Any]:
    """Zero-dependency parser for standard YAML subset (mappings, lists, primitives)."""
    lines = [line.rstrip() for line in text.splitlines()]
    clean_lines: List[Tuple[int, str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        clean_lines.append((indent, stripped))

    def parse_value(val_str: str) -> Any:
        v = val_str.strip()
        if v.lower() == "true":
            return True
        if v.lower() == "false":
            return False
        if v.lower() in ("null", "~"):
            return None
        if re.match(r"^-?\d+$", v):
            return int(v)
        if re.match(r"^-?\d+\.\d+$", v):
            return float(v)
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            return v[1:-1]
        return v

    def parse_block(idx: int, current_indent: int) -> Tuple[Any, int]:
        result: Dict[str, Any] = {}
        is_list = False
        list_items: List[Any] = []

        while idx < len(clean_lines):
            indent, line = clean_lines[idx]
            if indent < current_indent:
                break

            if indent != current_indent:
                raise PolicyConfigurationError("Invalid YAML indentation")
            if line.startswith("- "):
                if result:
                    raise PolicyConfigurationError("Mixed YAML mapping and list")
                is_list = True
                val_part = line[2:].strip()
                if not val_part:
                    sub_res, next_idx = parse_block(idx + 1, indent + 2)
                    list_items.append(sub_res)
                    idx = next_idx
                    continue
                else:
                    list_items.append(parse_value(val_part))
                    idx += 1
                    continue

            if ":" in line:
                colon_idx = line.index(":")
                key = line[:colon_idx].strip()
                if not key or key in result or is_list:
                    raise PolicyConfigurationError("Invalid or duplicate YAML key")
                val_part = line[colon_idx + 1:].strip()

                if not val_part:
                    sub_res, next_idx = parse_block(idx + 1, indent + 2)
                    result[key] = sub_res
                    idx = next_idx
                    continue
                else:
                    result[key] = parse_value(val_part)
                    idx += 1
                    continue

            raise PolicyConfigurationError(f"Unsupported YAML syntax: {line}")

        return (list_items if is_list else result), idx

    parsed, consumed = parse_block(0, clean_lines[0][0] if clean_lines else 0)
    if not isinstance(parsed, dict) or consumed != len(clean_lines):
        raise PolicyConfigurationError("Policy YAML must be a mapping")
    return parsed


# ---------------------------------------------------------------------------
# Policy Registry & Loader
# ---------------------------------------------------------------------------

class PolicyRegistry:
    """Maintains organization baseline and per-skill registered policies."""

    def __init__(self, org_policy: Optional[EnterprisePolicy] = None) -> None:
        self.org_policy = org_policy or EnterprisePolicy(
            skill="org_default",
            risk=PolicyRisk.HIGH,
            allowed=AllowedConfig(filesystem="workspace", git="read/write"),
            requires_approval=RequiresApprovalConfig(commit=True, pull_request=True, deployment=True),
            forbidden=ForbiddenConfig(production=True, credentials=True, force_push=True),
            name="organization_default",
        )
        _validate_policy(self.org_policy.to_dict())
        self.skill_policies: Dict[str, EnterprisePolicy] = {}

    def register_skill_policy(self, policy: EnterprisePolicy) -> EnterprisePolicy:
        """Register a skill policy after verifying it does not violate the monotonicity law."""
        effective = merge_and_validate_policy(self.org_policy, policy)
        self.skill_policies[policy.skill] = effective
        return effective

    def get_policy_for_skill(self, skill_name: str) -> EnterprisePolicy:
        """Retrieve the effective inherited policy for a named skill."""
        if skill_name in self.skill_policies:
            return self.skill_policies[skill_name]
        # Return default policy inheriting from org baseline
        default_for_skill = EnterprisePolicy(
            skill=skill_name,
            risk=self.org_policy.risk,
            allowed=AllowedConfig(**self.org_policy.allowed.to_dict()),
            requires_approval=RequiresApprovalConfig(**self.org_policy.requires_approval.to_dict()),
            forbidden=ForbiddenConfig(**self.org_policy.forbidden.to_dict()),
            name=f"default_{skill_name}",
        )
        return default_for_skill

    @classmethod
    def load_from_text(cls, content: str) -> "PolicyRegistry":
        """Load from either YAML or JSON string."""
        data: Dict[str, Any] = {}
        content_stripped = textwrap.dedent(content).strip()
        if content_stripped.startswith("{"):
            data = json.loads(content_stripped)
        else:
            data = parse_yaml_subset(content_stripped)

        # Extract top-level policy block if present
        if not isinstance(data, dict) or not data:
            raise PolicyConfigurationError("Policy must be a nonempty mapping")
        raw_policy = data.get("policy", data)
        _validate_policy(raw_policy)

        # Check if this is a single skill policy (e.g. skill: ship)
        declared_skill = raw_policy.get("skill")
        org_policy_data = dict(raw_policy)

        org_policy = EnterprisePolicy.from_dict(org_policy_data, default_skill="org_default")
        registry = cls(org_policy=org_policy)

        # Register skill-specific policy if explicit skill was specified
        if declared_skill and declared_skill not in ("org_default", "default", "*"):
            skill_pol = EnterprisePolicy.from_dict(raw_policy, default_skill=declared_skill)
            registry.register_skill_policy(skill_pol)

        # Register additional skills if 'skills' mapping is provided
        skills_dict = raw_policy.get("skills", {})
        if not isinstance(skills_dict, dict):
            raise PolicyConfigurationError("skills must be a mapping")
        if isinstance(skills_dict, dict):
            for s_name, s_data in skills_dict.items():
                _validate_policy(s_data)
                inherited = org_policy.to_dict()
                inherited["skill"] = s_name
                for key, value in s_data.items():
                    if key in ("allowed", "requires_approval", "forbidden"):
                        inherited[key].update(value)
                    else:
                        inherited[key] = value
                sp = EnterprisePolicy.from_dict(inherited, default_skill=s_name)
                registry.register_skill_policy(sp)

        return registry

    @classmethod
    def load_from_repo(cls, repo_root: Path) -> "PolicyRegistry":
        """Discover and load policy file from repository root in standard precedence."""
        root = Path(repo_root).resolve()
        candidates = [
            root / ".agentflow" / "policy.yaml",
            root / ".agentflow" / "policy.yml",
            root / ".agentflow" / "policy.json",
            root / "policy.yaml",
            root / "policy.yml",
            root / "policy.json",
        ]
        for c in candidates:
            if c.exists():
                return cls.load_from_text(c.read_text(encoding="utf-8"))

        # Fallback: check if .agentflow.json contains a 'policy' key
        af_json = root / ".agentflow.json"
        if af_json.exists():
            data = json.loads(af_json.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise PolicyConfigurationError(".agentflow.json must be a mapping")
            if "policy" in data:
                return cls.load_from_text(json.dumps(data["policy"]))

        # Return default registry
        return cls()


# ---------------------------------------------------------------------------
# Enterprise Policy Engine (Action Enforcement)
# ---------------------------------------------------------------------------

class EnterprisePolicyEngine:
    """
    Authoritative enforcement engine for enterprise SDLC policies.
    Evaluates filesystem access, git actions, command execution, and tool calls.
    """

    def __init__(
        self,
        repo_root: Path,
        registry: Optional[PolicyRegistry] = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.registry = registry or PolicyRegistry.load_from_repo(self.repo_root)

    def get_effective_policy(self, skill: str) -> EnterprisePolicy:
        return self.registry.get_policy_for_skill(skill)

    @staticmethod
    def _deny(policy, reason, rule, approval=None):
        return PolicyDecision(
            status=PolicyDecisionStatus.REQUIRES_APPROVAL if approval else PolicyDecisionStatus.DENIED,
            allowed=False, reason=reason, rule_violated=rule,
            required_approval_type=approval, skill=policy.skill,
            risk=policy.risk.value, policy_source=policy.name,
        )

    def evaluate_external(self, skill, operation, approval_granted=False):
        """Evaluate typed external actions; an existing capability cannot override policy.

        Internal destinations cannot be authenticated from a URL alone. Until a
        trusted host supplies destination classification, internal scope fails closed.
        """
        policy = self.get_effective_policy(skill)
        if operation == "SECRET_READ":
            if policy.forbidden.credentials:
                return self._deny(policy, "Secret access forbidden", "forbidden.credentials")
            if policy.requires_approval.secret_access and not approval_granted:
                return self._deny(policy, "Secret access requires approval", "requires_approval.secret_access", "SECRET_APPROVAL")
        else:
            if operation == "CLOUD_MUTATE" and policy.forbidden.production:
                return self._deny(policy, "Cloud destination requires trusted production classification", "forbidden.production")
            if policy.forbidden.network_egress or policy.allowed.network != "external":
                return self._deny(policy, "External access forbidden or destination not classified", "allowed.network")
            if policy.requires_approval.external_call and not approval_granted:
                return self._deny(policy, "External access requires approval", "requires_approval.external_call", "EXTERNAL_APPROVAL")
            if operation == "CLOUD_MUTATE":
                if policy.requires_approval.deployment and not approval_granted:
                    return self._deny(policy, "Deployment requires approval", "requires_approval.deployment", "DEPLOYMENT_APPROVAL")
        return PolicyDecision(PolicyDecisionStatus.ALLOWED, True, "External action permitted", skill=skill)

    # ------------------------------------------------------------------ #
    # Filesystem Evaluation                                               #
    # ------------------------------------------------------------------ #

    def evaluate_filesystem(
        self,
        skill: str,
        path: str,
        mode: str = "read",  # "read" | "write" | "delete"
    ) -> PolicyDecision:
        """
        Evaluate access to a filesystem target.
        Enforces forbidden credential patterns, path escapes, and filesystem scope.
        """
        policy = self.get_effective_policy(skill)
        risk_str = policy.risk.value
        clean_path = path.replace("\\", "/")
        if mode not in {"read", "write", "delete"}:
            return self._deny(policy, "Invalid filesystem mode", "allowed.filesystem")
        try:
            target = Path(clean_path)
            resolved = (target if target.is_absolute() else self.repo_root / target).resolve()
        except (OSError, RuntimeError, ValueError):
            return self._deny(policy, "Cannot resolve filesystem target", "allowed.filesystem")
        if not resolved.is_relative_to(self.repo_root):
            return self._deny(policy, "Path escapes repository workspace", "allowed.filesystem: workspace_escape")
        original_path = clean_path
        clean_path = resolved.as_posix()


        # Custom exclusions are independent of the credential-access toggle.
        # Match both canonical relative and absolute forms, so aliases cannot hide
        # a protected target. Retain the supplied path to also protect alias names.
        candidates = (original_path, clean_path, resolved.relative_to(self.repo_root).as_posix(), resolved.name)
        groups = [(policy.forbidden.paths, "forbidden.paths")]
        if policy.forbidden.credentials:
            groups.append((DEFAULT_FORBIDDEN_CREDENTIAL_PATTERNS, "forbidden.credentials"))
        for patterns, rule in groups:
            for pattern in patterns:
                pattern = pattern.replace("\\", "/")
                variants = [pattern, pattern[3:]] if pattern.startswith("**/") else [pattern]
                if any(fnmatch.fnmatchcase(candidate, pat) for candidate in candidates for pat in variants):
                    return self._deny(policy, f"Access to protected file '{original_path}' is forbidden", rule)

        # 2. Scope: none
        if policy.allowed.filesystem == "none":
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason=f"Filesystem access is completely disabled for skill '{skill}' by policy.",
                rule_violated="allowed.filesystem: none",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 3. Scope: read_only
        if policy.allowed.filesystem == "read_only" and mode in ("write", "delete"):
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason=f"Filesystem mutations forbidden: skill '{skill}' is configured with read_only filesystem policy.",
                rule_violated="allowed.filesystem: read_only",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # Scratch targets must remain under a literal in-workspace scratch root.
        if policy.allowed.filesystem == "scratch" and mode in ("write", "delete"):
            roots = [self.repo_root / ".scratch", self.repo_root / "scratch"]
            if not any(resolved.is_relative_to(root) for root in roots):
                return self._deny(policy, "File mutation outside scratch area", "allowed.filesystem: scratch")

        return PolicyDecision(
            status=PolicyDecisionStatus.ALLOWED,
            allowed=True,
            reason=f"Filesystem access to '{clean_path}' permitted by {policy.name}.",
            skill=skill,
            risk=risk_str,
            policy_source=policy.name,
        )

    # ------------------------------------------------------------------ #
    # Git Evaluation                                                      #
    # ------------------------------------------------------------------ #

    def evaluate_git(
        self,
        skill: str,
        operation: str,  # "commit" | "pull_request" | "push" | "force_push" | "read" | "branch"
        target_branch: Optional[str] = None,
        approval_granted: bool = False,
    ) -> PolicyDecision:
        """
        Evaluate git operation.
        Enforces approval gates (commit, PR), forbidden force_push, and read-only limits.
        """
        policy = self.get_effective_policy(skill)
        risk_str = policy.risk.value
        op = operation.lower().strip()

        # 1. Force push forbidden invariant
        if op in ("force_push", "push_force") and policy.forbidden.force_push:
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason="Git force-pushing is strictly forbidden by enterprise policy.",
                rule_violated="forbidden.force_push",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 2. Production branch mutation invariant
        if policy.forbidden.production and target_branch in ("production", "prod"):
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason=f"Direct mutations or pushes to production branch '{target_branch}' are forbidden by enterprise policy.",
                rule_violated="forbidden.production",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 3. Git scope: none
        if policy.allowed.git == "none":
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason=f"Git access is disabled for skill '{skill}' by policy.",
                rule_violated="allowed.git: none",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 4. Git scope: read (blocks commits, pushes, branches)
        if policy.allowed.git == "read" and op != "read":
            return PolicyDecision(
                status=PolicyDecisionStatus.DENIED,
                allowed=False,
                reason=f"Git mutations forbidden: skill '{skill}' has read-only git policy.",
                rule_violated="allowed.git: read",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 5. Requires Approval: commit
        if op == "commit" and policy.requires_approval.commit and not approval_granted:
            return PolicyDecision(
                status=PolicyDecisionStatus.REQUIRES_APPROVAL,
                allowed=False,
                reason="Git commit requires explicit human authorization under enterprise policy.",
                required_approval_type="COMMIT_APPROVAL",
                rule_violated="requires_approval.commit",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        # 6. Requires Approval: pull_request
        if op in ("pull_request", "pr") and policy.requires_approval.pull_request and not approval_granted:
            return PolicyDecision(
                status=PolicyDecisionStatus.REQUIRES_APPROVAL,
                allowed=False,
                reason="Pull request creation requires explicit human authorization under enterprise policy.",
                required_approval_type="PULL_REQUEST_APPROVAL",
                rule_violated="requires_approval.pull_request",
                skill=skill,
                risk=risk_str,
                policy_source=policy.name,
            )

        return PolicyDecision(
            status=PolicyDecisionStatus.ALLOWED,
            allowed=True,
            reason=f"Git operation '{op}' permitted by {policy.name}.",
            skill=skill,
            risk=risk_str,
            policy_source=policy.name,
        )

    # ------------------------------------------------------------------ #
    # Command Evaluation                                                 #
    # ------------------------------------------------------------------ #

    def evaluate_command(
        self,
        skill: str,
        command: str,
        approval_granted: bool = False,
    ) -> PolicyDecision:
        """
        Evaluate shell command before host execution.
        Intercepts credential extraction, git operations, and production deployments.
        """
        policy = self.get_effective_policy(skill)
        risk_str = policy.risk.value
        cmd_clean = command.strip()
        cmd_lower = cmd_clean.lower()

        # Exact full-command allowlists, never prefix or glob matching.
        if policy.allowed.commands != ["*"] and cmd_clean not in policy.allowed.commands:
            return self._deny(policy, "Command is not allowlisted", "allowed.commands")
        # This seam accepts simple invocations, not a shell language. Scripts still
        # require host sandboxing; approval here does not constrain their effects.
        if any(c in cmd_clean for c in (";", "&", "|", "<", ">", "`", "$", "\n", "\r")):
            return self._deny(policy, "Shell composition requires a sandboxed host adapter", "allowed.commands")
        try:
            argv = shlex.split(cmd_clean)
        except ValueError:
            return self._deny(policy, "Invalid command syntax", "allowed.commands")
        if not argv:
            return self._deny(policy, "Empty command", "allowed.commands")
        executable = Path(argv[0]).name
        if executable in {"sh", "bash", "zsh", "fish", "env", "sudo", "xargs"}:
            return self._deny(policy, "Indirect shell execution requires a host adapter", "allowed.commands")
        if executable == "git":
            args = argv[1:]
            while args and args[0].startswith("-"):
                option = args.pop(0)
                if option == "-C" and args:
                    scope = self.evaluate_filesystem(skill, args.pop(0))
                    if not scope.allowed:
                        return scope
                elif option in {"--no-pager", "--literal-pathspecs"}:
                    continue
                else:
                    return self._deny(policy, "Unsupported Git global option", "allowed.git")
            if not args:
                return self._deny(policy, "Missing Git operation", "allowed.git")
            op = args[0]
            reads = {"status", "diff", "log", "show", "rev-parse", "ls-files", "ls-tree"}
            known = reads | {"commit", "push", "add", "reset", "restore", "checkout", "switch", "branch", "tag", "merge", "rebase", "fetch", "pull", "clone", "clean", "rm", "mv", "stash"}
            if op not in known:
                return self._deny(policy, "Unknown Git operation or alias", "allowed.git")
            force = op == "push" and any(a.startswith("--force") or (a.startswith("-") and not a.startswith("--") and "f" in a) or a.startswith("+") for a in args[1:])
            decision = self.evaluate_git(skill, "force_push" if force else "read" if op in reads else op,
                                         approval_granted=approval_granted)
            if not decision.allowed:
                return decision
            if op == "push" and policy.forbidden.production:
                # Implicit/configured destinations and wildcard refspecs cannot be
                # classified from argv. Require explicit remote + destination(s).
                operands = [arg for arg in args[1:] if not arg.startswith("-")]
                unsupported_options = [arg for arg in args[1:] if arg.startswith("-")
                                       and arg not in {"--force", "--force-with-lease", "-f"}]
                if unsupported_options or len(operands) < 2:
                    return self._deny(policy, "Push requires explicit, classifiable destinations", "forbidden.production")
                for refspec in operands[1:]:
                    destination = refspec.lstrip("+").rsplit(":", 1)[-1]
                    if destination.startswith("refs/heads/"):
                        destination = destination[len("refs/heads/"):]
                    if not destination or destination == "HEAD" or any(c in destination for c in "*?["):
                        return self._deny(policy, "Unclassified push destination", "forbidden.production")
                    decision = self.evaluate_git(skill, "push", target_branch=destination,
                                                 approval_granted=approval_granted)
                    if not decision.allowed:
                        return decision
            if op in {"push", "fetch", "pull", "clone"}:
                decision = self.evaluate_external(skill, "NETWORK_WRITE", approval_granted)
                if not decision.allowed:
                    return decision
        if executable in {"curl", "wget", "ssh", "scp", "sftp", "rsync"}:
            decision = self.evaluate_external(skill, "NETWORK_WRITE", approval_granted)
            if not decision.allowed:
                return decision

        # 1. Intercept Credential Access Commands
        if policy.forbidden.credentials:
            cred_keywords = [
                r"\.env\b",
                r"id_rsa\b",
                r"\.aws/credentials\b",
                r"\.ssh/\w+\b",
                r"\bcredentials\.json\b",
                r"\bexport GITHUB_TOKEN\b",
                r"\bexport AWS_SECRET\b",
            ]
            for kw in cred_keywords:
                if re.search(kw, cmd_clean, re.IGNORECASE):
                    return PolicyDecision(
                        status=PolicyDecisionStatus.DENIED,
                        allowed=False,
                        reason=f"Command references credentials/secrets forbidden by enterprise policy: '{cmd_clean}'",
                        rule_violated="forbidden.credentials",
                        skill=skill,
                        risk=risk_str,
                        policy_source=policy.name,
                    )

        # 2. Intercept Git Force Push
        if "git push" in cmd_lower and ("--force" in cmd_lower or "-f " in cmd_lower or cmd_lower.endswith("-f")):
            if policy.forbidden.force_push:
                return PolicyDecision(
                    status=PolicyDecisionStatus.DENIED,
                    allowed=False,
                    reason="Command attempts 'git push --force' forbidden by enterprise policy.",
                    rule_violated="forbidden.force_push",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )

        # 3. Intercept Git Commit Approval
        if "git commit" in cmd_lower:
            if policy.allowed.git == "read":
                return PolicyDecision(
                    status=PolicyDecisionStatus.DENIED,
                    allowed=False,
                    reason=f"Git commit forbidden: skill '{skill}' has read-only git policy.",
                    rule_violated="allowed.git: read",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )
            if policy.requires_approval.commit and not approval_granted:
                return PolicyDecision(
                    status=PolicyDecisionStatus.REQUIRES_APPROVAL,
                    allowed=False,
                    reason="Command executes 'git commit', which requires human approval.",
                    required_approval_type="COMMIT_APPROVAL",
                    rule_violated="requires_approval.commit",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )

        # Deployment providers can select production via config/context as well
        # as explicit flags. Route mutations through the typed cloud policy gate;
        # approval does not establish a trusted nonproduction classification.
        deployment = (executable == "kubectl" and any(a in {
            "apply", "create", "delete", "patch", "replace", "rollout", "scale", "edit",
            "set", "run", "expose", "label", "annotate", "taint", "drain", "cordon", "uncordon"
        } for a in argv[1:])) or (executable == "terraform" and any(a in {"apply", "destroy", "import"} for a in argv[1:])) or "deploy" in argv[1:]
        if deployment:
            decision = self.evaluate_external(skill, "CLOUD_MUTATE", approval_granted)
            if not decision.allowed:
                return decision

        # 4. Intercept Production Deployments
        if policy.forbidden.production:
            if any(term in cmd_lower for term in ("--env=production", "--env=prod", "--context=prod", "deploy prod", "deploy production")):
                return PolicyDecision(
                    status=PolicyDecisionStatus.DENIED,
                    allowed=False,
                    reason="Direct deployment targeting production environment forbidden by enterprise policy.",
                    rule_violated="forbidden.production",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )

        # 5. Intercept Deployment Approval
        if any(term in cmd_lower for term in ("deploy ", "ship delivery", "terraform apply", "kubectl apply")):
            if policy.requires_approval.deployment and not approval_granted:
                return PolicyDecision(
                    status=PolicyDecisionStatus.REQUIRES_APPROVAL,
                    allowed=False,
                    reason="Deployment command requires human authorization under enterprise policy.",
                    required_approval_type="DEPLOYMENT_APPROVAL",
                    rule_violated="requires_approval.deployment",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )

        return PolicyDecision(
            status=PolicyDecisionStatus.ALLOWED,
            allowed=True,
            reason=f"Command '{cmd_clean[:50]}' permitted by {policy.name}.",
            skill=skill,
            risk=risk_str,
            policy_source=policy.name,
        )

    # ------------------------------------------------------------------ #
    # Tool Call Evaluation                                               #
    # ------------------------------------------------------------------ #

    def evaluate_tool_call(
        self,
        skill: str,
        tool_name: str,
        arguments: Dict[str, Any],
        approval_granted: bool = False,
    ) -> PolicyDecision:
        """Evaluate MCP or harness tool invocation against enterprise policy."""
        policy = self.get_effective_policy(skill)
        risk_str = policy.risk.value

        if policy.allowed.tools != ["*"] and tool_name not in policy.allowed.tools:
            return self._deny(policy, "Tool is not allowlisted", "allowed.tools")

        # Check path argument in filesystem tools
        path_arg = arguments.get("path") or arguments.get("TargetFile") or arguments.get("file_path") or arguments.get("file")
        if path_arg and isinstance(path_arg, str):
            mode = "write" if any(w in tool_name.lower() for w in ("write", "edit", "replace", "delete", "create")) else "read"
            fs_dec = self.evaluate_filesystem(skill, path_arg, mode=mode)
            if not fs_dec.allowed:
                return fs_dec

        # Check command argument in execution tools
        cmd_arg = arguments.get("CommandLine") or arguments.get("command") or arguments.get("cmd")
        if cmd_arg and isinstance(cmd_arg, str):
            return self.evaluate_command(skill, cmd_arg, approval_granted=approval_granted)

        # Check git PR / comment tools
        if "pr" in tool_name.lower().split("_") or "pull_request" in tool_name.lower() or "comment" in tool_name.lower():
            if policy.requires_approval.pull_request and not approval_granted:
                return PolicyDecision(
                    status=PolicyDecisionStatus.REQUIRES_APPROVAL,
                    allowed=False,
                    reason=f"Tool '{tool_name}' performs PR/external action requiring authorization.",
                    required_approval_type="PULL_REQUEST_APPROVAL",
                    rule_violated="requires_approval.pull_request",
                    skill=skill,
                    risk=risk_str,
                    policy_source=policy.name,
                )

        return PolicyDecision(
            status=PolicyDecisionStatus.ALLOWED,
            allowed=True,
            reason=f"Tool call '{tool_name}' permitted by {policy.name}.",
            skill=skill,
            risk=risk_str,
            policy_source=policy.name,
        )
