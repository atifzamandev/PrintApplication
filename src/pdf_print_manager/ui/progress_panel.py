"""The status line, progress bar, job-id chip, and delay countdown.

Status never relies on colour alone — every tone pairs with an icon and
explicit wording, per the spec's accessibility requirements.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..models import SessionProgress, SessionState
from .icons import icon

_TONE_FOR_STATE = {
    SessionState.IDLE: ("neutral", "dialog-information"),
    SessionState.VALIDATING: ("info", "dialog-information"),
    SessionState.PREPARING: ("info", "dialog-information"),
    SessionState.SUBMITTING: ("info", "document-print"),
    SessionState.WAITING_FOR_CUPS: ("info", "document-print"),
    SessionState.WAITING_DELAY: ("info", "document-print"),
    SessionState.PAUSED: ("warn", "media-playback-pause"),
    SessionState.CANCELLING: ("warn", "process-stop"),
    SessionState.ARCHIVING: ("info", "folder-open"),
    SessionState.COMPLETED: ("ok", "dialog-ok"),
    SessionState.COMPLETED_WITH_WARNING: ("warn", "dialog-warning"),
    SessionState.CANCELLED: ("neutral", "process-stop"),
    SessionState.FAILED: ("danger", "dialog-error"),
}

_TONE_COLORS = {
    "neutral": "#3a4550",
    "info": "#2f5fa6",
    "ok": "#2e7d32",
    "warn": "#8a5c10",
    "danger": "#a6362f",
}


class ProgressPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        status_row = QHBoxLayout()
        self.status_icon_label = QLabel()
        self.status_text_label = QLabel("Ready to print.")
        self.status_text_label.setWordWrap(True)
        status_row.addWidget(self.status_icon_label)
        status_row.addWidget(self.status_text_label, 1)
        root.addLayout(status_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        root.addWidget(self.progress_bar)

        meta_row = QHBoxLayout()
        self.progress_label = QLabel("No session yet")
        self.job_label = QLabel()
        self.job_label.setVisible(False)
        self.countdown_label = QLabel()
        self.countdown_label.setVisible(False)
        meta_row.addWidget(self.progress_label)
        meta_row.addStretch(1)
        meta_row.addWidget(self.job_label)
        meta_row.addWidget(self.countdown_label)
        root.addLayout(meta_row)

    def set_state(self, state: SessionState) -> None:
        tone, icon_name = _TONE_FOR_STATE.get(state, ("neutral", "dialog-information"))
        color = _TONE_COLORS[tone]
        self.status_icon_label.setPixmap(icon(icon_name).pixmap(16, 16))
        self.status_text_label.setStyleSheet(f"color: {color}; font-weight: 600;")

    def set_status_message(self, message: str) -> None:
        self.status_text_label.setText(message)

    def set_progress(self, progress: Optional[SessionProgress], mode_word: str) -> None:
        if progress is None or progress.total_items <= 0:
            self.progress_bar.setValue(0)
            self.progress_label.setText("No session yet")
            self.job_label.setVisible(False)
            return

        percent = int(round(progress.fraction * 100))
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            f"{mode_word} {progress.completed_items} of {progress.total_items}"
        )
        if progress.current_job_id:
            self.job_label.setText(f"Job {progress.current_job_id}")
            self.job_label.setVisible(True)
        else:
            self.job_label.setVisible(False)

    def set_progress_tone(self, tone: str) -> None:
        colors = {"ok": "#2e7d32", "warn": "#8a5c10", "danger": "#a6362f", "info": "#1e6e62"}
        color = colors.get(tone, "#1e6e62")
        self.progress_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )

    def set_countdown(self, seconds_remaining: Optional[float]) -> None:
        if not seconds_remaining or seconds_remaining <= 0:
            self.countdown_label.setVisible(False)
            return
        minutes, secs = divmod(int(round(seconds_remaining)), 60)
        self.countdown_label.setText(f"{minutes:02d}:{secs:02d} until next submission")
        self.countdown_label.setVisible(True)
