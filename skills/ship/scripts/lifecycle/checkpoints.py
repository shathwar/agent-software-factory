"""Checkpoint creation and rollback manager."""

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import functools
from typing import Any, Callable, Dict, List, Optional

from .trailers import canonicalize_gate_name
from .paths import repository_path, resolve_change_path, validate_change_id


def _backup_path(src: Path, dest: Path) -> None:
    """Helper to backup a file or directory into destination directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        dest.symlink_to(os.readlink(src))
    elif src.is_file():
        shutil.copy2(src, dest)
    elif src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True, symlinks=True)


def _locked_recovery(method):
    @functools.wraps(method)
    def run(self, repo_root, *args, **kwargs):
        with self.ledger.lock(repo_root):
            self.ledger.load(repo_root, auto_sync=False)
            return method(self, repo_root, *args, **kwargs)
    return run


class CheckpointManager:
    """Manages working-tree and Git ref checkpoints and safe rollback state restoration."""

    def __init__(self, vcs_client: Any, config_manager: Any, ledger_store: Any):
        self.vcs = vcs_client
        self.config_manager = config_manager
        self.ledger = ledger_store

    @staticmethod
    def _validate_names(change: str, gate: str) -> None:
        for name in (change, gate):
            validate_change_id(name)

    @_locked_recovery
    def create_checkpoint(
        self,
        repo_root: Path,
        gate_name: str,
        change: Optional[str] = None,
        create_git_tag: bool = False,
    ) -> Dict[str, Any]:
        resolved_change = change or self.ledger.get_active_change(repo_root) or "default"
        git_info = self.vcs.get_info(repo_root)
        cfg = self.config_manager.load(repo_root)
        allow_git_tag = create_git_tag or cfg.get("create_git_tag", False)

        canonical_tag = canonicalize_gate_name(gate_name)
        self._validate_names(resolved_change, canonical_tag)
        resolve_change_path(repo_root, resolved_change)
        ref_name = f"refs/ship/{resolved_change}/{canonical_tag}"
        tag_name = f"ship/{resolved_change}/{canonical_tag}"
        commit_sha = git_info.get("commit")
        fingerprint = git_info.get("working_tree_fingerprint") or self.vcs.compute_working_tree_fingerprint(repo_root)
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        ref_created = False
        snapshot_sha: Optional[str] = None
        if git_info.get("is_git") and commit_sha:
            try:
                with tempfile.TemporaryDirectory() as idx_dir:
                    env = {**os.environ, "GIT_INDEX_FILE": str(Path(idx_dir) / "index"), "GIT_LITERAL_PATHSPECS": "1"}
                    self.vcs.run_cmd(repo_root, "read-tree", commit_sha, env=env, check=True)
                    candidates = self.vcs.run_cmd(repo_root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", env=env, check=True, text=False).stdout.split(b"\0")
                    excluded = (b".scratch", b"scratch", b".gemini", b".ship")
                    paths = sorted({p for p in candidates if p and not any(p == x or p.startswith(x + b"/") for x in excluded)})
                    if paths:
                        pathspec = Path(idx_dir) / "paths"
                        pathspec.write_bytes(b"\0".join(paths) + b"\0")
                        self.vcs.run_cmd(repo_root, "add", "-A", f"--pathspec-from-file={pathspec}", "--pathspec-file-nul", env=env, check=True)
                    tree_sha = self.vcs.run_cmd(repo_root, "write-tree", env=env, check=True).stdout.strip()
                    commit_msg = f"ship-checkpoint:{resolved_change}:{canonical_tag}"
                    snapshot_sha = self.vcs.run_cmd(repo_root, "commit-tree", tree_sha, "-p", commit_sha, "-m", commit_msg, env=env, check=True).stdout.strip()
            except Exception as exc:
                raise RuntimeError("Checkpoint snapshot failed; no checkpoint recorded") from exc

            target_ref_sha = snapshot_sha or commit_sha
            try:
                self.vcs.run_cmd(repo_root, "update-ref", ref_name, target_ref_sha, check=True)
                if allow_git_tag:
                    self.vcs.run_cmd(repo_root, "tag", "-f", tag_name, target_ref_sha, check=True)
                ref_created = True
            except Exception as exc:
                raise RuntimeError("Checkpoint reference could not be saved") from exc

        chk_dir = repository_path(repo_root, ".scratch/checkpoints")
        chk_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = repository_path(repo_root, f".scratch/checkpoints/{resolved_change}_{canonical_tag}.json")
        receipt_data = {
            "change": resolved_change,
            "gate": canonical_tag,
            "ref": ref_name,
            "tag": tag_name if allow_git_tag else None,
            "tag_created": allow_git_tag,
            "commit": commit_sha or "none",
            "snapshot_commit": snapshot_sha or commit_sha or "none",
            "fingerprint": fingerprint,
            "timestamp": timestamp,
            "is_git": git_info.get("is_git", False),
            "ref_created": ref_created,
        }
        receipt_file.write_text(json.dumps(receipt_data, indent=2), encoding="utf-8")

        try:
            def record_chk(entry: Dict[str, Any]) -> None:
                entry["checkpoints"][canonical_tag] = receipt_data
                entry["phase"] = canonical_tag
            self.ledger.mutate_change(repo_root, resolved_change, record_chk)
        except Exception as exc:
            raise RuntimeError("Checkpoint created, but ledger update failed") from exc

        return receipt_data

    @_locked_recovery
    def perform_rollback(
        self,
        repo_root: Path,
        target_gate: str,
        change: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        resolved_change = change or self.ledger.get_active_change(repo_root) or "default"
        canonical_tag = canonicalize_gate_name(target_gate)
        self._validate_names(resolved_change, canonical_tag)
        resolve_change_path(repo_root, resolved_change)

        git_info = self.vcs.get_info(repo_root)
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_dir = repository_path(repo_root, f".scratch/rollback_{timestamp_str}")

        chk_file = repository_path(repo_root, f".scratch/checkpoints/{resolved_change}_{canonical_tag}.json")
        target_tag = f"ship/{resolved_change}/{canonical_tag}"
        target_ref = f"refs/ship/{resolved_change}/{canonical_tag}"

        from .ledger import read_json_file, make_default_review_evidence
        checkpoint_info: Optional[Dict[str, Any]] = read_json_file(chk_file)

        if not isinstance(checkpoint_info, dict) or checkpoint_info.get("change") != resolved_change or checkpoint_info.get("gate") != canonical_tag:
            raise RuntimeError("Missing or invalid checkpoint receipt; rollback did not change files or ledger")
        if not git_info.get("is_git") or not git_info.get("commit"):
            raise RuntimeError("Rollback requires a checkpoint in a Git repository with commits")
        snapshot = checkpoint_info.get("snapshot_commit")
        base = checkpoint_info.get("commit")
        for sha in (snapshot, base):
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40,64}", sha) or not self.vcs.get_output(repo_root, "rev-parse", "--verify", f"{sha}^{{commit}}"):
                raise RuntimeError("Checkpoint references a missing or invalid commit; rollback aborted")
        ref_snapshot = self.vcs.get_output(repo_root, "rev-parse", "--verify", target_ref)
        if ref_snapshot and ref_snapshot != snapshot:
            raise RuntimeError("Checkpoint receipt and reference disagree; rollback aborted")
        ledger = self.ledger.load(repo_root, auto_sync=False)
        competing = {
            cid for cid, entry in ledger.get("changes", {}).items()
            if cid != resolved_change
            and (cid != "default" or entry.get("phase") != "design"
                 or entry.get("blockers") or entry.get("checkpoints")
                 or entry.get("task_status", {}).get("total", 0) > 0
                 or entry.get("evidence", {}).get("implementation", {}).get("tests_passed") is not None)
            and entry.get("evidence", {}).get("delivery", {}).get("status") != "ARCHIVED"
        }
        changes_dir = repo_root / "openspec" / "changes"
        if changes_dir.is_dir():
            competing.update(d.name for d in changes_dir.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name != resolved_change)
        if competing:
            raise RuntimeError(f"Rollback requires one active change per checkout; use isolated worktrees. Other changes: {', '.join(sorted(competing))}")

        backed_up_files: List[str] = []
        restored_files: List[str] = []
        removed_files: List[str] = []
        git_reset_performed = False

        if git_info.get("is_git"):
            target_sha = snapshot
            base_commit = base

            current_sha = git_info.get("commit")
            backup_dir.mkdir(parents=True, exist_ok=True)

            working_diff = self.vcs.run_cmd(repo_root, "diff", "--no-renames", "HEAD", text=False, check=True).stdout
            if working_diff:
                (backup_dir / "working_diff.patch").write_bytes(working_diff)

            if target_sha and current_sha and current_sha != target_sha and target_sha != "none":
                commit_diff = self.vcs.run_cmd(repo_root, "diff", "--no-renames", target_sha, "HEAD", text=False, check=True).stdout
                if commit_diff:
                    (backup_dir / "committed_diff.patch").write_bytes(commit_diff)

            if target_sha and target_sha != "none":
                try:
                    diff_files = self.vcs.run_cmd(repo_root, "diff", "--no-renames", "--name-only", "-z", target_sha, check=True).stdout.split("\0")
                    untracked_files = self.vcs.run_cmd(repo_root, "ls-files", "--others", "--exclude-standard", "-z", check=True).stdout.split("\0")
                    changed_files = [f for f in diff_files if f]
                    for p in [f for f in untracked_files if f]:
                        if p not in changed_files:
                            changed_files.append(p)

                    ignored_prefixes = (".scratch/", "scratch/", ".ship/", "ship/", ".gemini/", ".git/")
                    tasks_rel = f"openspec/changes/{resolved_change}/tasks.md"

                    if tasks_rel not in changed_files and (repo_root / tasks_rel).exists():
                        changed_files.append(tasks_rel)
                    for rel_path in changed_files:
                        if any(rel_path.startswith(p) for p in ignored_prefixes):
                            continue
                        full_path = repo_root / rel_path
                        if full_path.exists() or full_path.is_symlink():
                            if rel_path not in backed_up_files:
                                _backup_path(full_path, backup_dir / rel_path)
                                backed_up_files.append(rel_path)
                            if self.vcs.run_cmd(repo_root, "cat-file", "-e", f"{target_sha}:{rel_path}").returncode != 0:
                                _backup_path(full_path, backup_dir / "untracked_removed" / rel_path)

                    for rel_path in changed_files:
                        if any(rel_path.startswith(p) for p in ignored_prefixes) or rel_path == tasks_rel:
                            continue

                        full_path = repo_root / rel_path
                        if (full_path.is_file() or full_path.is_dir()) and rel_path not in backed_up_files:
                            _backup_path(full_path, backup_dir / rel_path)
                            backed_up_files.append(rel_path)

                        if self.vcs.run_cmd(repo_root, "cat-file", "-e", f"{target_sha}:{rel_path}").returncode == 0:
                            if self.vcs.run_cmd(repo_root, "checkout", target_sha, "--", rel_path, check=True).returncode == 0:
                                restored_files.append(rel_path)
                        else:
                            if full_path.is_file() or full_path.is_symlink():
                                self.vcs.run_cmd(repo_root, "rm", "-f", "--cached", "--ignore-unmatch", "--", rel_path, check=True)
                                full_path.unlink(missing_ok=True)
                                parent = full_path.parent
                                while parent != repo_root and parent.is_dir():
                                    try:
                                        parent.rmdir()
                                        parent = parent.parent
                                    except OSError:
                                        break
                            elif full_path.is_dir():
                                self.vcs.run_cmd(repo_root, "rm", "-rf", "--cached", "--ignore-unmatch", "--", rel_path, check=True)
                                shutil.rmtree(full_path)
                            removed_files.append(rel_path)

                    reset_target = base_commit or target_sha
                    if current_sha and reset_target and current_sha != reset_target and reset_target != "none":
                        if self.vcs.run_cmd(repo_root, "reset", reset_target, check=True).returncode == 0:
                            git_reset_performed = True
                    elif restored_files or removed_files:
                        git_reset_performed = True
                except Exception as exc:
                    raise RuntimeError(f"Rollback failed; ledger unchanged. Backups are in {backup_dir}") from exc

        pkg_dir = resolve_change_path(repo_root, resolved_change)
        tasks_file = repository_path(repo_root, f"openspec/changes/{resolved_change}/tasks.md")
        reset_tasks_count = 0
        if tasks_file.exists() and canonical_tag == "design":
            tasks_content = tasks_file.read_text(encoding="utf-8", errors="replace")
            new_lines = []
            for line in tasks_content.splitlines():
                if re.match(r"^(\s*(?:[-*]|\d+\.)\s*\[)[xX](\].*)$", line):
                    new_line = re.sub(r"^(\s*(?:[-*]|\d+\.)\s*\[)[xX](\].*)$", r"\g<1> \2", line)
                    new_lines.append(new_line)
                    reset_tasks_count += 1
                else:
                    new_lines.append(line)
            tasks_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        has_backups = bool(backed_up_files) or (backup_dir.exists() and (
            (backup_dir / "working_diff.patch").exists() or (backup_dir / "committed_diff.patch").exists()
        ))
        res_payload = {
            "status": "success",
            "change": resolved_change,
            "target_gate": canonical_tag,
            "backup_directory": str(backup_dir.relative_to(repo_root)) if has_backups else None,
            "has_backups": has_backups,
            "backed_up_files": backed_up_files,
            "restored_files": restored_files,
            "removed_files": removed_files,
            "reset_tasks_count": reset_tasks_count,
            "git_reset_performed": git_reset_performed,
            "checkpoint_found": bool(checkpoint_info),
            "message": f"Successfully rolled back to {canonical_tag}. Restored {len(restored_files)} files, removed {len(removed_files)} new files, backed up to {backup_dir.name}/.",
        }

        try:
            def update_rb(entry: Dict[str, Any]) -> None:
                entry["phase"] = canonical_tag
                entry["evidence"]["review"] = make_default_review_evidence()
                if canonical_tag == "design":
                    entry["blockers"] = []
                    entry["evidence"]["implementation"]["status"] = "PENDING"
                    entry["evidence"]["implementation"]["tests_passed"] = None
                else:
                    entry["blockers"] = [b for b in entry.get("blockers", []) if not b.startswith("Review:")]
            self.ledger.mutate_change(repo_root, resolved_change, update_rb)
        except Exception as exc:
            raise RuntimeError(f"Files restored but ledger update failed; backups are in {backup_dir}") from exc

        return res_payload
