"""State ledger persistence and workspace synchronization."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

_tls = threading.local()


def read_json_file(path: Path, default: Any = None) -> Any:
    """Safely load JSON from file path, returning default on missing file or parse error."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def ensure_gitignore_has_ship(repo_root: Path) -> None:
    """Ensure .ship/ is ignored in git without creating unwanted untracked working-tree files."""
    def _append_ignore_entry(target: Path) -> None:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            content = target.read_text(encoding="utf-8") if target.exists() else ""
            lines = [l.strip() for l in content.splitlines()]
            if ".ship" not in lines and ".ship/" not in lines:
                with target.open("a", encoding="utf-8") as f:
                    if content and not content.endswith("\n"):
                        f.write("\n")
                    f.write(".ship/\n")
        except Exception:
            pass

    info_exclude = repo_root / ".git" / "info" / "exclude"
    if info_exclude.parent.exists():
        _append_ignore_entry(info_exclude)
    else:
        _append_ignore_entry(repo_root / ".gitignore")


def make_default_review_evidence() -> Dict[str, Any]:
    """Default review evidence structure."""
    return {
        "verdict": None,
        "status": "PENDING",
        "findings_count": 0,
        "critical_or_high_count": 0,
        "reviewer": None,
        "report_path": None,
        "snapshot_fingerprint": None,
        "test_evidence_passed": None,
    }


def make_default_evidence() -> Dict[str, Any]:
    return {
        "design": {"adr": None, "status": "PENDING"},
        "spike": {"status": "NONE", "verdict": None, "dir": None},
        "implementation": {"status": "PENDING", "tests_passed": None, "failed_count": 0},
        "simplify": {"debt_count": 0, "status": "PENDING"},
        "review": make_default_review_evidence(),
        "delivery": {"status": "PENDING"},
    }


def create_empty_change_entry(change_id: str) -> Dict[str, Any]:
    return {
        "change_id": change_id,
        "phase": "design",
        "task_status": {
            "total": 0,
            "completed": 0,
            "pending": 0,
            "next": None,
            "in_progress": None,
        },
        "blockers": [],
        "revision_counter": 0,
        "evidence": make_default_evidence(),
        "checkpoints": {},
    }


