"""Cryptographic signing, identity verification, and token authentication for AgentFlow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Dict, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AgentSigningContext:
    """Per-session or per-agent HMAC signing context.

    Held in memory by the runner/host runtime; used to sign action provenance,
    session tokens, and tool calls.
    """
    agent_id: str
    session_id: str
    signing_key: str    # Hex-encoded 32-byte secret

    @classmethod
    def generate(cls, agent_id: str, session_id: Optional[str] = None) -> "AgentSigningContext":
        sid = session_id or f"sess-{secrets.token_hex(8)}"
        key = secrets.token_hex(32)
        return cls(agent_id=agent_id, session_id=sid, signing_key=key)

    def sign_payload(self, payload: Any) -> str:
        """Produce an HMAC-SHA256 signature over a canonical JSON serialization of payload."""
        if isinstance(payload, str):
            content = payload.encode("utf-8")
        elif hasattr(payload, "to_dict"):
            content = json.dumps(payload.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        else:
            content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        key_bytes = bytes.fromhex(self.signing_key)
        return f"hmac-sha256:{hmac.new(key_bytes, content, hashlib.sha256).hexdigest()}"

    def verify_signature(self, payload: Any, signature: str) -> bool:
        """Verify that signature matches expected HMAC-SHA256."""
        if not signature or not signature.startswith("hmac-sha256:"):
            return False
        expected = self.sign_payload(payload)
        return hmac.compare_digest(expected, signature)


class AgentTokenAuthority:
    """Server-side authority for minting and verifying cryptographic session tokens."""

    _DEFAULT_SECRET: bytes = b"agentflow-sovereign-master-secret-key-32b"

    def __init__(self, master_secret: Optional[str] = None):
        if master_secret:
            self._master_secret = master_secret.encode("utf-8")
        else:
            env_secret = os.environ.get("AGENTFLOW_MASTER_SECRET")
            if env_secret:
                self._master_secret = env_secret.encode("utf-8")
            else:
                self._master_secret = self._DEFAULT_SECRET

    def mint_session_token(
        self,
        agent_id: str,
        session_id: str,
        role: str,
        ring: str,
        change_id: str,
        parent_session_id: Optional[str] = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Create a tamper-evident cryptographically signed session token."""
        ts = datetime.now(timezone.utc).timestamp()
        claims = {
            "agent_id": agent_id,
            "session_id": session_id,
            "role": role,
            "ring": ring,
            "change_id": change_id,
            "parent_session_id": parent_session_id,
            "iat": int(ts),
            "exp": int(ts + ttl_seconds),
        }
        claims_json = json.dumps(claims, sort_keys=True, separators=(",", ":"))
        sig = hmac.new(self._master_secret, claims_json.encode("utf-8"), hashlib.sha256).hexdigest()
        token_data = {
            "claims": claims,
            "sig": sig,
        }
        import base64
        return base64.urlsafe_b64encode(json.dumps(token_data).encode("utf-8")).decode("utf-8")

    def verify_session_token(self, token: str) -> Tuple[bool, str, Dict[str, Any]]:
        """Validate signature, expiry, and return claims."""
        import base64
        try:
            raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
            data = json.loads(raw)
            claims = data.get("claims", {})
            sig = data.get("sig", "")
            claims_json = json.dumps(claims, sort_keys=True, separators=(",", ":"))
            expected_sig = hmac.new(self._master_secret, claims_json.encode("utf-8"), hashlib.sha256).hexdigest()

            if not hmac.compare_digest(expected_sig, sig):
                return False, "Invalid token signature", {}

            now = int(datetime.now(timezone.utc).timestamp())
            if claims.get("exp", 0) < now:
                return False, "Session token has expired", {}

            return True, "Valid session token", claims
        except Exception as exc:
            return False, f"Malformed token: {exc}", {}
