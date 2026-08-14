"""Collision-safe move of a successfully-printed PDF into a sibling
`PrintedCompleted` folder."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, Tuple

from ..config import ARCHIVE_DIR_NAME
from ..errors import ArchiveError


class ArchiveService:
    def __init__(self, archive_dir_name: str = ARCHIVE_DIR_NAME) -> None:
        self._archive_dir_name = archive_dir_name

    @staticmethod
    def stat_fingerprint(path: Path) -> Optional[Tuple[int, float]]:
        """Capture (size, mtime) so callers can later verify the source
        hasn't changed since a print session started."""
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_size, st.st_mtime)

    def archive(
        self,
        source: Path,
        expected_fingerprint: Optional[Tuple[int, float]] = None,
    ) -> Path:
        if not source.exists():
            raise ArchiveError(f"Source file no longer exists: {source}")

        if expected_fingerprint is not None:
            current = self.stat_fingerprint(source)
            if current != expected_fingerprint:
                raise ArchiveError(
                    f"Source file changed since the session started; not archived: {source}"
                )

        dest_dir = source.parent / self._archive_dir_name
        try:
            dest_dir.mkdir(exist_ok=True)
        except OSError as exc:
            raise ArchiveError(f"Could not create {dest_dir}: {exc}") from exc

        destination = self._unique_path(dest_dir / source.name)
        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            raise ArchiveError(f"Could not move file into {dest_dir}: {exc}") from exc
        return destination

    @staticmethod
    def _unique_path(path: Path) -> Path:
        """Never overwrite an existing file — append " (1)", " (2)", ... until
        a free name is found."""
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        n = 1
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        while candidate.exists():
            n += 1
            candidate = path.with_name(f"{stem} ({n}){suffix}")
        return candidate
