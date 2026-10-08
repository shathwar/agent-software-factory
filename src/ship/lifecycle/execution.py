"""Host-side execution seam for capability-protected actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from .capabilities import CapabilityManager
from .models import AccessDecision
from .policy import EnterprisePolicyEngine

T = TypeVar("T")


class CapabilityDenied(PermissionError):
    """Raised when a host refuses to perform an unauthorized action."""

    def __init__(self, decision):
        self.decision = decision
        super().__init__(decision.reason)


@dataclass(frozen=True)
class ActionContext:
    agent_id: str
    operation: str
    target: str
    change_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    lease_token: Optional[str] = None
    skill: Optional[str] = "ship"
    approval_granted: bool = False


class CapabilityGuard:
    """Small host-facing seam: authorize an action before its adapter executes it."""

    def __init__(self, repo_root: Path, policy_engine: Optional[EnterprisePolicyEngine] = None):
        self.repo_root = Path(repo_root).resolve()
        self.manager = CapabilityManager(self.repo_root)
        self.policy_engine = policy_engine or EnterprisePolicyEngine(self.repo_root)

    def require(self, context: ActionContext):
        skill = context.skill or "ship"
        op_upper = context.operation.upper()

        # 1. Enterprise Policy Enforcement
        if op_upper == "SECRET_READ":
            pol = self.policy_engine.get_effective_policy(skill)
            if pol.forbidden.credentials:
                decision = AccessDecision(
                    allowed=False,
                    reason=f"Access to credential/secret '{context.target}' is strictly forbidden by enterprise policy.",
                    ring="RING_1_GOVERNANCE",
                    agent_id=context.agent_id,
                    operation=context.operation,
                    target=context.target,
                    violation_code="forbidden.credentials",
                )
                raise CapabilityDenied(decision)

        if op_upper in {"COMMAND", "SHELL", "EXEC", "EXECUTE"}:
            cmd_dec = self.policy_engine.evaluate_command(
                skill=skill,
                command=context.target,
                approval_granted=context.approval_granted,
            )
            if not cmd_dec.allowed:
                decision = AccessDecision(
                    allowed=False,
                    reason=cmd_dec.reason,
                    ring="RING_1_GOVERNANCE",
                    agent_id=context.agent_id,
                    operation=context.operation,
                    target=context.target,
                    violation_code=cmd_dec.rule_violated,
                )
                raise CapabilityDenied(decision)

        if op_upper in {"GITHUB_WRITE", "PULL_REQUEST", "GIT_COMMIT", "GIT_PUSH"}:
            git_op = "commit" if "COMMIT" in op_upper else ("pull_request" if "PULL_REQUEST" in op_upper or op_upper == "GITHUB_WRITE" else "push")
            git_dec = self.policy_engine.evaluate_git(
                skill=skill,
                operation=git_op,
                approval_granted=context.approval_granted,
            )
            if not git_dec.allowed:
                decision = AccessDecision(
                    allowed=False,
                    reason=git_dec.reason,
                    ring="RING_1_GOVERNANCE",
                    agent_id=context.agent_id,
                    operation=context.operation,
                    target=context.target,
                    violation_code=git_dec.rule_violated,
                )
                raise CapabilityDenied(decision)

        # Filesystem / Target checks (skip remote URLs and schemes)
        if op_upper in {"READ", "FILE_READ", "WRITE", "FILE_WRITE", "WORKSPACE_WRITE", "DELETE", "FILE_DELETE"} or (
            context.target and not (context.target.startswith(("http://", "https://", "arn:", "github:")) or "://" in context.target)
        ):
            mode = "write" if op_upper in {"WRITE", "FILE_WRITE", "WORKSPACE_WRITE", "DELETE", "FILE_DELETE"} else "read"
            fs_dec = self.policy_engine.evaluate_filesystem(
                skill=skill,
                path=context.target,
                mode=mode,
            )
            if not fs_dec.allowed:
                decision = AccessDecision(
                    allowed=False,
                    reason=fs_dec.reason,
                    ring="RING_1_GOVERNANCE",
                    agent_id=context.agent_id,
                    operation=context.operation,
                    target=context.target,
                    violation_code=fs_dec.rule_violated,
                )
                raise CapabilityDenied(decision)

        # 2. Capability Manager fine-grained check
        decision = self.manager.evaluate_access(
            agent_id=context.agent_id,
            operation=context.operation,
            target=context.target,
            change_id=context.change_id,
            task_id=context.task_id,
            session_id=context.session_id,
            lease_token=context.lease_token,
        )
        if not decision.allowed:
            raise CapabilityDenied(decision)
        return decision


class ExternalActionAdapter:
    """Authorize an external effect, then invoke the host/provider implementation.

    Provider SDKs stay outside this package. The callback is deliberately injected so
    tests can prove denied actions never reach a network, vault, cloud, or GitHub client.
    """

    def __init__(self, repo_root: Path):
        self.guard = CapabilityGuard(repo_root)

    def invoke(self, context: ActionContext, action: Callable[[], T]) -> T:
        self.guard.require(context)
        return action()

    def network(self, context: ActionContext, request: Callable[[], T]) -> T:
        if context.operation not in {"NETWORK", "NETWORK_READ", "NETWORK_WRITE"}:
            raise ValueError("network actions require NETWORK, NETWORK_READ, or NETWORK_WRITE")
        return self.invoke(context, request)

    def secret(self, context: ActionContext, read: Callable[[], T]) -> T:
        if context.operation != "SECRET_READ":
            raise ValueError("secret reads require SECRET_READ")
        return self.invoke(context, read)

    def cloud(self, context: ActionContext, mutate: Callable[[], T]) -> T:
        if context.operation != "CLOUD_MUTATE":
            raise ValueError("cloud mutations require CLOUD_MUTATE")
        return self.invoke(context, mutate)

    def github(self, context: ActionContext, mutate: Callable[[], T]) -> T:
        if context.operation != "GITHUB_WRITE":
            raise ValueError("GitHub mutations require GITHUB_WRITE")
        return self.invoke(context, mutate)
