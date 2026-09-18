"""Validated identifiers and repository-contained paths for lifecycle operations."""

from pathlib import Path
import re


def validate_change_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) or ".." in value:
        raise ValueError("Change ID must be a simple identifier without path separators or traversal")
    return value


def repository_path(repo_root: Path, relative: str) -> Path:
    """Resolve a managed path without following symlinks, including ancestor links."""
    path = Path(relative)
    if not relative or path.is_absolute() or "\\" in relative or any(p in {"", ".", ".."} for p in relative.split("/")):
        raise ValueError(f"Unsafe repository-relative path: {relative!r}")
    root = repo_root.resolve()
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Symlinks are not allowed in managed lifecycle paths: {candidate}")
    candidate.resolve().relative_to(root)
    # Keep caller's root spelling (e.g. /var versus /private/var on macOS).
    return repo_root / path


def resolve_change_path(repo_root: Path, change_id: str) -> Path:
    return repository_path(repo_root, f"openspec/changes/{validate_change_id(change_id)}")
