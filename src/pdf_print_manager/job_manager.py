"""Session lifecycle and legal state transitions.

`JobManager.run` is a blocking call meant to be invoked from a background
thread (see `worker.py`) — it drives one whole print session end to end,
reporting progress through a `SessionCallbacks` object rather than touching
any UI directly. `SessionControl` is the thread-safe handle the UI thread
uses to request pause/resume/cancel while `run` is in flight.

Keeping this module free of PySide6 imports means the entire state machine —
including pause/resume/cancel and the delay countdown — can be unit tested
with a fake CUPS client and no Qt event loop at all.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, List, Optional, Protocol

from .config import (
    CUPS_POLL_INTERVAL_SECONDS,
    DELAY_TICK_SECONDS,
    MAX_CONSECUTIVE_UNKNOWN_POLLS,
)
from .errors import ArchiveError, PdfServiceError, ValidationError
from .models import (
    CancelMode,
    CupsJobState,
    PrintMode,
    PrintRequest,
    SessionProgress,
    SessionResult,
    SessionState,
)


class SessionCallbacks(Protocol):
    def on_state(self, state: SessionState) -> None: ...
    def on_progress(self, progress: SessionProgress) -> None: ...
    def on_status(self, message: str) -> None: ...
    def on_log(self, line: str) -> None: ...
    def on_countdown(self, seconds_remaining: float) -> None: ...


class JobOutcome(Enum):
    SUCCESS = auto()
    TIMEOUT = auto()
    ABORTED = auto()
    CANCELLED = auto()
    UNKNOWN = auto()


class SessionControl:
    """Thread-safe pause/resume/cancel signalling shared between the UI
    thread and the background thread running `JobManager.run`."""

    def __init__(self) -> None:
        self._running_event = threading.Event()  # set == not paused
        self._running_event.set()
        self._cancel_event = threading.Event()
        self._cancel_mode: Optional[CancelMode] = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        self._running_event.set()
        self._cancel_event.clear()
        with self._lock:
            self._cancel_mode = None

    def request_pause(self) -> None:
        self._running_event.clear()

    def request_resume(self) -> None:
        self._running_event.set()

    def request_cancel(self, mode: CancelMode) -> None:
        with self._lock:
            self._cancel_mode = mode
        self._cancel_event.set()
        # Unblock anyone waiting out a pause so the cancel is noticed promptly.
        self._running_event.set()

    def is_paused(self) -> bool:
        return not self._running_event.is_set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def cancel_mode(self) -> Optional[CancelMode]:
        with self._lock:
            return self._cancel_mode

    def wait_if_paused(
        self,
        on_wait: Optional[Callable[[], None]] = None,
        on_resume: Optional[Callable[[], None]] = None,
        poll_interval: float = 0.15,
    ) -> None:
        """Block the calling (background) thread while paused. Returns
        immediately if not paused or if a cancel comes in while waiting."""
        if self._running_event.is_set():
            return
        if on_wait:
            on_wait()
        while not self._running_event.wait(poll_interval):
            if self.is_cancel_requested():
                break
        if on_resume and not self.is_cancel_requested():
            on_resume()


@dataclass
class _SplitItems:
    """Normalizes Document-Repeat and Page-by-Page into the same "list of
    source files to submit in order" shape, plus optional cleanup."""

    paths: List[Path]
    cleanup: Optional[Callable[[], None]] = None


