"""External hash anchoring and rotation engine for Forensic Audit Trails.

Provides:
- AnchorRecord: Immutable anchor checkpoint data structure.
- AnchorBackend: Interface for anchor backends.
- FileAnchorBackend: Append-only local/independent volume anchor.
- S3AnchorBackend: S3 WORM/Object Lock anchor.
- EventLogAnchorManager: Coordinates hash anchoring, rotation, and external verification.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Protocol, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AnchorRecord:
    """A tamper-evident published hash checkpoint."""
    anchor_id: str
    log_file: str
    event_count: int
    latest_event_id: str
    latest_event_hash: str     # Hash of the last event in log
    file_sha256: str           # SHA-256 of entire log file content
    timestamp: str             # ISO 8601
    backend: str = "file"
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnchorRecord":
        return cls(
            anchor_id=str(data.get("anchor_id", "")),
            log_file=str(data.get("log_file", "")),
            event_count=int(data.get("event_count", 0)),
            latest_event_id=str(data.get("latest_event_id", "")),
            latest_event_hash=str(data.get("latest_event_hash", "")),
            file_sha256=str(data.get("file_sha256", "")),
            timestamp=str(data.get("timestamp", "")),
            backend=str(data.get("backend", "file")),
            metadata=dict(data.get("metadata", {})),
        )


class AnchorBackend(Protocol):
    """Protocol for external audit witnesses."""

    def publish(self, record: AnchorRecord) -> str:
        """Publish an anchor record and return anchor_id."""
        ...

    def verify(self, anchor_id: str, expected_file_sha256: str) -> bool:
        """Verify that an anchor exists and matches the expected file SHA-256."""
        ...

    def list_anchors(self) -> List[AnchorRecord]:
        """List all published anchors."""
        ...


class FileAnchorBackend:
    """Local or mounted volume append-only anchor store."""

    def __init__(self, anchor_file_path: Path):
        self.anchor_file_path = Path(anchor_file_path).resolve()

    def _ensure_dir(self) -> None:
        self.anchor_file_path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, record: AnchorRecord) -> str:
        self._ensure_dir()
        line = json.dumps(record.to_dict(), separators=(",", ":"))
        with self.anchor_file_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        return record.anchor_id

    def verify(self, anchor_id: str, expected_file_sha256: str) -> bool:
        if not self.anchor_file_path.exists():
            return False
        with self.anchor_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    data = json.loads(line_str)
                    if data.get("anchor_id") == anchor_id:
                        return data.get("file_sha256") == expected_file_sha256
                except Exception:
                    continue
        return False

    def list_anchors(self) -> List[AnchorRecord]:
        if not self.anchor_file_path.exists():
            return []
        anchors = []
        with self.anchor_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    anchors.append(AnchorRecord.from_dict(json.loads(line_str)))
                except Exception:
                    continue
        return anchors


class S3AnchorBackend:
    """S3 append-only / Object Lock anchor backend."""

    def __init__(self, bucket: str, prefix: str = "anchors/"):
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/"

    def publish(self, record: AnchorRecord) -> str:
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 is required to use S3AnchorBackend") from exc

        s3 = boto3.client("s3")
        key = f"{self.prefix}{record.anchor_id}.json"
        s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(record.to_dict(), indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        return record.anchor_id

    def verify(self, anchor_id: str, expected_file_sha256: str) -> bool:
        try:
            import boto3  # type: ignore
        except ImportError:
            return False

        s3 = boto3.client("s3")
        key = f"{self.prefix}{anchor_id}.json"
        try:
            resp = s3.get_object(Bucket=self.bucket, Key=key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
            return data.get("file_sha256") == expected_file_sha256
        except Exception:
            return False

    def list_anchors(self) -> List[AnchorRecord]:
        try:
            import boto3  # type: ignore
        except ImportError:
            return []

        s3 = boto3.client("s3")
        paginator = s3.get_paginator("list_objects_v2")
        records = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for obj in page.get("Contents", []):
                try:
                    resp = s3.get_object(Bucket=self.bucket, Key=obj["Key"])
                    data = json.loads(resp["Body"].read().decode("utf-8"))
                    records.append(AnchorRecord.from_dict(data))
                except Exception:
                    continue
        return records


class AuditAnchorManager:
    """Coordinates event log hash computation, anchor publishing, and ledger rotation."""

    def __init__(self, repo_root: Path, backend: Optional[AnchorBackend] = None):
        self.repo_root = Path(repo_root).resolve()
        self.event_file = self.repo_root / ".agentflow" / "events.jsonl"
        self.default_anchor_file = self.repo_root / ".agentflow" / "anchors.jsonl"
        self.backend: AnchorBackend = backend or FileAnchorBackend(self.default_anchor_file)

    def compute_event_log_sha256(self) -> str:
        """Compute SHA-256 digest of entire events.jsonl file."""
        if not self.event_file.exists():
            return hashlib.sha256(b"").hexdigest()
        h = hashlib.sha256()
        with self.event_file.open("rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def create_anchor(self, metadata: Optional[Dict[str, Any]] = None) -> AnchorRecord:
        """Create and publish an immutable anchor record for current event stream state."""
        from .events import EventLogger

        logger = EventLogger(self.repo_root)
        count, last_hash = logger._get_last_event_info()
        events = logger.read_all()
        last_event_id = events[-1].event_id if events else "none"

        file_sha256 = self.compute_event_log_sha256()
        ts = _now_iso()
        anchor_id = f"anc-{hashlib.sha256(f'{file_sha256}:{ts}'.encode()).hexdigest()[:12]}"

        record = AnchorRecord(
            anchor_id=anchor_id,
            log_file=str(self.event_file.name),
            event_count=count,
            latest_event_id=last_event_id,
            latest_event_hash=last_hash,
            file_sha256=file_sha256,
            timestamp=ts,
            backend="file" if isinstance(self.backend, FileAnchorBackend) else "s3",
            metadata=metadata or {},
        )
        self.backend.publish(record)
        return record

    def verify_latest_anchor(self) -> Tuple[bool, str, Optional[AnchorRecord]]:
        """Verify that current events.jsonl matches the most recently published anchor."""
        anchors = self.backend.list_anchors()
        if not anchors:
            return True, "No anchors published yet; baseline valid.", None
        latest = anchors[-1]
        current_sha256 = self.compute_event_log_sha256()

        if latest.file_sha256 != current_sha256:
            # Check if current log is an append-only progression or modified
            # If current log is smaller or different before that count, it's tampered
            return (
                False,
                f"Anchor verification failed for {latest.anchor_id}: expected log hash '{latest.file_sha256}', got '{current_sha256}'",
                latest,
            )
        return True, f"Anchor {latest.anchor_id} matches current event log digest.", latest

    def rotate_event_log(self, max_events: int = 10000) -> Optional[Path]:
        """Rotate events.jsonl if count exceeds max_events.

        Anchors the current log, archives it with its file SHA-256 in filename,
        and starts a new log chaining back to the archive hash.
        """
        from .events import EventLogger
        from .ledger import FileLedgerStore

        if not self.event_file.exists():
            return None

        with FileLedgerStore.lock(self.repo_root):
            logger = EventLogger(self.repo_root)
            count, last_hash = logger._get_last_event_info()
            if count < max_events:
                return None

            # 1. Publish anchor for the current log before moving
            anchor = self.create_anchor(metadata={"rotation_trigger": f"count_{count}_gte_{max_events}"})

            # 2. Archive log file
            archive_dir = self.repo_root / ".agentflow" / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_name = f"events.{anchor.file_sha256[:12]}.jsonl"
            archive_path = archive_dir / archive_name
            shutil.move(self.event_file, archive_path)

            # 3. Create rotation genesis record pointing to archived hash
            logger.emit(
                event_type="CHECKPOINT_CREATED",
                target=str(archive_path.name),
                payload={
                    "rotation": True,
                    "archived_log": str(archive_path.name),
                    "archived_events_count": count,
                    "archived_file_sha256": anchor.file_sha256,
                    "archived_last_hash": last_hash,
                    "anchor_id": anchor.anchor_id,
                },
                provenance={"system": "AuditAnchorManager"},
            )
            return archive_path
