"""Shared pytest fixtures, including a fully in-memory fake CUPS client so
integration tests never touch a real `lp`/`lpstat`/`cancel`."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from pdf_print_manager.models import CupsJobState, PrinterInfo


class FakeCupsClient:
    """Scripted, in-memory stand-in for CupsClient.

    Each submitted job completes automatically after `auto_complete_after`
    polls of `get_job_state`, unless the test manually sets a different
    outcome via `set_job_state`. `submitted` records (printer, path) pairs in
    submission order so tests can assert exact sequencing.
    """

    def __init__(
        self,
        printers: Optional[List[PrinterInfo]] = None,
        default: Optional[str] = None,
        auto_complete_after: int = 1,
    ) -> None:
        self.printers = printers or [PrinterInfo(name="Test Printer", is_default=True)]
        self.default = default or (self.printers[0].name if self.printers else None)
        self.auto_complete_after = auto_complete_after
        self._job_counter = itertools.count(1)
        self._jobs: Dict[str, Dict[str, object]] = {}
        self.submitted: List[Tuple[str, str]] = []
        self.cancelled_job_ids: List[str] = []

    def list_printers(self) -> List[PrinterInfo]:
        return list(self.printers)

    def default_printer(self) -> Optional[str]:
        return self.default

    def submit_job(self, printer_name: str, path: Path) -> str:
        job_id = f"{printer_name.replace(' ', '-')}-{next(self._job_counter)}"
        self._jobs[job_id] = {"polls": 0, "state": CupsJobState.PROCESSING}
        self.submitted.append((printer_name, str(path)))
        return job_id

    def get_job_state(self, job_id: str) -> CupsJobState:
        job = self._jobs.get(job_id)
        if job is None:
            return CupsJobState.UNKNOWN
        if job["state"] != CupsJobState.PROCESSING:
            return job["state"]  # type: ignore[return-value]
        job["polls"] = int(job["polls"]) + 1
        if job["polls"] >= self.auto_complete_after:
            job["state"] = CupsJobState.COMPLETED
            return CupsJobState.COMPLETED
        return CupsJobState.PROCESSING

    def set_job_state(self, job_id: str, state: CupsJobState) -> None:
        if job_id in self._jobs:
            self._jobs[job_id]["state"] = state

    def cancel_job(self, job_id: str) -> bool:
        self.cancelled_job_ids.append(job_id)
        if job_id in self._jobs:
            self._jobs[job_id]["state"] = CupsJobState.CANCELLED
        return True


@pytest.fixture
def fake_cups() -> FakeCupsClient:
    return FakeCupsClient()


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    """A byte sequence that is *not* a valid PDF, but is good enough for tests
    that only need a readable `.pdf`-suffixed file (validation, archiving) —
    nothing here shells out to a real PDF parser."""
    path = tmp_path / "Invoice_2381.pdf"
    path.write_bytes(b"%PDF-1.4\n%fake pdf for tests\n")
    return path
