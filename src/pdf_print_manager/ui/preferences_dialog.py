"""Settings -> Preferences… — default delay, archive-on-completion, the
per-item timeout, and a shortcut to the log folder."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..config import (
    MAX_DELAY_SECONDS,
    MAX_ITEM_TIMEOUT_MINUTES,
    MIN_DELAY_SECONDS,
    MIN_ITEM_TIMEOUT_MINUTES,
)
from ..services.logging_service import default_log_dir


class PreferencesDialog(QDialog):
    def __init__(self, settings_service, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(360)
        self._build_ui()
        self._load_current_values()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        self.delay_spin.setSuffix(" s")
        form.addRow("Default delay", self.delay_spin)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(MIN_ITEM_TIMEOUT_MINUTES, MAX_ITEM_TIMEOUT_MINUTES)
        self.timeout_spin.setSuffix(" min")
        form.addRow("Print item timeout", self.timeout_spin)

        root.addLayout(form)

        self.archive_checkbox = QCheckBox("Move successfully printed PDFs to PrintedCompleted")
        root.addWidget(self.archive_checkbox)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Log folder"))
        self.log_dir_edit = QLineEdit()
        self.log_dir_edit.setReadOnly(True)
        log_row.addWidget(self.log_dir_edit, 1)
        open_log_button = QPushButton("Open")
        open_log_button.clicked.connect(self._open_log_folder)
        log_row.addWidget(open_log_button)
        root.addLayout(log_row)

        note = QLabel("Saved with QSettings — takes effect on the next session.")
        note.setStyleSheet("color: #5b6572; font-size: 11px;")
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_current_values(self) -> None:
        self.delay_spin.setValue(self._settings.delay_seconds())
        self.timeout_spin.setValue(self._settings.item_timeout_seconds() // 60)
        self.archive_checkbox.setChecked(self._settings.archive_completed_pdf())
        self.log_dir_edit.setText(str(default_log_dir()))

    def _on_save(self) -> None:
        self._settings.set_delay_seconds(self.delay_spin.value())
        self._settings.set_item_timeout_seconds(self.timeout_spin.value() * 60)
        self._settings.set_archive_completed_pdf(self.archive_checkbox.isChecked())
        self.accept()

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.log_dir_edit.text()))
