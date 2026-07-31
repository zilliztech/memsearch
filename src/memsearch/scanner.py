"""Multi-path file scanner for markdown knowledge bases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pathspec import GitIgnoreSpec


@dataclass(frozen=True)
class ScannedFile:
    """Metadata for a discovered markdown file."""

    path: Path
    mtime: float
    size: int


def scan_paths(
    paths: list[str | Path],
    *,
    extensions: tuple[str, ...] = (".md", ".markdown"),
    ignore_hidden: bool = True,
    ignore_files: list[str] | tuple[str, ...] | None = None,
    exclude: list[str] | tuple[str, ...] | None = None,
) -> list[ScannedFile]:
    """Recursively scan *paths* for markdown files.

    Each entry in *paths* may be a file or directory.  Directories are
    walked recursively.  Hidden files/dirs (starting with ``"."``) are
    skipped when *ignore_hidden* is ``True``. Ignore files are discovered at
    each directory within an explicit directory root and never from a parent
    directory. Explicit file paths always remain eligible for indexing.
    """
    results: list[ScannedFile] = []
    seen: set[str] = set()
    policy = IgnorePolicy(ignore_files=ignore_files, exclude=exclude)

    for p in paths:
        root = Path(p).expanduser().resolve()
        if root.is_file():
            _maybe_add(root, extensions, seen, results)
        elif root.is_dir():
            matcher = policy.matcher(root)
            for dirpath, dirnames, filenames in os.walk(root):
                directory = Path(dirpath)
                matcher.load_directory(directory)
                if ignore_hidden:
                    dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                if policy.enabled:
                    dirnames[:] = [
                        dirname
                        for dirname in dirnames
                        if not matcher.is_ignored(directory / dirname, is_directory=True)
                    ]
                for fname in filenames:
                    if ignore_hidden and fname.startswith("."):
                        continue
                    fp = Path(dirpath) / fname
                    if policy.enabled and matcher.is_ignored(fp):
                        continue
                    _maybe_add(fp, extensions, seen, results)

    results.sort(key=lambda f: f.path)
    return results


def _maybe_add(
    fp: Path,
    extensions: tuple[str, ...],
    seen: set[str],
    results: list[ScannedFile],
) -> None:
    if fp.suffix.lower() not in extensions:
        return
    real = str(fp.resolve())
    if real in seen:
        return
    seen.add(real)
    stat = fp.stat()
    results.append(ScannedFile(path=fp, mtime=stat.st_mtime, size=stat.st_size))


class IgnorePolicy:
    """Gitignore-compatible rules applied independently to each index root."""

    def __init__(
        self,
        *,
        ignore_files: list[str] | tuple[str, ...] | None = None,
        exclude: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.ignore_files = _normalize_ignore_file_names(ignore_files or ())
        self.exclude = tuple(str(pattern) for pattern in (exclude or ()))
        self.enabled = bool(self.ignore_files or self.exclude)

    def matcher(self, root: Path) -> _RootIgnoreMatcher:
        """Create a matcher whose ignore discovery is bounded by *root*."""
        return _RootIgnoreMatcher(root.resolve(), self.ignore_files, self.exclude)


class _RootIgnoreMatcher:
    """Ignore matcher for one directory root."""

    def __init__(self, root: Path, ignore_files: tuple[str, ...], exclude: tuple[str, ...]) -> None:
        self.root = root
        self.ignore_files = ignore_files
        self._specs_by_directory: dict[Path, tuple[GitIgnoreSpec, ...]] = {}
        self._exclude_spec = GitIgnoreSpec.from_lines(exclude) if exclude else None

    def load_directory(self, directory: Path) -> None:
        """Load configured ignore files located directly in *directory*."""
        directory = directory.resolve()
        if directory in self._specs_by_directory:
            return
        try:
            directory.relative_to(self.root)
        except ValueError:
            return

        specs: list[GitIgnoreSpec] = []
        for name in self.ignore_files:
            ignore_path = directory / name
            if not ignore_path.is_file():
                continue
            lines = ignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
            specs.append(GitIgnoreSpec.from_lines(lines))
        self._specs_by_directory[directory] = tuple(specs)

    def load_ancestors(self, path: Path) -> None:
        """Load ignore files from the root through the path's parent."""
        path = path.resolve()
        try:
            relative_parent = path.parent.relative_to(self.root)
        except ValueError:
            return

        directory = self.root
        self.load_directory(directory)
        for part in relative_parent.parts:
            directory /= part
            self.load_directory(directory)

    def is_ignored(self, path: Path, *, is_directory: bool = False) -> bool:
        """Return whether *path* is excluded by the currently loaded rules."""
        path = path.resolve()
        try:
            root_relative = path.relative_to(self.root)
        except ValueError:
            return False

        ignored = False
        directory = self.root
        for part in path.parent.relative_to(self.root).parts:
            ignored = self._apply_directory_specs(directory, path, is_directory, ignored)
            directory /= part
        ignored = self._apply_directory_specs(directory, path, is_directory, ignored)

        if self._exclude_spec is not None:
            candidate = root_relative.as_posix()
            if is_directory:
                candidate += "/"
            result = self._exclude_spec.check_file(candidate)
            if result.include is not None:
                ignored = result.include
        return ignored

    def _apply_directory_specs(self, directory: Path, path: Path, is_directory: bool, ignored: bool) -> bool:
        for spec in self._specs_by_directory.get(directory, ()):
            candidate = path.relative_to(directory).as_posix()
            if is_directory:
                candidate += "/"
            result = spec.check_file(candidate)
            if result.include is not None:
                ignored = result.include
        return ignored


def should_index_path(
    path: str | Path,
    roots: list[str | Path],
    *,
    extensions: tuple[str, ...] = (".md", ".markdown"),
    ignore_hidden: bool = True,
    ignore_files: list[str] | tuple[str, ...] | None = None,
    exclude: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Return whether a watcher event should be indexed under *roots*.

    The function rebuilds matchers from disk so edits to ignore files affect
    subsequent file events without restarting the watcher.
    """
    candidate = Path(path).expanduser().resolve()
    if candidate.suffix.lower() not in extensions:
        return False

    policy = IgnorePolicy(ignore_files=ignore_files, exclude=exclude)
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if root.is_file():
            if candidate == root:
                return True
            continue
        if not root.is_dir():
            continue
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if ignore_hidden and any(part.startswith(".") for part in relative.parts):
            continue
        if not policy.enabled:
            return True
        matcher = policy.matcher(root)
        matcher.load_ancestors(candidate)
        if not matcher.is_ignored(candidate):
            return True
    return False


def _normalize_ignore_file_names(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_name in names:
        name = str(raw_name).strip()
        if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError(f"Ignore file must be a filename without directory components: {raw_name!r}")
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)
