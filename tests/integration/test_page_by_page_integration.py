"""Full Page-by-Page session: real `pdfseparate` splits a real multi-page
PDF into a temp directory, JobManager submits each page in numeric order to
a FakeCupsClient, and the original source gets archived once every page
succeeds. Requires poppler-utils; skipped otherwise.
"""

import shutil

import pytest

from pdf_print_manager.job_manager import JobManager, SessionControl
from pdf_print_manager.models import PrintMode, PrintRequest, SessionState
from pdf_print_manager.services.archive_service import ArchiveService
from pdf_print_manager.services.pdf_service import PdfService
from tests.pdf_fixtures import build_minimal_pdf

pytestmark = pytest.mark.skipif(
    shutil.which("pdfseparate") is None,
    reason="requires poppler-utils (pdfseparate) on PATH",
)


class _NullCallbacks:
    def on_state(self, state):
        pass

    def on_progress(self, progress):
        pass

    def on_status(self, message):
        pass

    def on_log(self, line):
        pass

    def on_countdown(self, seconds_remaining):
        pass


def test_page_by_page_submits_sequentially_and_archives(fake_cups, tmp_path):
    source = tmp_path / "Invoice_2381.pdf"
    source.write_bytes(build_minimal_pdf(6))

    manager = JobManager(fake_cups, PdfService(), ArchiveService())
    request = PrintRequest(
        source_path=source,
        printer_name=fake_cups.default,
        mode=PrintMode.PAGE_BY_PAGE,
        delay_seconds=0,
    )

    result = manager.run(request, SessionControl(), _NullCallbacks())

    assert result.state is SessionState.COMPLETED
    assert len(fake_cups.submitted) == 6

    submitted_names = [path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for _printer, path in fake_cups.submitted]
    assert submitted_names == [f"Page_{i}.pdf" for i in range(1, 7)]

    assert result.archived_path is not None
    assert result.archived_path.exists()
    assert not source.exists()
