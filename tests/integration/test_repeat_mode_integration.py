"""End-to-end Document Repeat sessions via JobManager + FakeCupsClient — no
real CUPS or poppler needed, so this always runs."""

from pdf_print_manager.job_manager import JobManager, SessionControl
from pdf_print_manager.models import PrintMode, PrintRequest, SessionState
from pdf_print_manager.services.archive_service import ArchiveService
from pdf_print_manager.services.pdf_service import PdfService


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


def test_repeat_mode_end_to_end_archives_after_all_copies(fake_cups, sample_pdf):
    manager = JobManager(fake_cups, PdfService(), ArchiveService())
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=4,
        delay_seconds=0,
    )

    result = manager.run(request, SessionControl(), _NullCallbacks())

    assert result.state is SessionState.COMPLETED
    assert len(fake_cups.submitted) == 4
    assert result.archived_path.parent.name == "PrintedCompleted"
    assert result.archived_path.exists()


def test_failed_session_does_not_archive(fake_cups, sample_pdf):
    class AlwaysAbortedCups:
        def __init__(self):
            self.submitted = []

        def submit_job(self, printer_name, path):
            self.submitted.append((printer_name, str(path)))
            return "printer-1"

        def get_job_state(self, job_id):
            from pdf_print_manager.models import CupsJobState

            return CupsJobState.ABORTED

        def cancel_job(self, job_id):
            return True

    cups = AlwaysAbortedCups()
    manager = JobManager(cups, PdfService(), ArchiveService())
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name="Test Printer",
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=2,
        delay_seconds=0,
    )

    result = manager.run(request, SessionControl(), _NullCallbacks())

    assert result.state is SessionState.FAILED
    assert sample_pdf.exists()
    assert len(cups.submitted) == 1  # never attempted copy 2 after copy 1 failed
