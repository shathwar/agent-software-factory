"""OpenSpec, ADRs, and specification lifecycle management."""

from collections import OrderedDict
import datetime
import functools
import json
from pathlib import Path
import re
import shutil
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import ShipConfigManager
from .evidence import validate_design_approval
from .paths import repository_path, resolve_change_path, validate_change_id, get_state_file
from .transactions import atomic_write, begin_archive, record_archive_progress, recover_archive, sync_directory

REMOVAL_TITLE_MARKER = re.compile(
    r"(?:\s*[\[\(]\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\s*[\]\)]|\s*--\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\b|\s*\bSTATUS:\s*(?:REMOVED|DELETED)\b)",
    re.IGNORECASE,
)

REMOVAL_BODY_MARKER = re.compile(
    r"^\s*(?:[\[\(]\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\s*[\]\)]|--\s*(?:STATUS:\s*)?(?:REMOVED|DELETED)\b|\bSTATUS:\s*(?:REMOVED|DELETED)\b)",
    re.IGNORECASE,
)


def normalize_req_title(raw_title: str) -> str:
    """Normalize requirement title for matching, removing explicit removal markers, brackets, and markdown formatting."""
    cleaned = REMOVAL_TITLE_MARKER.sub("", raw_title).strip()
    cleaned = cleaned.strip("*`\"' ")
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1].strip()
    cleaned = re.sub(r"^\[[A-Za-z0-9_-]+\]\s*", "", cleaned)
    cleaned = re.sub(r"^[A-Za-z0-9_-]+:\s*", "", cleaned)
    return cleaned.strip("*`\"' ").strip().lower()


