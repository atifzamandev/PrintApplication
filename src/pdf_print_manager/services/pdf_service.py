"""PDF validation and page splitting.

Two distinct splitting operations live here:

* `split_to_temp` — used internally by Page-by-Page printing. Always writes
  into a fresh `tempfile.TemporaryDirectory()`, never a fixed shared path.
* `split_into_folder` — backs the Tools -> Split PDF into Pages... dialog.
  Writes into a persistent sibling `<name>_split/` folder, splitting into a
  temporary directory first and only moving pages into the destination after
  the whole split succeeds, so a failure never leaves a half-written folder.

Both shell out to `pdfseparate` from poppler-utils, always as argument lists.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from ..errors import PdfServiceError, ValidationError
from ._subprocess_utils import log_subprocess

_PAGE_NUM_RE = re.compile(r"Page_(\d+)\.pdf$")
_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def page_sort_key(path: Path) -> int:
    """Numeric sort key for `Page_<n>.pdf` files, so Page_2 sorts before
    Page_10 (plain string sorting would put Page_10 first)."""
    match = _PAGE_NUM_RE.search(path.name)
    return int(match.group(1)) if match else 0


def sanitize_stem(stem: str) -> str:
    """Normalize characters that are invalid in path components to `_`."""
    cleaned = _INVALID_PATH_CHARS_RE.sub("_", stem).strip()
    return cleaned or "untitled"


class SplitResult:
    def __init__(self, output_dir: Path, page_count: int) -> None:
        self.output_dir = output_dir
        self.page_count = page_count


class PdfService:
    def __init__(self, pdfseparate_cmd: str = "pdfseparate", runner=subprocess.run) -> None:
        self._pdfseparate_cmd = pdfseparate_cmd
        self._runner = runner

    def validate(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise ValidationError(f"File not found: {path}")
        if not os.access(path, os.R_OK):
            raise ValidationError(f"File is not readable: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValidationError(f"Not a PDF file: {path}")

    # ---- used by Page-by-Page printing ------------------------------------

    def split_to_temp(self, source: Path) -> "tuple[tempfile.TemporaryDirectory, List[Path]]":
        """Split `source` into a fresh temporary directory. Returns the
        TemporaryDirectory object (call `.cleanup()` when done — or use it as
        a context manager) and the numerically-sorted list of page paths."""
        self.validate(source)
        tempdir = tempfile.TemporaryDirectory(prefix="pdf_print_manager_")
        try:
            pages = self._run_pdfseparate(source, Path(tempdir.name))
        except PdfServiceError:
            tempdir.cleanup()
            raise
        if not pages:
            tempdir.cleanup()
            raise PdfServiceError("pdfseparate produced no pages.")
        return tempdir, pages

    # ---- used by Tools -> Split PDF into Pages... --------------------------

    def plan_split_destination(self, source: Path) -> Path:
        return source.parent / f"{sanitize_stem(source.stem)}_split"

    def destination_has_conflict(self, destination: Path) -> bool:
        return destination.exists() and any(destination.glob("Page_*.pdf"))

    def unique_destination(self, destination: Path) -> Path:
        n = 1
        candidate = destination.with_name(f"{destination.name} ({n})")
        while candidate.exists():
            n += 1
            candidate = destination.with_name(f"{destination.name} ({n})")
        return candidate

    def split_into_folder(self, source: Path, destination: Path, replace: bool = False) -> SplitResult:
        """Split `source` into one-page files inside `destination`, splitting
        into a temporary directory first and moving pages in only once the
        whole split has succeeded. The original PDF is never touched."""
        self.validate(source)
        destination.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="pdf_print_manager_split_") as tmp_name:
            pages = self._run_pdfseparate(source, Path(tmp_name))
            if not pages:
                raise PdfServiceError("pdfseparate produced no pages.")

            if replace:
                for existing in destination.glob("Page_*.pdf"):
                    existing.unlink()

            for page in pages:
                shutil.move(str(page), str(destination / page.name))

        return SplitResult(output_dir=destination, page_count=len(pages))

    # ---- shared -------------------------------------------------------------

    def _run_pdfseparate(self, source: Path, out_dir: Path) -> List[Path]:
        pattern = out_dir / "Page_%d.pdf"
        result = self._runner(
            [self._pdfseparate_cmd, str(source), str(pattern)],
            capture_output=True,
            text=True,
            check=False,
        )
        log_subprocess("pdfseparate", result)
        if result.returncode != 0:
            raise PdfServiceError(
                f"pdfseparate failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return sorted(out_dir.glob("Page_*.pdf"), key=page_sort_key)
