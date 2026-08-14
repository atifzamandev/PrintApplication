"""Bulk Print mode: each selected file is printed once, in list order, and
archived individually right after its own job succeeds — independent of the
others, unlike Document Repeat/Page-by-Page which archive one source file
at the very end."""

from pdf_print_manager.job_manager import JobManager, SessionControl
from pdf_print_manager.models import CancelMode, PrintMode, PrintRequest, SessionState
from pdf_print_manager.services.archive_service import ArchiveService
from pdf_print_manager.services.pdf_service import PdfService

from .test_job_manager import RecordingCallbacks, _make_job_manager


def _bulk_pdfs(tmp_path, names):
    paths = []
    for name in names:
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.4\n%fake\n")
        paths.append(path)
    return paths


def test_bulk_print_archives_each_file_independently(fake_cups, tmp_path):
    files = _bulk_pdfs(tmp_path, ["Invoice_1.pdf", "Invoice_2.pdf", "Invoice_3.pdf"])
    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=files[0],
        printer_name=fake_cups.default,
        mode=PrintMode.BULK_PRINT,
        delay_seconds=0,
        bulk_files=tuple(files),
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.COMPLETED
    assert len(fake_cups.submitted) == 3
    submitted_paths = [path for _printer, path in fake_cups.submitted]
    assert submitted_paths == [str(f) for f in files]

    assert len(result.archived_paths) == 3
    for original, archived in zip(files, result.archived_paths):
        assert not original.exists()
        assert archived.exists()
        assert archived.parent.name == "PrintedCompleted"
        assert archived.name == original.name


def test_bulk_print_labels_include_filename(fake_cups, tmp_path):
    files = _bulk_pdfs(tmp_path, ["A.pdf", "B.pdf"])
    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=files[0],
        printer_name=fake_cups.default,
        mode=PrintMode.BULK_PRINT,
        delay_seconds=0,
        bulk_files=tuple(files),
    )
    callbacks = RecordingCallbacks()

    manager.run(request, SessionControl(), callbacks)

    assert any("File 1 of 2 — A.pdf" in status for status in callbacks.statuses)
    assert any("File 2 of 2 — B.pdf" in status for status in callbacks.statuses)


def test_bulk_print_stops_on_failure_and_keeps_already_archived_files(fake_cups, tmp_path):
    files = _bulk_pdfs(tmp_path, ["Invoice_1.pdf", "Invoice_2.pdf", "Invoice_3.pdf"])

    from pdf_print_manager.models import CupsJobState

    class FailSecondCups:
        def __init__(self):
            self.submitted = []
            self._counter = 0

        def submit_job(self, printer_name, path):
            self._counter += 1
            self.submitted.append((printer_name, str(path)))
            return f"job-{self._counter}"

        def get_job_state(self, job_id):
            if job_id == "job-2":
                return CupsJobState.ABORTED
            return CupsJobState.COMPLETED

        def cancel_job(self, job_id):
            return True

    cups = FailSecondCups()
    manager = JobManager(cups, PdfService(), ArchiveService())
    request = PrintRequest(
        source_path=files[0],
        printer_name="Test Printer",
        mode=PrintMode.BULK_PRINT,
        delay_seconds=0,
        bulk_files=tuple(files),
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.FAILED
    assert len(cups.submitted) == 2  # third file never attempted
    assert len(result.archived_paths) == 1  # only the first file made it through
    assert not files[0].exists()  # archived
    assert files[1].exists()  # failed job — kept in place
    assert files[2].exists()  # never attempted — untouched


def test_bulk_print_cancellation_keeps_already_archived_files(fake_cups, tmp_path):
    files = _bulk_pdfs(tmp_path, ["Invoice_1.pdf", "Invoice_2.pdf", "Invoice_3.pdf"])
    control = SessionControl()

    def cancel_after_first_file(progress):
        if progress.completed_items == 1:
            control.request_cancel(CancelMode.STOP_AFTER_CURRENT)

    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=files[0],
        printer_name=fake_cups.default,
        mode=PrintMode.BULK_PRINT,
        delay_seconds=0,
        bulk_files=tuple(files),
    )
    callbacks = RecordingCallbacks(on_progress_hook=cancel_after_first_file)

    result = manager.run(request, control, callbacks)

    assert result.state is SessionState.CANCELLED
    assert len(fake_cups.submitted) == 1
    assert len(result.archived_paths) == 1
    assert not files[0].exists()
    assert files[1].exists()
    assert files[2].exists()


def test_bulk_print_without_archiving_leaves_files_in_place(fake_cups, tmp_path):
    files = _bulk_pdfs(tmp_path, ["A.pdf", "B.pdf"])
    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=files[0],
        printer_name=fake_cups.default,
        mode=PrintMode.BULK_PRINT,
        delay_seconds=0,
        archive_completed_pdf=False,
        bulk_files=tuple(files),
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.COMPLETED
    assert result.archived_paths == []
    assert all(f.exists() for f in files)
    assert "archived" not in result.message.lower()


def test_bulk_print_requires_at_least_one_file(fake_cups, tmp_path):
    placeholder = tmp_path / "placeholder.pdf"
    placeholder.write_bytes(b"%PDF-1.4\n")
    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=placeholder,
        printer_name=fake_cups.default,
        mode=PrintMode.BULK_PRINT,
        bulk_files=(),
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.FAILED
    assert len(fake_cups.submitted) == 0
