"""Runs `JobManager.run` on a background `QThread`, translating its plain
callbacks into Qt signals. This is the only place printing logic touches Qt —
`JobManager` itself stays framework-free and unit-testable.

Pause/resume/cancel are deliberately *not* Qt slots invoked through a queued
connection. `start_session` blocks the worker thread's event loop for the
entire session, so a queued call to a `pause`/`resume`/`cancel` slot on that
same thread would simply sit undelivered until the session finished —
exactly when it's no longer useful. Instead, `control` (a `SessionControl`)
is plain, thread-safe Python built on `threading.Event`/`threading.Lock`, so
the UI thread calls `worker.control.request_pause()` etc. directly — safe
because `SessionControl` was designed from the start to be read and written
from two threads at once, with no Qt event-loop involved.

The Qt main thread must only handle UI: nothing here ever touches a widget
directly, and everything that *does* need to reach the UI thread (state,
progress, status, log, countdown, the final result) goes through a signal.
`QThread.terminate()` is never used.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from .job_manager import JobManager, SessionControl
from .models import PrintRequest, SessionProgress, SessionResult, SessionState


class _SignalCallbacks:
    """Adapts JobManager's plain callback protocol to PrintWorker's signals,
    and also feeds the persistent session log."""

    def __init__(self, worker: "PrintWorker", session_logger=None) -> None:
        self._worker = worker
        self._session_logger = session_logger

    def on_state(self, state: SessionState) -> None:
        self._worker.state_changed.emit(state)

    def on_progress(self, progress: SessionProgress) -> None:
        self._worker.progress_changed.emit(progress)

    def on_status(self, message: str) -> None:
        self._worker.status_changed.emit(message)

    def on_log(self, line: str) -> None:
        if self._session_logger:
            self._session_logger.info(line)
        self._worker.log_emitted.emit(line)

    def on_countdown(self, seconds_remaining: float) -> None:
        self._worker.countdown_changed.emit(seconds_remaining)


class PrintWorker(QObject):
    state_changed = Signal(object)      # SessionState
    progress_changed = Signal(object)   # SessionProgress
    status_changed = Signal(str)
    log_emitted = Signal(str)
    countdown_changed = Signal(float)
    finished = Signal(object)           # SessionResult

    def __init__(self, job_manager: JobManager, session_logger=None, parent=None) -> None:
        super().__init__(parent)
        self._job_manager = job_manager
        self._session_logger = session_logger
        # Public and thread-safe by design — the UI thread calls
        # `request_pause()` / `request_resume()` / `request_cancel()` on this
        # directly. See the module docstring for why that's not a Qt slot.
        self.control = SessionControl()

    @Slot(object)
    def start_session(self, request: PrintRequest) -> None:
        self.control.reset()
        callbacks = _SignalCallbacks(self, self._session_logger)
        result: SessionResult = self._job_manager.run(request, self.control, callbacks)
        self.finished.emit(result)
