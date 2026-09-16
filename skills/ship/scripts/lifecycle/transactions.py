"""Durable, single-writer archive recovery. Call while holding the ledger lock."""

import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, Optional

from .paths import repository_path, resolve_change_path, validate_change_id

JOURNAL = ".ship/archive-transaction.json"


def sync_directory(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, data: bytes, tag: Optional[str] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".ship-write-{tag}-" if tag else ".ship-write-", dir=path.parent)
    try:
        if path.exists():
            os.fchmod(fd, path.stat().st_mode & 0o777)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _encode(data: Optional[bytes]) -> Optional[str]:
    return base64.b64encode(data).decode("ascii") if data is not None else None


def begin_archive(repo_root: Path, operation_id: str, change: str, destination: Path,
                  updates: Dict[Path, Any]) -> None:
    journal = repository_path(repo_root, JOURNAL)
    if journal.exists():
        raise RuntimeError("Unfinished archive must be recovered before starting another")
    source = resolve_change_path(repo_root, change)
    ledger = repository_path(repo_root, ".ship/state.json")
    payload = {
        "version": 1, "operation_id": operation_id, "change": change, "phase": "prepared",
        "source": str(source.relative_to(repo_root)),
        "destination": str(destination.relative_to(repo_root)),
        "ledger_before": _encode(ledger.read_bytes() if ledger.exists() else None),
        "specs": [{"path": str(path.relative_to(repo_root)), "before": _encode(before),
                   "after_hash": hashlib.sha256(after.encode("utf-8")).hexdigest()}
                  for path, (before, after) in updates.items()],
    }
    atomic_write(journal, json.dumps(payload, indent=2).encode("utf-8"))


def record_archive_progress(repo_root: Path, phase: str) -> None:
    journal = repository_path(repo_root, JOURNAL)
    data = json.loads(journal.read_text(encoding="utf-8"))
    data["phase"] = phase
    atomic_write(journal, json.dumps(data, indent=2).encode("utf-8"))


def recover_archive(repo_root: Path) -> Optional[str]:
    """Restore a prepared archive, or finalize one committed in the ledger; repeatable."""
    journal = repository_path(repo_root, JOURNAL)
    if not journal.exists():
        return None
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        if data["version"] != 1 or not isinstance(data["operation_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", data["operation_id"]):
            raise ValueError("unsupported transaction")
        change = validate_change_id(data["change"])
        source = resolve_change_path(repo_root, change)
        if data["source"] != str(source.relative_to(repo_root)):
            raise ValueError("invalid archive source")
        destination = repository_path(repo_root, data["destination"])
        if destination.parent != repository_path(repo_root, "openspec/archive"):
            raise ValueError("invalid archive destination")
        specs = []
        for item in data["specs"]:
            path = repository_path(repo_root, item["path"])
            if path.parent != repository_path(repo_root, "openspec/specs"):
                raise ValueError("invalid living spec path")
            before = base64.b64decode(item["before"], validate=True) if item["before"] is not None else None
            specs.append((path, before, item["after_hash"]))
        ledger = repository_path(repo_root, ".ship/state.json")
        current_bytes = ledger.read_bytes() if ledger.exists() else None
        current = json.loads(current_bytes) if current_bytes is not None else {}
        delivery = current.get("changes", {}).get(change, {}).get("evidence", {}).get("delivery", {})
        committed = (delivery.get("archive_operation_id") == data["operation_id"]
                     and delivery.get("status") == "ARCHIVED")
        if committed:
            if source.exists() or not destination.is_dir():
                raise ValueError("committed archive package is inconsistent")
            for path, _, after_hash in specs:
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != after_hash:
                    raise ValueError(f"committed spec is inconsistent: {path}")
        else:
            old_ledger = base64.b64decode(data["ledger_before"], validate=True) if data["ledger_before"] is not None else None
            if current_bytes != old_ledger:
                raise ValueError("ledger changed outside the unfinished archive; manual reconciliation required")
            if source.exists() == destination.exists():
                raise ValueError("expected exactly one source or archived package")
            # Never overwrite edits made outside the interrupted transaction.
            # Atomic spec writes can leave only the original or intended bytes.
            for path, before, after_hash in specs:
                actual = path.read_bytes() if path.exists() else None
                if actual != before and (actual is None or hashlib.sha256(actual).hexdigest() != after_hash):
                    raise ValueError(f"spec changed outside the unfinished archive: {path}")
            for path, before, _ in specs:
                if before is None:
                    path.unlink(missing_ok=True)
                    if path.parent.exists():
                        sync_directory(path.parent)
                else:
                    atomic_write(path, before, tag=data["operation_id"])
            if destination.exists():
                shutil.move(str(destination), str(source))
                sync_directory(source.parent)
                sync_directory(destination.parent)
        for parent in {path.parent for path, _, _ in specs}:
            if parent.exists():
                for temporary in parent.glob(f".ship-write-{data['operation_id']}-*"):
                    temporary.unlink()
                sync_directory(parent)
        journal.unlink()
        sync_directory(journal.parent)
        return "committed" if committed else "rolled_back"
    except Exception as exc:
        raise RuntimeError(f"Archive recovery incomplete; journal preserved at {journal}: {exc}") from exc
