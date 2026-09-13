"""OpenSpec, ADRs, and specification lifecycle management."""

from collections import OrderedDict
import datetime
import json
from pathlib import Path
import re
import shutil
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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

    def inspect_openspec(
        self,
        repo_root: Path,
        target_change: Optional[str] = None,
        get_active_fn: Optional[Callable[[Path], Optional[str]]] = None,
        clear_active_fn: Optional[Callable[[Path], Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Scan openspec/changes/ for active change packages and parse tasks.md."""
        resolved_target = target_change
        changes_dir = repo_root / "openspec" / "changes"
        archive_dir = repo_root / "openspec" / "archive"
        packages = []

        def target_is_archived(target: str) -> bool:
            if archive_dir.exists():
                for d in archive_dir.iterdir():
                    if d.is_dir() and (d.name == target or d.name.endswith(f"-{target}")):
                        return True
            state_file = repo_root / ".ship" / "state.json"
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
            target_dir = changes_dir / resolved_target
            if not target_dir.exists() or not target_dir.is_dir():
                if target_is_archived(resolved_target):
                    return packages
                available = [d.name for d in sorted(changes_dir.iterdir()) if d.is_dir() and not d.name.startswith(".")]
                avail_str = f" Available: {', '.join(available)}" if available else " (no packages found)"
                raise ValueError(f"Specified OpenSpec change '{resolved_target}' not found under openspec/changes/.{avail_str}")

        active_persisted = resolved_target or (get_active_fn(repo_root) if get_active_fn else None)
        if active_persisted and not resolved_target:
            if not (changes_dir / active_persisted).is_dir():
                if clear_active_fn:
                    clear_active_fn(repo_root)
                active_persisted = None

        for change_dir in changes_dir.iterdir():
            if not change_dir.is_dir() or change_dir.name.startswith("."):
                continue

            tasks_file = change_dir / "tasks.md"
            tasks_found = False
            total_tasks = 0
            completed_tasks = 0
            next_task = None

            if tasks_file.exists():
                tasks_found = True
                content = tasks_file.read_text(encoding="utf-8", errors="replace")
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- [ ]") or stripped.startswith("* [ ]"):
                        total_tasks += 1
                        if next_task is None:
                            next_task = stripped[5:].strip()
                    elif stripped.startswith(("- [x]", "- [X]", "* [x]", "* [X]")):
                        total_tasks += 1
                        completed_tasks += 1

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
        archive_dir = repo_root / "openspec" / "archive"
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
        specs_dir = repo_root / "openspec" / "specs"
        specs = []
        if not specs_dir.exists():
            return specs

        for child in sorted(specs_dir.glob("*.md")):
            specs.append({
                "name": child.name,
                "path": str(child.relative_to(repo_root)),
            })
        return specs

    def archive_change(
        self,
        repo_root: Path,
        change: Optional[str] = None,
        force: bool = False,
        load_ledger_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        inspect_review_fn: Optional[Callable[..., Any]] = None,
        validate_review_fn: Optional[Callable[..., Any]] = None,
        get_git_info_fn: Optional[Callable[[Path], Dict[str, Any]]] = None,
        clear_active_fn: Optional[Callable[[Path, Optional[str]], Any]] = None,
        generate_trailers_fn: Optional[Callable[..., str]] = None,
        mutate_change_fn: Optional[Callable[..., Any]] = None,
        get_active_fn: Optional[Callable[[Path], Optional[str]]] = None,
    ) -> Dict[str, Any]:
        """Sync delta specs from changes to openspec/specs/, then move change package to openspec/archive/."""
        changes_dir = repo_root / "openspec" / "changes"
        if not changes_dir.exists():
            raise FileNotFoundError(f"No openspec/changes directory found at {changes_dir}")

        resolved_target = change
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

        if resolved_target and (changes_dir / resolved_target).is_dir():
            change_dir = changes_dir / resolved_target
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
            tasks_file = change_dir / "tasks.md"
            if not tasks_file.exists():
                raise RuntimeError(f"Cannot archive '{change_name}': tasks.md does not exist.")
            content = tasks_file.read_text(encoding="utf-8", errors="replace")
            has_pending = False
            has_tasks = False
            for line in content.splitlines():
                s = line.strip()
                if s.startswith("- [ ]") or s.startswith("* [ ]"):
                    has_pending = True
                    has_tasks = True
                elif s.startswith(("- [x]", "- [X]", "* [x]", "* [X]")):
                    has_tasks = True
            if not has_tasks:
                raise RuntimeError(f"Cannot archive '{change_name}': tasks.md contains no tasks.")
            if has_pending:
                raise RuntimeError(f"Cannot archive '{change_name}': package has pending tasks in tasks.md. Complete all tasks before archiving or use --force.")

            if load_ledger_fn:
                ledger = load_ledger_fn(repo_root, auto_sync=False)
                change_entry = ledger.get("changes", {}).get(change_name)
                if change_entry:
                    blockers = change_entry.get("blockers", [])
                    if blockers:
                        raise RuntimeError(
                            f"Cannot archive '{change_name}': active ledger blockers ({'; '.join(blockers)}). Remediate blockers before archiving or use --force."
                        )
                    impl_ev = change_entry.get("evidence", {}).get("implementation", {})
                    if impl_ev.get("tests_passed") is False or impl_ev.get("status") == "FAILED":
                        failed_cnt = impl_ev.get("failed_count", 1)
                        raise RuntimeError(
                            f"Cannot archive '{change_name}': {failed_cnt} test(s) failing recorded in ledger. Fix tests before archiving or use --force."
                        )

            if inspect_review_fn and validate_review_fn and get_git_info_fn:
                review_report = inspect_review_fn(repo_root, change=change_name)
                if not review_report:
                    raise RuntimeError(f"Cannot archive '{change_name}': no passing review report found (or delivery evidence in .scratch/).")

                source_specs_dir = change_dir / "specs"
                package_spec_names = {s.name for s in source_specs_dir.glob("*.md")} if source_specs_dir.exists() else set()
                git_info = get_git_info_fn(repo_root)

                review_err = validate_review_fn(review_report, change_name, git_info, package_spec_names=package_spec_names)
                if review_err:
                    msg = review_err if review_err.startswith("Judge report") else (review_err[:1].lower() + review_err[1:])
                    raise RuntimeError(f"Cannot archive '{change_name}': {msg}")

        synced_specs = []
        living_specs_dir = repo_root / "openspec" / "specs"
        source_specs_dir = change_dir / "specs"

        prepared_updates: Dict[Path, Tuple[Optional[str], str]] = {}
        if source_specs_dir.exists() and source_specs_dir.is_dir():
            for spec_file in sorted(source_specs_dir.glob("*.md")):
                dest_spec = living_specs_dir / spec_file.name
                delta_text = spec_file.read_text(encoding="utf-8", errors="replace")
                if dest_spec.exists():
                    living_text = dest_spec.read_text(encoding="utf-8", errors="replace")
                    merged_text = merge_spec_requirements(living_text, delta_text)
                    prepared_updates[dest_spec] = (living_text, merged_text)
                else:
                    prepared_updates[dest_spec] = (None, delta_text)

        date_str = datetime.date.today().strftime("%Y-%m-%d")
        archive_dir = repo_root / "openspec" / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        dest_archive = archive_dir / f"{date_str}-{change_name}"
        if dest_archive.exists():
            dest_archive = archive_dir / f"{date_str}-{change_name}-{int(time.time())}"

        applied_mutations: Dict[Path, Optional[str]] = {}
        package_moved = False
        trailers = ""
        try:
            living_specs_dir.mkdir(parents=True, exist_ok=True)
            for dest_spec, (original_text, new_text) in prepared_updates.items():
                applied_mutations[dest_spec] = original_text
                dest_spec.write_text(new_text, encoding="utf-8")
                synced_specs.append(dest_spec.name)

            shutil.move(str(change_dir), str(dest_archive))
            package_moved = True
            if clear_active_fn:
                clear_active_fn(repo_root, change_name)

            if generate_trailers_fn:
                trailers = generate_trailers_fn(repo_root, change_id=change_name)
            if mutate_change_fn:
                try:
                    def update_delivery(entry: Dict[str, Any]) -> None:
                        entry["phase"] = "delivery"
                        entry["evidence"]["delivery"]["status"] = "ARCHIVED"
                        entry["evidence"]["delivery"]["archived_path"] = str(dest_archive.relative_to(repo_root))
                        entry["evidence"]["delivery"]["trailers"] = trailers
                    mutate_change_fn(repo_root, change_name, update_delivery, set_active=False)
                except Exception:
                    pass

        except Exception as err:
            for dest_spec, original_text in applied_mutations.items():
                try:
                    if original_text is None:
                        dest_spec.unlink(missing_ok=True)
                    else:
                        dest_spec.write_text(original_text, encoding="utf-8")
                except Exception:
                    pass
            if package_moved and dest_archive.exists() and not change_dir.exists():
                try:
                    shutil.move(str(dest_archive), str(change_dir))
                except Exception:
                    pass
            raise RuntimeError(f"Archive failed during execution; rolled back living spec updates: {err}") from err

        return {
            "change": change_name,
            "synced_specs": synced_specs,
            "living_specs_dir": str(living_specs_dir.relative_to(repo_root)),
            "archived_path": str(dest_archive.relative_to(repo_root)),
            "trailers": trailers,
        }