class FileLedgerStore:
    """Thread-safe, atomic state store for .ship/state.json."""

    @staticmethod
    def get_ledger_path(repo_root: Path) -> Path:
        return repo_root / ".ship" / "state.json"

    @classmethod
    @contextmanager
    def lock(cls, repo_root: Path, timeout_sec: float = 10.0):
        ship_dir = repo_root / ".ship"
        ship_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (ship_dir / "state.lock").resolve()
        lock_key = str(lock_file)

        if not hasattr(_tls, "locks"):
            _tls.locks = {}

        current_depth = _tls.locks.get(lock_key, 0)
        if current_depth > 0:
            _tls.locks[lock_key] = current_depth + 1
            try:
                yield
            finally:
                _tls.locks[lock_key] -= 1
            return

        fd = os.open(str(lock_file), os.O_RDWR | os.O_CREAT, 0o666)
        locked = False
        try:
            if fcntl:
                start_time = time.time()
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        locked = True
                        break
                    except (BlockingIOError, IOError, OSError):
                        if time.time() - start_time >= timeout_sec:
                            fcntl.flock(fd, fcntl.LOCK_EX)
                            locked = True
                            break
                        time.sleep(0.01)
            _tls.locks[lock_key] = 1
            yield
        finally:
            _tls.locks[lock_key] = 0
            if locked and fcntl:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                os.close(fd)
            except Exception:
                pass

    @classmethod
    def get_active_change(cls, repo_root: Path) -> Optional[str]:
        ledger_data = read_json_file(cls.get_ledger_path(repo_root))
        if isinstance(ledger_data, dict) and ledger_data.get("active_change_id"):
            return ledger_data["active_change_id"]
        return None

    @classmethod
    def save(cls, repo_root: Path, ledger: Dict[str, Any]) -> None:
        ship_dir = repo_root / ".ship"
        ship_dir.mkdir(parents=True, exist_ok=True)
        ensure_gitignore_has_ship(repo_root)
        ledger_path = cls.get_ledger_path(repo_root)

        temp_fd, temp_path = tempfile.mkstemp(prefix="state_", suffix=".json.tmp", dir=str(ship_dir))
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(ledger, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, ledger_path)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            raise

    @classmethod
    def sync_from_workspace(
        cls,
        repo_root: Path,
        target_change_id: Optional[str] = None,
        inspect_openspec_fn: Optional[Callable[..., List[Dict[str, Any]]]] = None,
        inspect_adrs_fn: Optional[Callable[[Path], List[Dict[str, Any]]]] = None,
        inspect_spikes_fn: Optional[Callable[[Path], List[str]]] = None,
        inspect_review_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None,
    ) -> Dict[str, Any]:
        with cls.lock(repo_root):
            ledger_path = cls.get_ledger_path(repo_root)
            loaded = read_json_file(ledger_path)
            existing: Dict[str, Any] = loaded if isinstance(loaded, dict) and "changes" in loaded else {}

            changes: Dict[str, Any] = dict(existing.get("changes", {}))
            active_change_id = target_change_id or existing.get("active_change_id") or cls.get_active_change(repo_root)

            packages = inspect_openspec_fn(repo_root, target_change=None) if inspect_openspec_fn else []
            adrs = inspect_adrs_fn(repo_root) if inspect_adrs_fn else []
            spikes = inspect_spikes_fn(repo_root) if inspect_spikes_fn else []

            # Re-read ledger state to capture any concurrent updates committed during workspace discovery
            latest_loaded = read_json_file(ledger_path)
            if isinstance(latest_loaded, dict) and "changes" in latest_loaded:
                for cid, cval in latest_loaded["changes"].items():
                    if cid not in changes:
                        changes[cid] = cval
                    elif isinstance(cval, dict) and cval.get("revision_counter", 0) > changes[cid].get("revision_counter", 0):
                        changes[cid] = cval
                if not active_change_id and latest_loaded.get("active_change_id"):
                    active_change_id = latest_loaded["active_change_id"]

            discovered_changes = [p["change"] for p in packages]
            if not discovered_changes:
                if active_change_id and changes.get(active_change_id, {}).get("evidence", {}).get("delivery", {}).get("status") != "ARCHIVED":
                    discovered_changes = [active_change_id]
                elif adrs:
                    discovered_changes = [adrs[0]["name"].replace(".md", "").lower()]
                else:
                    discovered_changes = ["default"]

            for change in discovered_changes:
                if change not in changes:
                    changes[change] = create_empty_change_entry(change)
                entry = changes[change]

                old_phase = entry.get("phase")
                old_blockers = list(entry.get("blockers", []))

                if entry.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
                    entry["phase"] = "delivery"
                    continue

                matched_pkg = next((p for p in packages if p["change"] == change), None)
                if matched_pkg:
                    entry["task_status"]["total"] = matched_pkg["total_tasks"]
                    entry["task_status"]["completed"] = matched_pkg["completed_tasks"]
                    entry["task_status"]["pending"] = matched_pkg["pending_tasks"]
                    entry["task_status"]["next"] = matched_pkg["next_task"]
                    entry["task_status"]["in_progress"] = matched_pkg["next_task"]

                if adrs:
                    entry["evidence"]["design"]["adr"] = adrs[0]["name"]
                    entry["evidence"]["design"]["status"] = adrs[0].get("status")

                if spikes:
                    entry["evidence"]["spike"]["status"] = "ACTIVE"
                    entry["evidence"]["spike"]["dir"] = spikes[0]
                else:
                    if entry["evidence"]["spike"].get("status") == "ACTIVE":
                        entry["evidence"]["spike"]["status"] = "PASSED"

                review = inspect_review_fn(repo_root, change=change) if inspect_review_fn else None
                if review:
                    verdict = review.get("verdict") or review.get("status")
                    entry["evidence"]["review"]["verdict"] = verdict
                    entry["evidence"]["review"]["status"] = review.get("status")
                    entry["evidence"]["review"]["reviewer"] = review.get("reviewer")
                    entry["evidence"]["review"]["findings_count"] = review.get("findings_count", 0)
                    entry["evidence"]["review"]["critical_or_high_count"] = review.get("critical_or_high_count", 0)
                    entry["evidence"]["review"]["test_evidence_passed"] = review.get("test_evidence_passed")
                    entry["evidence"]["review"]["report_path"] = review.get("path") or review.get("report_file")
                    entry["evidence"]["review"]["snapshot_fingerprint"] = review.get("snapshot_fingerprint")

                chk_dir = repo_root / ".scratch" / "checkpoints"
                if chk_dir.exists():
                    for cf in chk_dir.glob(f"{change}_*.json"):
                        cdata = read_json_file(cf)
                        if isinstance(cdata, dict):
                            gate_k = cdata.get("gate", cf.stem.replace(f"{change}_", ""))
                            entry["checkpoints"][gate_k] = cdata

                # Preserve explicit non-derived blockers (e.g. manual holds, design approval)
                explicit_blockers = [
                    b for b in entry.get("blockers", [])
                    if not (
                        b.startswith("Tests:")
                        or b.startswith("Spike active in ")
                        or b.startswith("Review has ")
                        or b.startswith("Review verdict is ")
                    )
                ]

                existing_test_blockers = [b for b in entry.get("blockers", []) if b.startswith("Tests:")]
                if entry.get("evidence", {}).get("implementation", {}).get("tests_passed") is False:
                    failed_cnt = entry["evidence"]["implementation"].get("failed_count", 1)
                    t_blocker = f"Tests: {failed_cnt} test(s) failing"
                    if t_blocker not in existing_test_blockers:
                        existing_test_blockers.append(t_blocker)

                blockers: List[str] = list(existing_test_blockers)
                for eb in explicit_blockers:
                    if eb not in blockers:
                        blockers.append(eb)

                if spikes:
                    entry["phase"] = "spike"
                    blockers.append(f"Spike active in {spikes[0]}")
                elif not matched_pkg or matched_pkg["total_tasks"] == 0:
                    entry["phase"] = "design"
                elif matched_pkg["pending_tasks"] > 0 or any(b.startswith("Tests:") for b in blockers):
                    entry["phase"] = "implementation"
                else:
                    review_ev = entry["evidence"]["review"]
                    crit = review_ev.get("critical_or_high_count", 0)
                    verd = review_ev.get("verdict", "")
                    if crit > 0:
                        blockers.append(f"Review has {crit} unresolved CRITICAL/HIGH finding(s)")
                    if verd in {"FAIL", "FAILED", "REJECTED"}:
                        blockers.append(f"Review verdict is {verd}")

                    if review_ev.get("verdict") in {"PASS", "APPROVED"} and crit == 0 and not blockers:
                        entry["phase"] = "delivery"
                    else:
                        entry["phase"] = "review"

                deduped_blockers: List[str] = []
                for b in blockers:
                    if b not in deduped_blockers:
                        deduped_blockers.append(b)
                entry["blockers"] = deduped_blockers

                if entry.get("revision_counter", 0) == 0:
                    entry["revision_counter"] = 1
                elif entry.get("phase") != old_phase or entry.get("blockers") != old_blockers:
                    entry["revision_counter"] = entry.get("revision_counter", 1) + 1

            if not active_change_id and discovered_changes and discovered_changes != ["default"]:
                active_change_id = discovered_changes[0]

            new_ledger = {
                "version": 1,
                "active_change_id": active_change_id,
                "changes": changes,
            }
            try:
                cls.save(repo_root, new_ledger)
            except Exception:
                pass
            return new_ledger

    @classmethod
    def load(
        cls,
        repo_root: Path,
        auto_sync: bool = True,
        sync_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        ledger_path = cls.get_ledger_path(repo_root)
        data = read_json_file(ledger_path)
        if isinstance(data, dict) and "changes" in data:
            return data
        if auto_sync and sync_fn:
            return sync_fn(repo_root)
        return {"version": 1, "active_change_id": None, "changes": {}}

    @classmethod
    def mutate_change(
        cls,
        repo_root: Path,
        change_id: str,
        updater: Callable[[Dict[str, Any]], None],
        set_active: bool = True,
        sync_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        with cls.lock(repo_root):
            ledger = cls.load(repo_root, auto_sync=False)
            ledger_path = cls.get_ledger_path(repo_root)
            if not ledger.get("changes") and not ledger_path.exists() and sync_fn:
                ledger = sync_fn(repo_root)
            changes = ledger.setdefault("changes", {})
            if change_id not in changes:
                changes[change_id] = create_empty_change_entry(change_id)
            entry = changes[change_id]
            updater(entry)
            entry["revision_counter"] = entry.get("revision_counter", 0) + 1
            if set_active:
                ledger["active_change_id"] = change_id
            elif ledger.get("active_change_id") == change_id:
                ledger["active_change_id"] = None
            cls.save(repo_root, ledger)
            return entry

    @classmethod
    def set_active_change(
        cls,
        repo_root: Path,
        change: str,
        sync_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> None:
        with cls.lock(repo_root):
            ledger = cls.load(repo_root, auto_sync=False)
            ledger_path = cls.get_ledger_path(repo_root)
            if not ledger.get("changes") and not ledger_path.exists() and sync_fn:
                ledger = sync_fn(repo_root)
            ledger["active_change_id"] = change.strip()
            cls.save(repo_root, ledger)

    @classmethod
    def record_review(
        cls,
        repo_root: Path,
        report_path_or_dict: Any,
        change_id: Optional[str] = None,
        parse_report_fn: Optional[Callable[[Path, Path], Dict[str, Any]]] = None,
        get_git_info_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
        attach_note_fn: Optional[Callable[..., Any]] = None,
        sync_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        if isinstance(report_path_or_dict, (str, Path)):
            p = Path(report_path_or_dict)
            if not p.is_absolute():
                p = repo_root / p
            report = parse_report_fn(p, repo_root) if parse_report_fn else {}
        else:
            report = report_path_or_dict

        cid = change_id or report.get("change") or cls.get_active_change(repo_root) or "default"

        def updater(entry: Dict[str, Any]) -> None:
            ev = entry["evidence"]["review"]
            ev["verdict"] = report.get("verdict")
            ev["status"] = report.get("status")
            ev["reviewer"] = report.get("reviewer")
            ev["findings_count"] = report.get("findings_count", 0)
            ev["critical_or_high_count"] = report.get("critical_or_high_count", 0)
            ev["test_evidence_passed"] = report.get("test_evidence_passed")
            ev["report_path"] = report.get("path") or report.get("report_file")
            ev["snapshot_fingerprint"] = report.get("snapshot_fingerprint")

            if get_git_info_fn and attach_note_fn:
                git_info = get_git_info_fn(repo_root)
                commit = git_info.get("commit")
                if commit:
                    note_oid = attach_note_fn(repo_root, commit, "review_report", report, change_id=cid)
                    ev["git_note_oid"] = note_oid

            blockers = [b for b in entry.get("blockers", []) if not b.startswith("Review:")]
            crit = ev.get("critical_or_high_count", 0)
            if crit > 0:
                blockers.append(f"Review: {crit} unresolved CRITICAL/HIGH finding(s)")
            if ev.get("verdict") in {"FAIL", "FAILED", "REJECTED"}:
                blockers.append(f"Review: verdict is {ev.get('verdict')}")
            entry["blockers"] = blockers

            if ev.get("verdict") in {"PASS", "APPROVED"} and crit == 0 and not blockers:
                entry["phase"] = "delivery"
            else:
                entry["phase"] = "review"

        return cls.mutate_change(repo_root, cid, updater, sync_fn=sync_fn)

    @classmethod
    def record_test_run(
        cls,
        repo_root: Path,
        test_summary: Dict[str, Any],
        change_id: Optional[str] = None,
        get_git_info_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
        attach_note_fn: Optional[Callable[..., Any]] = None,
        notes_ref: str = "refs/notes/ship-evidence",
        sync_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        cid = change_id or cls.get_active_change(repo_root) or "default"

        def updater(entry: Dict[str, Any]) -> None:
            impl = entry["evidence"]["implementation"]
            impl["status"] = "PASSED" if test_summary.get("passed", False) else "FAILED"
            impl["tests_passed"] = test_summary.get("passed", False)
            impl["failed_count"] = test_summary.get("failed_count", 0)
            impl["command"] = test_summary.get("command")

            if get_git_info_fn and attach_note_fn:
                git_info = get_git_info_fn(repo_root)
                commit = git_info.get("commit")
                if commit:
                    attach_note_fn(repo_root, commit, "test_evidence", test_summary, change_id=cid)
                    impl["evidence_ref"] = notes_ref

            blockers = [b for b in entry.get("blockers", []) if not b.startswith("Tests:")]
            if not test_summary.get("passed", False):
                blockers.append(f"Tests: {test_summary.get('failed_count', 1)} test(s) failing")
            entry["blockers"] = blockers

        return cls.mutate_change(repo_root, cid, updater, sync_fn=sync_fn)

    @classmethod
    def clear_active_change(cls, repo_root: Path, change: Optional[str] = None) -> None:
        with cls.lock(repo_root):
            state_file = cls.get_ledger_path(repo_root)
            if state_file.exists():
                data = read_json_file(state_file, {})
                if isinstance(data, dict) and (change is None or data.get("active_change_id") == (change.strip() if change else None)):
                    data["active_change_id"] = None
                    cls.save(repo_root, data)

get_ledger_path = FileLedgerStore.get_ledger_path
ledger_lock = FileLedgerStore.lock
get_active_change = FileLedgerStore.get_active_change
set_active_change = FileLedgerStore.set_active_change
clear_active_change = FileLedgerStore.clear_active_change
load_ledger = FileLedgerStore.load
save_ledger = FileLedgerStore.save
mutate_change_state = FileLedgerStore.mutate_change
record_review_to_ledger = FileLedgerStore.record_review
record_test_run_to_ledger = FileLedgerStore.record_test_run
sync_ledger_from_workspace = FileLedgerStore.sync_from_workspace

