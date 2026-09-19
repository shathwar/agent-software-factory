"""Durable Authorization Objects & Approval Lifecycle Management.

Enforces:
  Request -> Approval -> Capability -> Action
Guarantees:
  - Durable cryptographic authorization objects
  - Non-transferability across agents (agent-bound)
  - Non-transferability across changes (change-bound)
  - Scope-limited resources and action limitation
  - Expiration (TTL) and Revocation enforcement
"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .ledger import FileLedgerStore
from .models import ApprovalRequest, DurableApproval


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _is_expired(expires_at: Optional[str], now: Optional[datetime] = None) -> bool:
    if not expires_at:
        return False
    now_dt = now or _now_utc()
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return now_dt > exp
    except Exception:
        return False


def compute_approval_signature(
    approval_id: str,
    human: str,
    agent: str,
    change: str,
    action: str,
    scope: str,
    issued_at: str,
    expires_at: Optional[str],
    reason: str,
) -> str:
    """Compute deterministic SHA-256 digest over canonical authorization fields."""
    canonical = (
        f"{approval_id}|{human.strip()}|{agent.strip()}|{change.strip()}|"
        f"{action.strip().upper()}|{scope.strip()}|{issued_at.strip()}|"
        f"{(expires_at or '').strip()}|{reason.strip()}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalManager:
    """Manages durable approval requests, human reviews, and cryptographic authorization objects."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def _resolve_change_id(self, change_id: Optional[str] = None) -> str:
        if change_id:
            return change_id
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        active = ledger.get("active_change_id")
        if not active:
            raise ValueError("No active change found in ledger")
        return str(active)

    def create_request(
        self,
        agent: str,
        action: str,
        scope: str,
        reason: str,
        change: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """Step 1: Agent creates a durable authorization request (Status: PENDING)."""
        cid = self._resolve_change_id(change)
        now_iso = _now_iso()
        req_id = f"req-{uuid.uuid4().hex[:12]}"

        req = ApprovalRequest(
            request_id=req_id,
            agent=agent.strip(),
            change=cid,
            action=action.strip().upper(),
            scope=scope.strip(),
            reason=reason.strip(),
            requested_at=now_iso,
            status="PENDING",
            metadata=metadata or {},
        )

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(cid, {})
            apprs = ch.setdefault("approvals", {})
            requests = apprs.setdefault("requests", {})
            requests[req_id] = req.to_dict()
            FileLedgerStore.save(self.repo_root, ledger)

        return req

    def approve_request(
        self,
        request_id: str,
        human: str,
        ttl_seconds: Optional[int] = None,
        reason: Optional[str] = None,
        change_id: Optional[str] = None,
    ) -> DurableApproval:
        """Step 2: Human supervisor approves a pending request, issuing a durable authorization."""
        cid = self._resolve_change_id(change_id)
        now_dt = _now_utc()
        now_iso = now_dt.isoformat()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(cid, {})
            apprs = ch.setdefault("approvals", {})
            requests = apprs.setdefault("requests", {})

            if request_id not in requests:
                raise KeyError(f"Approval request '{request_id}' not found in change '{cid}'")

            req_data = requests[request_id]
            if req_data.get("status") != "PENDING":
                raise ValueError(f"Request '{request_id}' is '{req_data.get('status')}', not 'PENDING'")

            expires_at = None
            if ttl_seconds and ttl_seconds > 0:
                expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

            appr_id = f"appr-{uuid.uuid4().hex[:12]}"
            effective_reason = reason.strip() if reason else req_data.get("reason", "")

            signature = compute_approval_signature(
                approval_id=appr_id,
                human=human,
                agent=req_data["agent"],
                change=cid,
                action=req_data["action"],
                scope=req_data["scope"],
                issued_at=now_iso,
                expires_at=expires_at,
                reason=effective_reason,
            )

            approval = DurableApproval(
                approval_id=appr_id,
                human=human.strip(),
                agent=req_data["agent"],
                change=cid,
                action=req_data["action"],
                scope=req_data["scope"],
                issued_at=now_iso,
                expires_at=expires_at,
                reason=effective_reason,
                revoked=False,
                signature=signature,
                metadata={"request_id": request_id},
            )

            # Update request
            req_data["status"] = "APPROVED"
            req_data["approval_id"] = appr_id
            req_data["reviewed_by"] = human.strip()
            req_data["reviewed_at"] = now_iso

            # Store authorization
            authorizations = apprs.setdefault("authorizations", {})
            authorizations[appr_id] = approval.to_dict()

            FileLedgerStore.save(self.repo_root, ledger)

        return approval

    def issue_direct_approval(
        self,
        human: str,
        agent: str,
        action: str,
        scope: str,
        reason: str,
        ttl_seconds: Optional[int] = None,
        change: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DurableApproval:
        """Direct issuance of a durable authorization object by a human supervisor."""
        cid = self._resolve_change_id(change)
        now_dt = _now_utc()
        now_iso = now_dt.isoformat()

        expires_at = None
        if ttl_seconds and ttl_seconds > 0:
            expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

        appr_id = f"appr-{uuid.uuid4().hex[:12]}"
        signature = compute_approval_signature(
            approval_id=appr_id,
            human=human,
            agent=agent,
            change=cid,
            action=action,
            scope=scope,
            issued_at=now_iso,
            expires_at=expires_at,
            reason=reason,
        )

        approval = DurableApproval(
            approval_id=appr_id,
            human=human.strip(),
            agent=agent.strip(),
            change=cid,
            action=action.strip().upper(),
            scope=scope.strip(),
            issued_at=now_iso,
            expires_at=expires_at,
            reason=reason.strip(),
            revoked=False,
            signature=signature,
            metadata=metadata or {},
        )

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(cid, {})
            apprs = ch.setdefault("approvals", {})
            authorizations = apprs.setdefault("authorizations", {})
            authorizations[appr_id] = approval.to_dict()
            FileLedgerStore.save(self.repo_root, ledger)

        return approval

    def reject_request(
        self,
        request_id: str,
        human: str,
        reason: str = "",
        change_id: Optional[str] = None,
    ) -> ApprovalRequest:
        """Reject a pending authorization request."""
        cid = self._resolve_change_id(change_id)
        now_iso = _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(cid, {})
            requests = ch.setdefault("approvals", {}).setdefault("requests", {})

            if request_id not in requests:
                raise KeyError(f"Approval request '{request_id}' not found in change '{cid}'")

            req_data = requests[request_id]
            req_data["status"] = "REJECTED"
            req_data["reviewed_by"] = human.strip()
            req_data["reviewed_at"] = now_iso
            req_data["rejection_reason"] = reason.strip()

            FileLedgerStore.save(self.repo_root, ledger)
            return ApprovalRequest.from_dict(req_data)

    def revoke_approval(
        self,
        approval_id: str,
        human: str,
        reason: str = "",
        change_id: Optional[str] = None,
    ) -> DurableApproval:
        """Revoke a previously granted authorization object."""
        cid = self._resolve_change_id(change_id)
        now_iso = _now_iso()

        with FileLedgerStore.lock(self.repo_root):
            ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
            ch = ledger.setdefault("changes", {}).setdefault(cid, {})
            authorizations = ch.setdefault("approvals", {}).setdefault("authorizations", {})

            if approval_id not in authorizations:
                raise KeyError(f"Durable approval '{approval_id}' not found in change '{cid}'")

            data = authorizations[approval_id]
            data["revoked"] = True
            data.setdefault("metadata", {})
            data["metadata"]["revoked_by"] = human.strip()
            data["metadata"]["revoked_at"] = now_iso
            data["metadata"]["revocation_reason"] = reason.strip()

            FileLedgerStore.save(self.repo_root, ledger)
            return DurableApproval.from_dict(data)

    def get_approval(self, approval_id: str, change_id: Optional[str] = None) -> Optional[DurableApproval]:
        """Retrieve durable approval object by ID."""
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        changes = ledger.get("changes", {})

        if change_id:
            auths = changes.get(change_id, {}).get("approvals", {}).get("authorizations", {})
            if approval_id in auths:
                return DurableApproval.from_dict(auths[approval_id])
            return None

        # Search across all changes if change_id not specified
        for ch in changes.values():
            auths = ch.get("approvals", {}).get("authorizations", {})
            if approval_id in auths:
                return DurableApproval.from_dict(auths[approval_id])
        return None

    def list_requests(
        self, status: Optional[str] = None, change_id: Optional[str] = None
    ) -> List[ApprovalRequest]:
        """List authorization requests."""
        cid = self._resolve_change_id(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        requests = ledger.get("changes", {}).get(cid, {}).get("approvals", {}).get("requests", {})
        res = []
        for d in requests.values():
            r = ApprovalRequest.from_dict(d)
            if status and r.status.upper() != status.upper():
                continue
            res.append(r)
        return res

    def list_approvals(
        self, active_only: bool = False, change_id: Optional[str] = None
    ) -> List[DurableApproval]:
        """List authorization objects."""
        cid = self._resolve_change_id(change_id)
        ledger = FileLedgerStore.load(self.repo_root, auto_sync=False)
        auths = ledger.get("changes", {}).get(cid, {}).get("approvals", {}).get("authorizations", {})
        res = []
        now_dt = _now_utc()
        for d in auths.values():
            a = DurableApproval.from_dict(d)
            if active_only:
                if a.revoked or _is_expired(a.expires_at, now_dt):
                    continue
            res.append(a)
        return res

    def validate_approval(
        self,
        approval_id: str,
        agent_id: str,
        change_id: str,
        operation: str,
        target: str,
    ) -> Tuple[bool, str, Optional[DurableApproval]]:
        """Validate an approval object against agent, change, action, and scope boundaries.
        
        Returns:
            (valid, violation_code_or_ok, approval_object)
        """
        from .capabilities import _target_matches, _op_matches

        appr = self.get_approval(approval_id, change_id=change_id)
        if not appr:
            return False, "APPROVAL_NOT_FOUND", None

        # 1. Tamper detection: verify cryptographic signature
        expected_sig = compute_approval_signature(
            approval_id=appr.approval_id,
            human=appr.human,
            agent=appr.agent,
            change=appr.change,
            action=appr.action,
            scope=appr.scope,
            issued_at=appr.issued_at,
            expires_at=appr.expires_at,
            reason=appr.reason,
        )
        if appr.signature != expected_sig:
            return False, "APPROVAL_TAMPERED", appr

        # 2. Revocation check
        if appr.revoked:
            return False, "APPROVAL_REVOKED", appr

        # 3. Expiration check
        if _is_expired(appr.expires_at):
            return False, "APPROVAL_EXPIRED", appr

        # 4. Non-transferability: Agent binding
        if appr.agent != agent_id:
            return False, "APPROVAL_AGENT_MISMATCH", appr

        # 5. Non-transferability: Change binding
        if appr.change != change_id:
            return False, "APPROVAL_CHANGE_MISMATCH", appr

        # 6. Action limitation
        op_val = operation.value if hasattr(operation, "value") else str(operation).upper()
        if not _op_matches(appr.action, op_val):
            return False, "APPROVAL_ACTION_MISMATCH", appr

        # 7. Scope limitation
        if not _target_matches(appr.scope, target):
            return False, "APPROVAL_SCOPE_EXCEEDED", appr

        return True, "OK", appr
