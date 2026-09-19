"""Host-side execution seam for capability-protected actions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from .capabilities import CapabilityManager

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


class CapabilityGuard:
    """Small host-facing seam: authorize an action before its adapter executes it."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.manager = CapabilityManager(self.repo_root)

    def require(self, context: ActionContext):
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