def parse_requirements_doc(content: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse a markdown spec into preamble and individual requirement sections."""
    lines = content.splitlines(keepends=True)
    req_header_regex = re.compile(r"^(#{1,4})\s+Requirement:\s*(.+)$", re.IGNORECASE)

    preamble_lines: List[str] = []
    requirements: List[Dict[str, Any]] = []
    current_req: Optional[Dict[str, Any]] = None

    for line in lines:
        match = req_header_regex.match(line.rstrip("\r\n"))
        if match:
            if current_req is not None:
                requirements.append(current_req)
            level = match.group(1)
            raw_title = match.group(2).strip()
            is_removal = bool(REMOVAL_TITLE_MARKER.search(raw_title))
            norm_key = normalize_req_title(raw_title)
            current_req = {
                "header": line.rstrip("\r\n"),
                "level": level,
                "raw_title": raw_title,
                "key": norm_key,
                "body_lines": [],
                "is_removal": is_removal,
            }
        else:
            if current_req is None:
                preamble_lines.append(line)
            else:
                current_req["body_lines"].append(line)

    if current_req is not None:
        requirements.append(current_req)

    for req in requirements:
        if not req["is_removal"]:
            for bline in req["body_lines"][:3]:
                stripped = bline.strip()
                if stripped and REMOVAL_BODY_MARKER.match(stripped):
                    req["is_removal"] = True
                    break

    preamble = "".join(preamble_lines)
    return preamble, requirements


def merge_spec_requirements(living_content: str, delta_content: str) -> str:
    """Merge delta requirements into living spec, preserving untouched requirements."""
    living_preamble, living_reqs = parse_requirements_doc(living_content)
    delta_preamble, delta_reqs = parse_requirements_doc(delta_content)

    if not living_reqs and not delta_reqs:
        if not living_content.strip():
            return delta_content
        return living_content.rstrip() + "\n\n" + delta_content.strip() + "\n"

    if not living_reqs and delta_reqs:
        return delta_content

    living_dict: OrderedDict[str, Dict[str, Any]] = OrderedDict()
    for req in living_reqs:
        living_dict[req["key"]] = req

    for d_req in delta_reqs:
        key = d_req["key"]
        if d_req["is_removal"]:
            if key in living_dict:
                del living_dict[key]
        else:
            living_dict[key] = d_req

    preamble = living_preamble if living_preamble.strip() else delta_preamble
    result: List[str] = []
    if preamble.strip():
        result.append(preamble.rstrip())

    for req in living_dict.values():
        clean_header = REMOVAL_TITLE_MARKER.sub("", req["header"]).rstrip()
        body = "".join(req["body_lines"]).strip()
        if body:
            result.append(f"{clean_header}\n{body}")
        else:
            result.append(clean_header)

    return "\n\n".join(result).strip() + "\n"


def _locked_workspace(method):
    @functools.wraps(method)
    def run(self, repo_root, *args, **kwargs):
        from .ledger import FileLedgerStore
        with FileLedgerStore.lock(repo_root):
            FileLedgerStore.load(repo_root, auto_sync=False)
            return method(self, repo_root, *args, **kwargs)
    return run


class OpenSpecRepository:
    """Manages discovery and manipulation of OpenSpec change packages, ADRs, and living specs."""

    def inspect_adrs(self, repo_root: Path) -> List[Dict[str, Any]]:
        """Scan docs/adr/ for architecture decision records."""
        adr_dir = repo_root / "docs" / "adr"
        adrs = []
        if not adr_dir.exists():
            return adrs

        for path in sorted(adr_dir.glob("*.md")):
            if path.name.lower() in {"readme.md", "template.md"}:
                continue
            content = path.read_text(encoding="utf-8", errors="replace")
            status_match = re.search(r"\*\*Status\*\*:\s*([A-Za-z0-9_-]+)", content, re.IGNORECASE)
            status = status_match.group(1).upper() if status_match else "UNKNOWN"
            adrs.append({
                "name": path.name,
                "path": str(path.relative_to(repo_root)),
                "status": status,
            })
        return adrs

    @_locked_workspace
    def inspect_openspec(
        self,
        repo_root: Path,
        target_change: Optional[str] = None,
        get_active_fn: Optional[Callable[[Path], Optional[str]]] = None,
        clear_active_fn: Optional[Callable[[Path], Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Scan openspec/changes/ for active change packages and parse tasks.md."""
        resolved_target = validate_change_id(target_change) if target_change is not None else None
        changes_dir = repository_path(repo_root, "openspec/changes")
        archive_dir = repository_path(repo_root, "openspec/archive")
        packages = []

        def target_is_archived(target: str) -> bool:
            if archive_dir.exists():
                for d in archive_dir.iterdir():
                    if d.is_dir() and (d.name == target or d.name.endswith(f"-{target}")):
                        return True
            state_file = get_state_file(repo_root)
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    entry = data.get("changes", {}).get(target, {})
                    if entry.get("evidence", {}).get("delivery", {}).get("status") == "ARCHIVED":
                        return True
                except Exception:
                    pass
            return False

        if not changes_dir.exists():
            if resolved_target and not target_is_archived(resolved_target):
                raise ValueError(f"Specified OpenSpec change '{resolved_target}' not found (openspec/changes does not exist).")
            return packages

        if resolved_target:
            target_dir = resolve_change_path(repo_root, resolved_target)
            if not target_dir.exists() or not target_dir.is_dir():
                if target_is_archived(resolved_target):
                    return packages
                available = [d.name for d in sorted(changes_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
                avail_str = f" Available: {', '.join(available)}" if available else " (no packages found)"
                raise ValueError(f"Specified OpenSpec change '{resolved_target}' not found under openspec/changes/.{avail_str}")

        active_persisted = resolved_target or (get_active_fn(repo_root) if get_active_fn else None)
        if active_persisted and not resolved_target:
            if not (resolve_change_path(repo_root, active_persisted)).is_dir():
                if clear_active_fn:
                    clear_active_fn(repo_root)
                active_persisted = None

        for change_dir in changes_dir.iterdir():
            if change_dir.name.startswith("."):
                continue
            change_dir = resolve_change_path(repo_root, change_dir.name)
            if not change_dir.is_dir():
                continue

            tasks_file = repository_path(repo_root, str((change_dir / "tasks.md").relative_to(repo_root)))
            tasks_found = False
            total_tasks = 0
            completed_tasks = 0
            next_task = None
            task_list = []

            if tasks_file.exists():
                tasks_found = True
                content = tasks_file.read_text(encoding="utf-8", errors="replace")
                task_counter = 0
                for line in content.splitlines():
                    stripped = line.strip()
                    is_pending = stripped.startswith(("- [ ]", "* [ ]"))
                    is_done = stripped.startswith(("- [x]", "- [X]", "* [x]", "* [X]"))
                    if is_pending or is_done:
                        task_counter += 1
                        total_tasks += 1
                        task_text = stripped[5:].strip()
                        m = re.match(r"^([A-Za-z0-9_.-]+)\b(?:\s*[:.-])?\s*(.*)", task_text)
                        if m and any(c.isdigit() for c in m.group(1)):
                            tid = m.group(1)
                            desc = m.group(2).strip() or task_text
                        else:
                            tid = f"T{task_counter}"
                            desc = task_text
                        task_list.append({
                            "task_id": tid,
                            "description": desc,
                            "completed": is_done,
                            "raw": stripped,
                        })
                        if is_done:
                            completed_tasks += 1
                        elif next_task is None:
                            next_task = task_text

            proposal_file = change_dir / "proposal.md"
            specs_dir = change_dir / "specs"

            try:
                mtime = change_dir.stat().st_mtime
            except Exception:
                mtime = 0.0

            packages.append({
                "change": change_dir.name,
                "path": str(change_dir.relative_to(repo_root)),
                "has_proposal": proposal_file.exists(),
                "has_specs": specs_dir.exists() and any(specs_dir.iterdir()) if specs_dir.exists() else False,
                "has_tasks": tasks_found,
                "total_tasks": total_tasks,
                "completed_tasks": completed_tasks,
                "pending_tasks": total_tasks - completed_tasks,
                "next_task": next_task,
                "task_list": task_list,
                "mtime": mtime,
                "is_active_target": (change_dir.name == active_persisted),
            })

        packages.sort(
            key=lambda p: (
                1 if p["is_active_target"] else 0,
                1 if p["pending_tasks"] > 0 else 0,
                p["mtime"],
                p["change"],
            ),
            reverse=True,
        )
        return packages

    def inspect_archived_openspec(self, repo_root: Path) -> List[Dict[str, Any]]:
        """Scan openspec/archive/ for completed historical change packages."""
        archive_dir = repository_path(repo_root, "openspec/archive")
        archived = []
        if not archive_dir.exists():
            return archived

        for child in sorted(archive_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                archived.append({
                    "name": child.name,
                    "path": str(child.relative_to(repo_root)),
                })
        return archived

    def inspect_living_specs(self, repo_root: Path) -> List[Dict[str, Any]]:
        """Scan openspec/specs/ for living cumulative system specifications."""
        specs_dir = repository_path(repo_root, "openspec/specs")
        specs = []
        if not specs_dir.exists():
            return specs

        for child in sorted(specs_dir.glob("*.md")):
            specs.append({
                "name": child.name,
                "path": str(child.relative_to(repo_root)),
            })
        return specs

    @_locked_workspace
    def archive_change(
        self,
        repo_root: Path,
        change: Optional[str] = None,
        force: bool = False,
        load_ledger_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        inspect_review_fn: Optional[Callable[..., Any]] = None,
        get_git_info_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
        clear_active_fn: Optional[Callable[[Path, Optional[str]], Any]] = None,
        generate_trailers_fn: Optional[Callable[..., List[str]]] = None,
        mutate_change_fn: Optional[Callable[..., Any]] = None,
        get_active_fn: Optional[Callable[[Path], Optional[str]]] = None,
    ) -> Dict[str, Any]:
        """Sync delta specs from changes to openspec/specs/, then move change package to openspec/archive/."""
        changes_dir = repository_path(repo_root, "openspec/changes")
        if not changes_dir.exists():
            raise FileNotFoundError(f"No openspec/changes directory found at {changes_dir}")

        resolved_target = validate_change_id(change) if change is not None else None
        if not resolved_target and load_ledger_fn:
            try:
                ledger = load_ledger_fn(repo_root, auto_sync=False)
                if isinstance(ledger, dict):
                    resolved_target = ledger.get("active_change_id")
            except Exception:
                pass
        if not resolved_target and get_active_fn:
            try:
                resolved_target = get_active_fn(repo_root)
            except Exception:
                pass

        if resolved_target and (resolve_change_path(repo_root, resolved_target)).is_dir():
            change_dir = resolve_change_path(repo_root, resolved_target)
        elif resolved_target and change:
            raise FileNotFoundError(f"OpenSpec change directory '{resolved_target}' not found under {changes_dir}")
        else:
            packages = self.inspect_openspec(
                repo_root,
                target_change=resolved_target,
                get_active_fn=get_active_fn,
            )
            if not packages:
                raise FileNotFoundError("No active change packages found in openspec/changes/ to archive.")
            change_dir = repo_root / packages[0]["path"]

        change_name = change_dir.name

        if not force:
            from .gates import validate_delivery_readiness
            from .ledger import FileLedgerStore
            from .evidence import inspect_review_reports, inspect_spikes
            from .vcs import GitClient
            current = (load_ledger_fn(repo_root, auto_sync=False) if load_ledger_fn else FileLedgerStore.load(repo_root, auto_sync=False)).get("changes", {}).get(change_name)
            packages = self.inspect_openspec(repo_root, target_change=change_name)
            report = (inspect_review_fn or inspect_review_reports)(repo_root, change=change_name)
            git_info = (get_git_info_fn or GitClient().get_info)(repo_root)
            specs = repository_path(repo_root, str((change_dir / "specs").relative_to(repo_root)))
            decision = validate_delivery_readiness(
                report, packages[0], git_info, current,
                design_error=validate_design_approval(repo_root, change_name, current),
                package_spec_names={path.name for path in specs.glob("*.md")},
                spikes=inspect_spikes(repo_root),
                repo_root=repo_root, verification_config=ShipConfigManager.load(repo_root),
            )
            if decision[1] != "DELIVERY_READY":
                raise RuntimeError(f"Cannot archive '{change_name}': {decision[2]}")

        synced_specs = []
        living_specs_dir = repository_path(repo_root, "openspec/specs")
        source_specs_dir = repository_path(repo_root, str((change_dir / "specs").relative_to(repo_root)))

        prepared_updates: Dict[Path, Tuple[Optional[bytes], str]] = {}
        if source_specs_dir.exists() and source_specs_dir.is_dir():
            for spec_file in sorted(source_specs_dir.glob("*.md")):
                spec_file = repository_path(repo_root, str(spec_file.relative_to(repo_root)))
                dest_spec = repository_path(repo_root, f"openspec/specs/{spec_file.name}")
                delta_text = spec_file.read_text(encoding="utf-8", errors="replace")
                if dest_spec.exists():
                    original_bytes = dest_spec.read_bytes()
                    merged_text = merge_spec_requirements(original_bytes.decode("utf-8", errors="replace"), delta_text)
                    prepared_updates[dest_spec] = (original_bytes, merged_text)
                else:
                    prepared_updates[dest_spec] = (None, delta_text)

        date_str = datetime.date.today().strftime("%Y-%m-%d")
        archive_dir = repository_path(repo_root, "openspec/archive")
        archive_dir.mkdir(parents=True, exist_ok=True)
        sync_directory(archive_dir.parent)
        if change_dir.stat().st_dev != archive_dir.stat().st_dev:
            raise ValueError("Archive source and destination must be on the same filesystem")

        dest_archive = archive_dir / f"{date_str}-{change_name}"
        if dest_archive.exists():
            dest_archive = archive_dir / f"{date_str}-{change_name}-{uuid.uuid4().hex}"

        # Validate/generate evidence before moving the reviewed files.
        trailers = generate_trailers_fn(repo_root, change_id=change_name) if generate_trailers_fn else []
        trailers = [t for t in trailers if not t.startswith("Ship-Delivery:")]
        trailers.append("Ship-Delivery: ARCHIVED")
        operation_id = uuid.uuid4().hex
        begin_archive(repo_root, operation_id, change_name, dest_archive, prepared_updates)
        try:
            living_specs_dir.mkdir(parents=True, exist_ok=True)
            sync_directory(living_specs_dir.parent)
            for dest_spec, (original_text, new_text) in prepared_updates.items():
                atomic_write(dest_spec, new_text.encode("utf-8"), tag=operation_id)
                synced_specs.append(dest_spec.name)

            record_archive_progress(repo_root, "specs_written")
            shutil.move(str(change_dir), str(dest_archive))
            sync_directory(change_dir.parent)
            sync_directory(dest_archive.parent)
            record_archive_progress(repo_root, "package_moved")
            if mutate_change_fn:
                def update_delivery(entry: Dict[str, Any]) -> None:
                    entry["phase"] = "delivery"
                    entry["evidence"]["delivery"]["status"] = "ARCHIVED"
                    entry["evidence"]["delivery"]["archive_operation_id"] = operation_id
                    entry["evidence"]["delivery"]["archived_path"] = str(dest_archive.relative_to(repo_root))
                    entry["evidence"]["delivery"]["trailers"] = trailers
                # This final atomic write also clears the active pointer. No ledger
                # mutation occurs before filesystem changes can be rolled back.
                mutate_change_fn(repo_root, change_name, update_delivery, set_active=False)
            else:
                from .ledger import FileLedgerStore
                def commit_archive(entry):
                    entry["phase"] = "delivery"
                    entry["evidence"]["delivery"].update(status="ARCHIVED", archive_operation_id=operation_id,
                                                       archived_path=str(dest_archive.relative_to(repo_root)), trailers=trailers)
                FileLedgerStore.mutate_change(repo_root, change_name, commit_archive, set_active=False)
            recover_archive(repo_root)

        except Exception as err:
            try:
                outcome = recover_archive(repo_root)
            except Exception as recovery_err:
                raise RuntimeError(f"Archive failed: {err}; recovery incomplete: {recovery_err}") from err
            if outcome == "committed":
                raise RuntimeError(f"Archive committed but finalization failed: {err}") from err
            raise RuntimeError(f"Archive failed during execution; restored package and living specs: {err}") from err

        return {
            "change": change_name,
            "synced_specs": synced_specs,
            "living_specs_dir": str(living_specs_dir.relative_to(repo_root)),
            "archived_path": str(dest_archive.relative_to(repo_root)),
            "trailers": trailers,
        }
