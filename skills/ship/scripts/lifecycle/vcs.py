from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

from .models import GitInfo

GIT_NOTES_REF = "refs/notes/ship-evidence"
_vcs_tls = threading.local()


class GitClient:
    """Encapsulates all Git VCS interactions, status inspections, and note storage."""

    def __init__(self, notes_ref: str = GIT_NOTES_REF):
        self.notes_ref = notes_ref

    def run_cmd(
        self,
        repo_root: Path,
        *args: str,
        check: bool = False,
        env: Optional[Dict[str, str]] = None,
        text: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        """Execute a git command in the repository directory."""
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=text,
            check=check,
            env=env,
        )

    def get_output(self, repo_root: Path, *args: str, default: str = "") -> str:
        """Execute a git command and return stripped stdout if successful, else default."""
        try:
            res = self.run_cmd(repo_root, *args)
            return res.stdout.strip() if res.returncode == 0 else default
        except Exception:
            return default

    def is_git_repo(self, repo_root: Path) -> bool:
        """Check if path is inside a working tree."""
        return self.get_output(repo_root, "rev-parse", "--is-inside-work-tree") == "true"

    def compute_working_tree_fingerprint(self, repo_root: Path) -> str:
        """Compute a deterministic SHA-256 fingerprint of HEAD commit, working tree diff, and untracked files."""
        hasher = hashlib.sha256()

        head_sha = self.get_output(repo_root, "rev-parse", "HEAD", default="none")
        hasher.update(f"HEAD:{head_sha}\n".encode("utf-8"))

        try:
            if head_sha != "none":
                diff_res = self.run_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "HEAD", "--", text=False)
                if diff_res.returncode == 0:
                    hasher.update(b"DIFF:\n" + diff_res.stdout)
            else:
                diff_staged = self.run_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--cached", "--", text=False)
                diff_unstaged = self.run_cmd(repo_root, "diff", "--no-ext-diff", "--no-textconv", "--no-color", "--", text=False)
                if diff_staged.returncode == 0:
                    hasher.update(b"DIFF_STAGED:\n" + diff_staged.stdout)
                if diff_unstaged.returncode == 0:
                    hasher.update(b"DIFF_UNSTAGED:\n" + diff_unstaged.stdout)
        except Exception:
            pass

        ignored_prefixes = (".scratch/", "scratch/", ".ship/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
        try:
            untracked_res = self.run_cmd(repo_root, "ls-files", "--others", "--exclude-standard", "-z", text=False)
            if untracked_res.returncode == 0:
                for raw_path in sorted(p for p in untracked_res.stdout.split(b"\0") if p):
                    rel_str = raw_path.decode("utf-8", errors="replace")
                    if any(rel_str.startswith(p) for p in ignored_prefixes) or rel_str == "report.json":
                        continue
                    full_path = repo_root / rel_str
                    if full_path.is_symlink():
                        try:
                            target = os.readlink(full_path)
                            hasher.update(f"UNTRACKED_SYMLINK:{rel_str}->{target}\n".encode("utf-8"))
                        except Exception:
                            pass
                    elif full_path.is_file():
                        hasher.update(f"UNTRACKED:{rel_str}\n".encode("utf-8"))
                        try:
                            hasher.update(full_path.read_bytes())
                        except Exception:
                            pass
        except Exception:
            pass

        return hasher.hexdigest()

    def get_info(self, repo_root: Path) -> Dict[str, Any]:
        """Gather git branch, commit SHA, tree hash, and working tree status."""
        info: Dict[str, Any] = {
            "is_git": False,
            "branch": "unknown",
            "commit": None,
            "tree_hash": None,
            "is_clean": True,
            "modified_count": 0,
            "untracked_count": 0,
            "modified_source_files": [],
            "working_tree_fingerprint": None,
        }
        if not self.is_git_repo(repo_root):
            return info

        info["is_git"] = True
        info["branch"] = self.get_output(repo_root, "branch", "--show-current") or self.get_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD", default="unknown")
        info["commit"] = self.get_output(repo_root, "rev-parse", "HEAD") or None
        info["tree_hash"] = self.get_output(repo_root, "rev-parse", "HEAD^{tree}") or None

        try:
            status_res = self.run_cmd(repo_root, "status", "--porcelain")
            status_lines = [l for l in status_res.stdout.splitlines() if l.strip()]
            info["is_clean"] = len(status_lines) == 0
            info["modified_count"] = sum(1 for l in status_lines if not l.startswith("??"))
            info["untracked_count"] = sum(1 for l in status_lines if l.startswith("??"))

            ignored_prefixes = (".scratch/", "scratch/", ".ship/", "openspec/archive/", "openspec/.", ".gemini/", ".git/")
            modified_sources = []
            for l in status_lines:
                filename = l[3:].strip()
                if " -> " in filename:
                    filename = filename.split(" -> ", 1)[1].strip()
                if filename.startswith('"') and filename.endswith('"'):
                    filename = filename[1:-1]
                if not any(filename.startswith(p) for p in ignored_prefixes) and filename not in {"report.json", ".gitignore"}:
                    modified_sources.append(filename)
            info["modified_source_files"] = modified_sources
            info["working_tree_fingerprint"] = self.compute_working_tree_fingerprint(repo_root)
        except Exception:
            pass
        return info

    def get_git_common_dir(self, repo_root: Path) -> Path:
        """Resolve the common git directory shared across worktrees."""
        out = self.get_output(repo_root, "rev-parse", "--git-common-dir")
        if out:
            p = Path(out)
            if not p.is_absolute():
                p = (repo_root / p).resolve()
            return p
        return (repo_root / ".git").resolve()

    @contextmanager
    def notes_lock(self, repo_root: Path, timeout_sec: float = 10.0):
        """Cross-worktree file lock on the shared git common directory."""
        common_dir = self.get_git_common_dir(repo_root)
        common_dir.mkdir(parents=True, exist_ok=True)
        lock_file = (common_dir / "ship_notes.lock").resolve()
        lock_key = str(lock_file)

        if not hasattr(_vcs_tls, "locks"):
            _vcs_tls.locks = {}

        depth = _vcs_tls.locks.get(lock_key, 0)
        if depth > 0:
            _vcs_tls.locks[lock_key] = depth + 1
            try:
                yield
            finally:
                _vcs_tls.locks[lock_key] -= 1
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
            _vcs_tls.locks[lock_key] = 1
            yield
        finally:
            _vcs_tls.locks[lock_key] = 0
            if locked and fcntl:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except Exception:
                    pass
            try:
                os.close(fd)
            except Exception:
                pass

    def attach_git_note_evidence(
        self,
        repo_root: Path,
        commit_sha: str,
        evidence_type: str,
        data: Dict[str, Any],
        ref: Optional[str] = None,
        change_id: Optional[str] = None,
        active_change: Optional[str] = None,
    ) -> Optional[str]:
        """Attach structured JSON validation evidence to a commit object via git notes."""
        ref = ref or self.notes_ref
        if not self.is_git_repo(repo_root) or not commit_sha:
            return None
        resolved_sha = self.get_output(repo_root, "rev-parse", "--verify", commit_sha)
        if not resolved_sha:
            return None

        cid = change_id or data.get("change") or active_change or "default"
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        fingerprint = self.compute_working_tree_fingerprint(repo_root)

        with self.notes_lock(repo_root):
            for attempt in range(5):
                raw_note = self.get_output(repo_root, "notes", f"--ref={ref}", "show", resolved_sha)
                try:
                    existing_evidence = json.loads(raw_note) if raw_note else {}
                except Exception:
                    existing_evidence = {"raw_previous_note": raw_note}

                changes = existing_evidence.setdefault("changes", {})
                change_entry = changes.setdefault(cid, {})

                runs = change_entry.setdefault(f"{evidence_type}_runs", [])
                runs.append({
                    "timestamp": now_iso,
                    "commit": resolved_sha,
                    "fingerprint": fingerprint,
                    "change_id": cid,
                    "evidence_type": evidence_type,
                    "data": data,
                })

                change_entry[evidence_type] = data
                change_entry["last_updated"] = now_iso
                existing_evidence[evidence_type] = data
                existing_evidence["last_change_id"] = cid
                existing_evidence["last_updated"] = now_iso

                res = self.run_cmd(
                    repo_root,
                    "notes",
                    f"--ref={ref}",
                    "add",
                    "-f",
                    "-m",
                    json.dumps(existing_evidence, indent=2),
                    resolved_sha,
                )
                if res.returncode == 0:
                    return resolved_sha
                time.sleep(0.02 * (attempt + 1))

        return None

    def read_git_note_evidence(
        self,
        repo_root: Path,
        commit_sha: str,
        ref: Optional[str] = None,
        change_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Read and parse structured JSON evidence from git notes on a commit."""
        ref = ref or self.notes_ref
        if not self.is_git_repo(repo_root) or not commit_sha:
            return {}
        resolved_sha = self.get_output(repo_root, "rev-parse", "--verify", commit_sha)
        if not resolved_sha:
            return {}
        raw_note = self.get_output(repo_root, "notes", f"--ref={ref}", "show", resolved_sha)
        try:
            data = json.loads(raw_note) if raw_note else {}
            if isinstance(data, dict):
                if change_id and "changes" in data and change_id in data["changes"]:
                    return data["changes"][change_id]
                return data
        except Exception:
            pass
        return {}
