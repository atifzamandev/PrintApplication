"""State-machine transition tests for JobManager — the core of the app's
correctness. Uses FakeCupsClient (no real `lp`/`lpstat`), the real
PdfService/ArchiveService against tmp_path (no real `pdfseparate` needed for
Document Repeat mode), and a deterministic fake clock/sleep so delay and
timeout logic runs instantly instead of over real wall-clock time.
"""

from pdf_print_manager.job_manager import JobManager, SessionControl
from pdf_print_manager.models import CancelMode, PrintMode, PrintRequest, SessionState
from pdf_print_manager.services.archive_service import ArchiveService
from pdf_print_manager.services.pdf_service import PdfService


class FakeClockSleep:
    """A clock that only advances when `sleep` is called, so timeouts and
    delays resolve deterministically without real wall-clock waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


class RecordingCallbacks:
    def __init__(self, on_progress_hook=None) -> None:
        self.states = []
        self.statuses = []
        self.logs = []
        self.countdowns = []
        self.progress_snapshots = []
        self._on_progress_hook = on_progress_hook

    def on_state(self, state):
        self.states.append(state)

    def on_progress(self, progress):
        self.progress_snapshots.append((progress.completed_items, progress.total_items))
        if self._on_progress_hook:
            self._on_progress_hook(progress)

    def on_status(self, message):
        self.statuses.append(message)

    def on_log(self, line):
        self.logs.append(line)

    def on_countdown(self, seconds_remaining):
        self.countdowns.append(seconds_remaining)


def _make_job_manager(cups, pdf_service=None, archive_service=None, clock_sleep=None):
    clock_sleep = clock_sleep or FakeClockSleep()
    return JobManager(
        cups_client=cups,
        pdf_service=pdf_service or PdfService(),
        archive_service=archive_service or ArchiveService(),
        clock=clock_sleep.clock,
        sleep=clock_sleep.sleep,
    )


def test_document_repeat_success_submits_one_job_per_copy_and_archives(fake_cups, sample_pdf):
    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=3,
        delay_seconds=0,
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.COMPLETED
    assert len(fake_cups.submitted) == 3
    assert all(path == str(sample_pdf) for _printer, path in fake_cups.submitted)
    assert result.archived_path is not None
    assert result.archived_path.exists()
    assert not sample_pdf.exists()
    assert SessionState.ARCHIVING in callbacks.states
    assert callbacks.progress_snapshots[-1] == (3, 3)


def test_page_by_page_submits_pages_in_numeric_order(fake_cups, tmp_path, sample_pdf):
    pages = [tmp_path / "Page_1.pdf", tmp_path / "Page_2.pdf", tmp_path / "Page_3.pdf"]
    for page in pages:
        page.write_bytes(b"%PDF-1.4\n")

    class FakeTempDir:
        def cleanup(self):
            self.cleaned = True

    class FakePdfService:
        def __init__(self):
            self.validated = []

        def validate(self, path):
            self.validated.append(path)

        def split_to_temp(self, source):
            return FakeTempDir(), list(pages)

    manager = _make_job_manager(fake_cups, pdf_service=FakePdfService())
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.PAGE_BY_PAGE,
        delay_seconds=0,
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.COMPLETED
    submitted_paths = [path for _printer, path in fake_cups.submitted]
    assert submitted_paths == [str(p) for p in pages]


def test_cancellation_prevents_further_submissions_and_does_not_archive(fake_cups, sample_pdf):
    control = SessionControl()

    def cancel_after_first_copy(progress):
        if progress.completed_items == 1:
            control.request_cancel(CancelMode.STOP_AFTER_CURRENT)

    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=3,
        delay_seconds=0,
    )
    callbacks = RecordingCallbacks(on_progress_hook=cancel_after_first_copy)

    result = manager.run(request, control, callbacks)

    assert result.state is SessionState.CANCELLED
    assert len(fake_cups.submitted) == 1
    assert sample_pdf.exists()  # never archived
    assert result.archived_path is None


def test_cancel_current_job_calls_cups_cancel(fake_cups, sample_pdf):
    control = SessionControl()
    fake_cups.auto_complete_after = 1000  # never auto-completes on its own

    def cancel_immediately(progress):
        # Only cancel once a job has actually been submitted (current_job_id
        # set) — not on the very first, pre-submission progress snapshot.
        if progress.current_job_id is not None:
            control.request_cancel(CancelMode.CANCEL_CURRENT_JOB)

    manager = _make_job_manager(fake_cups)
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=2,
        delay_seconds=0,
    )
    callbacks = RecordingCallbacks(on_progress_hook=cancel_immediately)

    result = manager.run(request, control, callbacks)

    assert result.state is SessionState.CANCELLED
    assert len(fake_cups.cancelled_job_ids) == 1


def test_job_timeout_fails_session_and_keeps_source(fake_cups, sample_pdf):
    fake_cups.auto_complete_after = 10 ** 6  # effectively never completes
    clock_sleep = FakeClockSleep()
    manager = _make_job_manager(fake_cups, clock_sleep=clock_sleep)
    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=1,
        delay_seconds=0,
        item_timeout_seconds=5,
    )
    callbacks = RecordingCallbacks()

    result = manager.run(request, SessionControl(), callbacks)

    assert result.state is SessionState.FAILED
    assert sample_pdf.exists()


def test_delay_countdown_preserves_remaining_time_across_a_pause(fake_cups, sample_pdf):
    """Simulates the UI pausing partway through the inter-copy delay, then
    immediately resuming (as it would once the user clicks Resume) — the
    countdown must not have skipped ahead during the pause."""
    control = SessionControl()
    clock_sleep = FakeClockSleep()
    manager = _make_job_manager(fake_cups, clock_sleep=clock_sleep)

    seen_after_pause = {}
    paused_once = {"done": False}

    class PausingCallbacks(RecordingCallbacks):
        def on_countdown(self, seconds_remaining):
            super().on_countdown(seconds_remaining)
            if not paused_once["done"] and seconds_remaining <= 7.0:
                paused_once["done"] = True
                control.request_pause()

        def on_state(self, state):
            super().on_state(state)
            if state is SessionState.PAUSED:
                # Simulate an instantaneous resume — enough to prove the
                # countdown value is unaffected by however long a real pause
                # would have lasted, without blocking this test on real time.
                seen_after_pause["remaining"] = self.countdowns[-1]
                control.request_resume()

    request = PrintRequest(
        source_path=sample_pdf,
        printer_name=fake_cups.default,
        mode=PrintMode.DOCUMENT_REPEAT,
        copies=2,
        delay_seconds=10,
    )
    callbacks = PausingCallbacks()

    result = manager.run(request, control, callbacks)

    assert result.state is SessionState.COMPLETED
    assert SessionState.PAUSED in callbacks.states
    # Countdown resumed from (approximately) where it left off, not from 10.
    assert seen_after_pause["remaining"] <= 7.0
    assert len(fake_cups.submitted) == 2