class JobManager:
    POLL_INTERVAL_SECONDS = CUPS_POLL_INTERVAL_SECONDS
    DELAY_TICK_SECONDS = DELAY_TICK_SECONDS
    MAX_UNKNOWN_POLLS = MAX_CONSECUTIVE_UNKNOWN_POLLS

    def __init__(
        self,
        cups_client,
        pdf_service,
        archive_service,
        logger=None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cups = cups_client
        self._pdf_service = pdf_service
        self._archive = archive_service
        self._logger = logger
        self._clock = clock
        self._sleep = sleep

    # -- public API -----------------------------------------------------------

    def run(
        self,
        request: PrintRequest,
        control: SessionControl,
        callbacks: SessionCallbacks,
    ) -> SessionResult:
        items = None
        is_bulk = request.mode is PrintMode.BULK_PRINT
        archived_paths: List[Path] = []
        archive_warnings: List[str] = []
        try:
            callbacks.on_state(SessionState.VALIDATING)
            source_fingerprint = None
            if is_bulk:
                if not request.bulk_files:
                    raise ValidationError("No files selected for bulk printing.")
                for path in request.bulk_files:
                    self._pdf_service.validate(path)
            else:
                self._pdf_service.validate(request.source_path)
                source_fingerprint = self._archive.stat_fingerprint(request.source_path)

            if not request.printer_name:
                raise ValidationError("No printer selected.")

            callbacks.on_state(SessionState.PREPARING)
            items = self._prepare_items(request, callbacks)

            total = len(items.paths)
            progress = SessionProgress(total_items=total)
            callbacks.on_progress(progress)

            for index, item_path in enumerate(items.paths, start=1):
                control.wait_if_paused(
                    on_wait=lambda: callbacks.on_state(SessionState.PAUSED)
                )
                if control.is_cancel_requested():
                    return self._finish_cancelled(control, callbacks, archived_paths)

                label = self._item_label(request.mode, index, total, item_path)
                progress.current_item_label = label
                callbacks.on_state(SessionState.SUBMITTING)
                callbacks.on_status(f"Submitting {label}…")

                item_fingerprint = self._archive.stat_fingerprint(item_path) if is_bulk else None

                job_id = self._cups.submit_job(request.printer_name, item_path)
                progress.current_job_id = job_id
                callbacks.on_log(f"Submitted {label} -> job {job_id}")
                callbacks.on_state(SessionState.WAITING_FOR_CUPS)
                callbacks.on_status(f"Printing {label} — job in progress.")
                callbacks.on_progress(progress)

                outcome = self._wait_for_job(
                    job_id, request.item_timeout_seconds, control, callbacks
                )
                if outcome is JobOutcome.CANCELLED:
                    return self._finish_cancelled(control, callbacks, archived_paths)
                if outcome is not JobOutcome.SUCCESS:
                    message = self._failure_message(outcome, label, job_id)
                    if is_bulk and archived_paths:
                        message += (
                            f" ({len(archived_paths)} earlier file(s) in this batch "
                            "were already archived.)"
                        )
                    callbacks.on_state(SessionState.FAILED)
                    callbacks.on_status(message)
                    return SessionResult(
                        state=SessionState.FAILED, message=message, archived_paths=archived_paths
                    )

                progress.completed_items = index
                progress.current_job_id = None
                callbacks.on_progress(progress)

                if is_bulk and request.archive_completed_pdf:
                    callbacks.on_state(SessionState.ARCHIVING)
                    callbacks.on_status(f"Archiving {item_path.name}…")
                    try:
                        archived = self._archive.archive(item_path, item_fingerprint)
                        archived_paths.append(archived)
                        callbacks.on_log(f"Archived {item_path.name} to {archived}")
                    except ArchiveError as exc:
                        archive_warnings.append(f"{item_path.name}: {exc}")
                        callbacks.on_log(f"Archive warning for {item_path.name}: {exc}")

                is_last = index == total
                if not is_last:
                    cancelled = self._delay(request.delay_seconds, control, callbacks)
                    if cancelled:
                        return self._finish_cancelled(control, callbacks, archived_paths)

            if is_bulk:
                return self._finish_bulk_success(
                    request, archived_paths, archive_warnings, total, callbacks
                )
            return self._finish_success(request, total, source_fingerprint, callbacks)

        except ValidationError as exc:
            callbacks.on_state(SessionState.FAILED)
            callbacks.on_status(str(exc))
            return SessionResult(state=SessionState.FAILED, message=str(exc), error=str(exc))
        except PdfServiceError as exc:
            message = f"Couldn't prepare the PDF: {exc}"
            callbacks.on_state(SessionState.FAILED)
            callbacks.on_status(message)
            return SessionResult(state=SessionState.FAILED, message=message, error=str(exc))
        except Exception as exc:  # noqa: BLE001 - last-resort safety net
            if self._logger:
                self._logger.error(f"Unexpected error during print session: {exc!r}")
            message = f"Unexpected error: {exc}"
            callbacks.on_state(SessionState.FAILED)
            callbacks.on_status(message)
            return SessionResult(state=SessionState.FAILED, message=message, error=str(exc))
        finally:
            if items and items.cleanup:
                items.cleanup()

    # -- internals --------------------------------------------------------------

    def _prepare_items(self, request: PrintRequest, callbacks: SessionCallbacks) -> _SplitItems:
        if request.mode is PrintMode.DOCUMENT_REPEAT:
            return _SplitItems(paths=[request.source_path] * request.copies)

        if request.mode is PrintMode.BULK_PRINT:
            return _SplitItems(paths=list(request.bulk_files))

        tempdir, pages = self._pdf_service.split_to_temp(request.source_path)
        callbacks.on_log(f"Split into {len(pages)} page(s) for page-by-page printing")
        return _SplitItems(paths=pages, cleanup=tempdir.cleanup)

    @staticmethod
    def _item_label(mode: PrintMode, index: int, total: int, item_path: Optional[Path] = None) -> str:
        if mode is PrintMode.DOCUMENT_REPEAT:
            return f"Copy {index} of {total}"
        if mode is PrintMode.BULK_PRINT:
            name = item_path.name if item_path else ""
            return f"File {index} of {total} — {name}"
        return f"Page {index} of {total}"

    def _wait_for_job(
        self,
        job_id: str,
        timeout_seconds: float,
        control: SessionControl,
        callbacks: SessionCallbacks,
    ) -> JobOutcome:
        start = self._clock()
        consecutive_unknown = 0

        while True:
            if control.is_cancel_requested():
                if control.cancel_mode() is CancelMode.CANCEL_CURRENT_JOB:
                    self._cups.cancel_job(job_id)
                    callbacks.on_log(f"Cancelled job {job_id} at the user's request")
                return JobOutcome.CANCELLED

            control.wait_if_paused(
                on_wait=lambda: callbacks.on_state(SessionState.PAUSED),
                on_resume=lambda: callbacks.on_state(SessionState.WAITING_FOR_CUPS),
            )
            if control.is_cancel_requested():
                continue  # re-check at the top so CANCEL_CURRENT_JOB still runs

            state = self._cups.get_job_state(job_id)
            if state is CupsJobState.COMPLETED:
                callbacks.on_log(f"job {job_id} completed")
                return JobOutcome.SUCCESS
            if state is CupsJobState.CANCELLED:
                callbacks.on_log(f"job {job_id} was cancelled")
                return JobOutcome.CANCELLED
            if state is CupsJobState.ABORTED:
                callbacks.on_log(f"job {job_id} aborted")
                return JobOutcome.ABORTED
            if state is CupsJobState.UNKNOWN:
                consecutive_unknown += 1
                if consecutive_unknown >= self.MAX_UNKNOWN_POLLS:
                    callbacks.on_log(
                        f"job {job_id} state could not be confirmed after "
                        f"{consecutive_unknown} checks"
                    )
                    return JobOutcome.UNKNOWN
            else:
                consecutive_unknown = 0

            if self._clock() - start > timeout_seconds:
                callbacks.on_log(f"job {job_id} timed out after {timeout_seconds:.0f}s")
                return JobOutcome.TIMEOUT

            self._sleep(self.POLL_INTERVAL_SECONDS)

    def _delay(
        self, seconds: float, control: SessionControl, callbacks: SessionCallbacks
    ) -> bool:
        """Waits out the inter-job delay, reporting a countdown. Returns True
        if the wait ended because of a cancel request."""
        if seconds <= 0:
            return control.is_cancel_requested()

        remaining = float(seconds)
        callbacks.on_state(SessionState.WAITING_DELAY)
        callbacks.on_status(f"Waiting {remaining:.0f}s before the next item…")

        while remaining > 0:
            if control.is_cancel_requested():
                return True

            control.wait_if_paused(
                on_wait=lambda: callbacks.on_state(SessionState.PAUSED),
                on_resume=lambda: callbacks.on_state(SessionState.WAITING_DELAY),
            )
            if control.is_cancel_requested():
                return True

            callbacks.on_countdown(remaining)
            tick = min(self.DELAY_TICK_SECONDS, remaining)
            self._sleep(tick)
            remaining -= tick

        callbacks.on_countdown(0)
        return False

    def _finish_cancelled(
        self,
        control: SessionControl,
        callbacks: SessionCallbacks,
        archived_paths: Optional[List[Path]] = None,
    ) -> SessionResult:
        archived_paths = archived_paths or []
        if archived_paths:
            message = (
                f"Cancelled by user before completion. {len(archived_paths)} file(s) "
                "already printed were archived; the rest were not."
            )
        else:
            message = "Cancelled by user before completion. No files archived."
        callbacks.on_state(SessionState.CANCELLED)
        callbacks.on_status(message)
        return SessionResult(
            state=SessionState.CANCELLED, message=message, archived_paths=list(archived_paths)
        )

    def _finish_success(
        self,
        request: PrintRequest,
        total: int,
        source_fingerprint,
        callbacks: SessionCallbacks,
    ) -> SessionResult:
        if not request.archive_completed_pdf:
            message = f"Completed — {total} of {total} printed."
            callbacks.on_state(SessionState.COMPLETED)
            callbacks.on_status(message)
            return SessionResult(state=SessionState.COMPLETED, message=message)

        callbacks.on_state(SessionState.ARCHIVING)
        callbacks.on_status("Archiving source PDF…")
        try:
            archived = self._archive.archive(request.source_path, source_fingerprint)
        except ArchiveError as exc:
            message = (
                f"Completed with archive warning — all {total} printed, but "
                f"the file couldn't be moved: {exc}"
            )
            callbacks.on_log(str(exc))
            callbacks.on_state(SessionState.COMPLETED_WITH_WARNING)
            callbacks.on_status(message)
            return SessionResult(
                state=SessionState.COMPLETED_WITH_WARNING, message=message, error=str(exc)
            )

        callbacks.on_log(f"Archived source to {archived}")
        message = f"Completed — {total} of {total} printed. Archived to {archived.parent.name}/."
        callbacks.on_state(SessionState.COMPLETED)
        callbacks.on_status(message)
        return SessionResult(state=SessionState.COMPLETED, message=message, archived_path=archived)

    def _finish_bulk_success(
        self,
        request: PrintRequest,
        archived_paths: List[Path],
        archive_warnings: List[str],
        total: int,
        callbacks: SessionCallbacks,
    ) -> SessionResult:
        if archive_warnings:
            message = (
                f"Completed with archive warning — all {total} files printed, but "
                f"{len(archive_warnings)} couldn't be archived: {'; '.join(archive_warnings)}"
            )
            callbacks.on_state(SessionState.COMPLETED_WITH_WARNING)
            callbacks.on_status(message)
            return SessionResult(
                state=SessionState.COMPLETED_WITH_WARNING,
                message=message,
                archived_paths=archived_paths,
                error="; ".join(archive_warnings),
            )

        if request.archive_completed_pdf:
            message = f"Completed — {total} of {total} files printed and archived."
        else:
            message = f"Completed — {total} of {total} files printed."
        callbacks.on_state(SessionState.COMPLETED)
        callbacks.on_status(message)
        return SessionResult(
            state=SessionState.COMPLETED, message=message, archived_paths=archived_paths
        )

    @staticmethod
    def _failure_message(outcome: JobOutcome, label: str, job_id: str) -> str:
        if outcome is JobOutcome.TIMEOUT:
            return f"Failed — {label} (job {job_id}) timed out. Source file kept; nothing archived."
        if outcome is JobOutcome.ABORTED:
            return f"Failed — {label} (job {job_id}) was aborted by CUPS. Source file kept."
        if outcome is JobOutcome.UNKNOWN:
            return f"Failed — couldn't confirm {label} (job {job_id}) finished. Source file kept."
        return f"Failed — {label} (job {job_id}) did not complete. Source file kept."
