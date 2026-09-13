"""Checkpoint creation and rollback manager."""

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional

from .trailers import canonicalize_gate_name


def _backup_path(src: Path, dest: Path) -> None:
    """Helper to backup a file or directory into destination directory."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if src.is_file():
            shutil.copy2(src, dest)
        elif src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
    except Exception:
        pass


class CheckpointManager:
    """Manages working-tree and Git ref checkpoints and safe rollback state restoration."""

    def __init__(self, vcs_client: Any, config_manager: Any, ledger_store: Any):
        self.vcs = vcs_client
        self.config_manager = config_manager
        self.ledger = ledger_store

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
                    env = {**os.environ, "GIT_INDEX_FILE": str(Path(idx_dir) / "index")}
                    self.vcs.run_cmd(repo_root, "read-tree", commit_sha, env=env, check=True)
                    self.vcs.run_cmd(repo_root, "add", "-A", "--", ".", ":!.scratch", ":!scratch", ":!.gemini", ":!.ship", env=env, check=True)
                    tree_sha = self.vcs.run_cmd(repo_root, "write-tree", env=env, check=True).stdout.strip()
                    commit_msg = f"ship-checkpoint:{resolved_change}:{canonical_tag}"
                    snapshot_sha = self.vcs.run_cmd(repo_root, "commit-tree", tree_sha, "-p", commit_sha, "-m", commit_msg, env=env, check=True).stdout.strip()
            except Exception:
                snapshot_sha = None

            target_ref_sha = snapshot_sha or commit_sha
            try:
                self.vcs.run_cmd(repo_root, "update-ref", ref_name, target_ref_sha, check=True)
                if allow_git_tag:
                    self.vcs.run_cmd(repo_root, "tag", "-f", tag_name, target_ref_sha)
                ref_created = True
            except Exception:
                pass

        chk_dir = repo_root / ".scratch" / "checkpoints"
        chk_dir.mkdir(parents=True, exist_ok=True)
        receipt_file = chk_dir / f"{resolved_change}_{canonical_tag}.json"
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
        except Exception:
            pass

        return receipt_data

    def perform_rollback(
        self,
        repo_root: Path,
        target_gate: str,
        change: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        resolved_change = change or self.ledger.get_active_change(repo_root) or "default"
        canonical_tag = canonicalize_gate_name(target_gate)

        git_info = self.vcs.get_info(repo_root)
        timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = repo_root / ".scratch" / f"rollback_{timestamp_str}"

        chk_file = repo_root / ".scratch" / "checkpoints" / f"{resolved_change}_{canonical_tag}.json"
        target_tag = f"ship/{resolved_change}/{canonical_tag}"
        target_ref = f"refs/ship/{resolved_change}/{canonical_tag}"

        from .ledger import read_json_file, make_default_review_evidence
        checkpoint_info: Optional[Dict[str, Any]] = read_json_file(chk_file)

        backed_up_files: List[str] = []
        restored_files: List[str] = []
        removed_files: List[str] = []
        git_reset_performed = False

        if git_info.get("is_git"):
            target_sha: Optional[str] = (
                self.vcs.get_output(repo_root, "rev-parse", "--verify", target_ref)
                or self.vcs.get_output(repo_root, "rev-parse", "--verify", target_tag)
                or (checkpoint_info.get("snapshot_commit") if checkpoint_info else None)
                or (checkpoint_info.get("commit") if checkpoint_info else None)
            )

            base_commit = (
                checkpoint_info.get("commit")
                if checkpoint_info and checkpoint_info.get("commit") and checkpoint_info.get("commit") != "none"
                else None
            )
            current_sha = git_info.get("commit")
            backup_dir.mkdir(parents=True, exist_ok=True)

            working_diff = self.vcs.run_cmd(repo_root, "diff", "--no-renames", "HEAD", text=False).stdout
            if working_diff:
                (backup_dir / "working_diff.patch").write_bytes(working_diff)

            if target_sha and current_sha and current_sha != target_sha and target_sha != "none":
                commit_diff = self.vcs.run_cmd(repo_root, "diff", "--no-renames", target_sha, "HEAD", text=False).stdout
                if commit_diff:
                    (backup_dir / "committed_diff.patch").write_bytes(commit_diff)

            for src_path_str in git_info.get("modified_source_files", []):
                full_src = repo_root / src_path_str
                if full_src.is_file():
                    _backup_path(full_src, backup_dir / src_path_str)
                    if src_path_str not in backed_up_files:
                        backed_up_files.append(src_path_str)

            if target_sha and target_sha != "none":
                try:
                    diff_files = self.vcs.get_output(repo_root, "diff", "--no-renames", "--name-only", target_sha).splitlines()
                    untracked_files = self.vcs.get_output(repo_root, "ls-files", "--others", "--exclude-standard").splitlines()
                    changed_files = [f.strip() for f in diff_files if f.strip()]
                    for p in [f.strip() for f in untracked_files if f.strip()]:
                        if p not in changed_files:
                            changed_files.append(p)

                    ignored_prefixes = (".scratch/", "scratch/", ".ship/", "ship/", ".gemini/", ".git/")
                    tasks_rel = f"openspec/changes/{resolved_change}/tasks.md"

                    for rel_path in changed_files:
                        if any(rel_path.startswith(p) for p in ignored_prefixes) or rel_path == tasks_rel:
                            continue

                        full_path = repo_root / rel_path
                        if (full_path.is_file() or full_path.is_dir()) and rel_path not in backed_up_files:
                            _backup_path(full_path, backup_dir / rel_path)
                            backed_up_files.append(rel_path)

                        if self.vcs.run_cmd(repo_root, "cat-file", "-e", f"{target_sha}:{rel_path}").returncode == 0:
                            if self.vcs.run_cmd(repo_root, "checkout", target_sha, "--", rel_path).returncode == 0:
                                restored_files.append(rel_path)
                        else:
                            safety_stash = backup_dir / "untracked_removed" / rel_path
                            _backup_path(full_path, safety_stash)
                            if full_path.is_file():
                                self.vcs.run_cmd(repo_root, "rm", "-f", "--cached", rel_path)
                                full_path.unlink(missing_ok=True)
                                parent = full_path.parent
                                while parent != repo_root and parent.is_dir():
                                    try:
                                        parent.rmdir()
                                        parent = parent.parent
                                    except OSError:
                                        break
                            elif full_path.is_dir():
                                self.vcs.run_cmd(repo_root, "rm", "-rf", "--cached", rel_path)
                                shutil.rmtree(full_path, ignore_errors=True)
                            removed_files.append(rel_path)

                    reset_target = base_commit or target_sha
                    if current_sha and reset_target and current_sha != reset_target and reset_target != "none":
                        if self.vcs.run_cmd(repo_root, "reset", reset_target).returncode == 0:
                            git_reset_performed = True
                    elif restored_files or removed_files:
                        git_reset_performed = True
                except Exception:
                    pass

        pkg_dir = repo_root / "openspec" / "changes" / resolved_change
        tasks_file = pkg_dir / "tasks.md"
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
        except Exception:
            pass

        return res_payload
