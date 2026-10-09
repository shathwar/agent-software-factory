"""Secrets management, scrubbing, declaration manifests, and host-bridge broker for AgentFlow."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import os
import re
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass
class SecretRequirement:
    """Declaration of a credential required or optionally requested by a workflow/skill."""
    name: str
    description: str
    source: str = "env"      # "env" | "file" | "vault" | "host"
    optional: bool = False
    rotation_days: int = 0   # 0 = not enforced

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecretRequirement":
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            source=str(data.get("source", "env")),
            optional=bool(data.get("optional", False)),
            rotation_days=int(data.get("rotation_days", 0)),
        )


@dataclass
class SecretManifest:
    """Skill-level or change-level declared secrets requirements."""
    skill: str
    requirements: List[SecretRequirement] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill": self.skill,
            "requirements": [r.to_dict() for r in self.requirements],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecretManifest":
        reqs = [SecretRequirement.from_dict(r) for r in data.get("requirements", [])]
        return cls(skill=str(data.get("skill", "")), requirements=reqs)


class SecretProvider(Protocol):
    """Protocol for checking presence or acquiring indirect references to secrets."""

    def has_secret(self, name: str) -> bool:
        ...

    def get_reference(self, name: str) -> str:
        """Returns safe reference pointer instead of raw plaintext."""
        ...


class EnvSecretProvider:
    """Checks environment variables safely without leaking secret values into logs."""

    def has_secret(self, name: str) -> bool:
        return name in os.environ and bool(os.environ[name])

    def get_reference(self, name: str) -> str:
        return f"${{env:{name}}}"


class SecretsBroker:
    """Manages secret verification, preflight checks, command leakage prevention, and output scrubbing."""

    SCRUB_PATTERNS = [
        re.compile(r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^"\'\s]+)["\']?'),
        re.compile(r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([^"\'\s]+)["\']?'),
        re.compile(r'(?i)(secret|token)\s*[=:]\s*["\']?([^"\'\s]+)["\']?'),
        re.compile(r'(?i)(aws_secret_access_key)\s*[=:]\s*["\']?([^"\'\s]+)["\']?'),
        re.compile(r'(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}'),          # GitHub PAT
        re.compile(r'sk-[A-Za-z0-9]{32,}'),                                  # OpenAI key
        re.compile(r'AIzaSy[A-Za-z0-9\-_]{33}'),                              # Google API key
        re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
        re.compile(r'(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*'),                   # Bearer token
    ]

    DANGEROUS_ENV_COMMANDS = {
        "env", "printenv", "export", "set", "compgen",
    }

    def __init__(self, provider: Optional[SecretProvider] = None):
        self.provider: SecretProvider = provider or EnvSecretProvider()

    def check_preflight(self, manifest: SecretManifest) -> Tuple[bool, List[str]]:
        """Verify all non-optional secrets are present without revealing their values."""
        missing = []
        for req in manifest.requirements:
            if not req.optional and not self.provider.has_secret(req.name):
                missing.append(f"{req.name} ({req.description})")
        return (len(missing) == 0, missing)

    def scrub_text(self, text: str) -> str:
        """Redact known secret patterns from output text, tool responses, and diffs."""
        if not text:
            return ""
        scrubbed = text
        for pat in self.SCRUB_PATTERNS:
            def _repl(match):
                # If groups exist, preserve key name and redact value
                if match.groups() and len(match.groups()) >= 2:
                    return f"{match.group(1)}=[REDACTED]"
                return "[REDACTED]"
            scrubbed = pat.sub(_repl, scrubbed)
        return scrubbed

    def scrub_value(self, value: Any) -> Any:
        """Copy JSON-compatible output, redacting strings at every depth."""
        if isinstance(value, str):
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {self.scrub_text(key) if isinstance(key, str) else key: self.scrub_value(item)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub_value(item) for item in value]
        return value

    def inspect_command(self, command: str) -> Tuple[bool, Optional[str]]:
        """Inspect a shell command for attempts to dump credentials or inject raw secrets.

        Returns (allowed, reason_if_blocked).
        """
        cmd_clean = command.strip()
        parts = cmd_clean.split()
        if not parts:
            return True, None

        first = parts[0].split("/")[-1].lower()
        if first in self.DANGEROUS_ENV_COMMANDS and len(parts) == 1:
            return False, f"Command '{first}' dumps full process environment and is blocked by SecretsBroker policy."

        # Check for piping env or redirecting /proc/*/environ
        if "environ" in cmd_clean or "export -p" in cmd_clean:
            return False, "Command inspects environment variables and is blocked by SecretsBroker policy."

        # Check if command line contains inline secrets
        for pat in self.SCRUB_PATTERNS:
            if pat.search(cmd_clean):
                return False, "Command contains potential plaintext secret credentials; use environment references."

        return True, None
