"""The single-window PySide6 UI described in spec section 8.

MainWindow owns the services, the background QThread + PrintWorker, and
wires everything together. It never runs printing logic itself and never
touches worker internals except through signals — see `worker.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION
from ..job_manager import JobManager
from ..models import CancelMode, PrintMode, PrintRequest, SessionProgress, SessionResult, SessionState
from ..services.archive_service import ArchiveService
from ..services.cups_client import CupsClient
from ..services.logging_service import SessionLogger, default_log_dir
from ..services.pdf_service import PdfService
from ..services.settings_service import SettingsService
from ..worker import PrintWorker
from .control_state import control_state_for, legend_for_state
from .icons import app_icon, icon
from .log_panel import LogPanel
from .preferences_dialog import PreferencesDialog
from .print_settings_panel import PrintSettingsPanel
from .progress_panel import ProgressPanel
from .split_dialog import SplitDialog

_FINISHED_PROGRESS_TONE = {
    SessionState.COMPLETED: "ok",
    SessionState.COMPLETED_WITH_WARNING: "warn",
    SessionState.FAILED: "danger",
    SessionState.CANCELLED: "warn",
}

_ACTIVE_LEGENDS = {"running", "paused", "cancelling"}

_MODE_WORD = {
    PrintMode.DOCUMENT_REPEAT: "Copy",
    PrintMode.PAGE_BY_PAGE: "Page",
    PrintMode.BULK_PRINT: "File",
}


class MainWindow(QMainWindow):
    # Starting a session must run on the worker thread, so it goes through a
    # real queued signal -> slot. Pause/resume/cancel do not — see worker.py.
    start_requested = Signal(object)   # PrintRequest

    def __init__(
        self,
        settings: SettingsService,
        cups: CupsClient,
        pdf_service: PdfService,
        archive_service: ArchiveService,
        job_manager: JobManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._cups = cups
        self._pdf_service = pdf_service
        self._archive_service = archive_service
        self._job_manager = job_manager
        self._session_logger = SessionLogger()

        self._current_state = SessionState.IDLE
        self._last_result: Optional[SessionResult] = None
        self._bulk_last_completed = 0

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(560, 640)

        self._build_ui()
        self._build_menus()
        self._start_worker_thread()

        self.settings_panel.set_defaults(
            self._settings.delay_seconds(), self._settings.archive_completed_pdf()
        )
        self._refresh_printers()
        self._apply_control_state()

    # -- UI construction ------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setSpacing(14)
        root.setContentsMargins(14, 14, 14, 10)

        self.settings_panel = PrintSettingsPanel()
        self.settings_panel.select_pdf_clicked.connect(self._select_pdf)
        self.settings_panel.select_files_clicked.connect(self._select_bulk_files)
        self.settings_panel.refresh_printers_clicked.connect(self._refresh_printers)
        self.settings_panel.printer_selected.connect(lambda _name: self._apply_control_state())
        root.addWidget(self.settings_panel)

        self.progress_panel = ProgressPanel()
        root.addWidget(self.progress_panel)

        action_row = QHBoxLayout()
        self.start_button = QPushButton(icon("media-playback-start"), "Start Printing")
        self.pause_button = QPushButton(icon("media-playback-pause"), "Pause")
        self.resume_button = QPushButton(icon("media-playback-start"), "Resume")
        self.cancel_button = QPushButton(icon("process-stop"), "Cancel")
        self.open_folder_button = QPushButton(icon("folder-open"), "Open Folder")
        for button in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.cancel_button,
            self.open_folder_button,
        ):
            action_row.addWidget(button)
        root.addLayout(action_row)

        self.start_button.clicked.connect(self._on_start_clicked)
        self.pause_button.clicked.connect(lambda: self._worker.control.request_pause())
        self.resume_button.clicked.connect(lambda: self._worker.control.request_resume())
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        self.open_folder_button.clicked.connect(self._on_open_folder_clicked)

        self.log_panel = LogPanel()
        root.addWidget(self.log_panel)
        root.addStretch(1)

        self.setCentralWidget(central)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        self.select_pdf_action = QAction(icon("document-open"), "Select PDF", self)
        self.select_pdf_action.triggered.connect(self._select_pdf)
        file_menu.addAction(self.select_pdf_action)

        open_source_action = QAction(icon("folder-open"), "Open Source Folder", self)
        open_source_action.triggered.connect(self._open_source_folder)
        file_menu.addAction(open_source_action)

        file_menu.addSeparator()
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        file_menu.addAction(self.exit_action)

        tools_menu = menu_bar.addMenu("&Tools")
        split_action = QAction(icon("document-page-setup"), "Split PDF into Pages…", self)
        split_action.triggered.connect(self._open_split_dialog)
        tools_menu.addAction(split_action)

        self.refresh_printers_action = QAction(icon("view-refresh"), "Refresh Printers", self)
        self.refresh_printers_action.triggered.connect(self._refresh_printers)
        tools_menu.addAction(self.refresh_printers_action)

        settings_menu = menu_bar.addMenu("&Settings")
        self.preferences_action = QAction(icon("preferences-system"), "Preferences…", self)
        self.preferences_action.triggered.connect(self._open_preferences_dialog)
        settings_menu.addAction(self.preferences_action)

        help_menu = menu_bar.addMenu("&Help")
        user_guide_action = QAction("User Guide", self)
        user_guide_action.triggered.connect(self._show_user_guide)
        help_menu.addAction(user_guide_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        view_log_action = QAction("View Log Folder", self)
        view_log_action.triggered.connect(self._view_log_folder)
        help_menu.addAction(view_log_action)

    def _start_worker_thread(self) -> None:
        self._thread = QThread(self)
        self._worker = PrintWorker(self._job_manager, self._session_logger)
        self._worker.moveToThread(self._thread)
        self._thread.start()

        self.start_requested.connect(self._worker.start_session)

        self._worker.state_changed.connect(self._on_state_changed)
        self._worker.progress_changed.connect(self._on_progress_changed)
        self._worker.status_changed.connect(self.progress_panel.set_status_message)
        self._worker.log_emitted.connect(self.log_panel.append_line)
        self._worker.countdown_changed.connect(self.progress_panel.set_countdown)
        self._worker.finished.connect(self._on_session_finished)

    # -- control-state application --------------------------------------------

    def _apply_control_state(self) -> None:
        has_printer = self.settings_panel.has_valid_printer()
        cs = control_state_for(self._current_state, has_valid_printer=has_printer)

        self.start_button.setEnabled(cs.start)
        self.pause_button.setEnabled(cs.pause)
        self.resume_button.setEnabled(cs.resume)
        self.cancel_button.setEnabled(cs.cancel)
        self.open_folder_button.setEnabled(cs.open_folder)

        self.settings_panel.set_editable(cs.edit_settings)
        self.select_pdf_action.setEnabled(cs.edit_settings)
        self.refresh_printers_action.setEnabled(cs.edit_settings)
        self.preferences_action.setEnabled(cs.edit_settings)
        self.exit_action.setEnabled(cs.edit_settings)

    # -- session actions --------------------------------------------------------

    def _on_start_clicked(self) -> None:
        mode = self.settings_panel.current_mode()

        if mode is PrintMode.BULK_PRINT:
            bulk_files = self.settings_panel.bulk_files()
            if not bulk_files:
                QMessageBox.information(
                    self, "Select files", "Select at least one PDF for bulk printing."
                )
                return
        else:
            file_text = self.settings_panel.file_edit.text()
            if not file_text:
                QMessageBox.information(self, "Select a PDF", "Select a PDF file before starting.")
                return
            bulk_files = []

        if not self.settings_panel.has_valid_printer():
            QMessageBox.information(
                self, "Select a printer", "Select a valid printer before starting."
            )
            return

        source_path = bulk_files[0] if mode is PrintMode.BULK_PRINT else Path(file_text)
        request = PrintRequest(
            source_path=source_path,
            printer_name=self.settings_panel.selected_printer_name() or "",
            mode=mode,
            copies=self.settings_panel.copies() if mode is PrintMode.DOCUMENT_REPEAT else 1,
            delay_seconds=self.settings_panel.delay_seconds(),
            archive_completed_pdf=self.settings_panel.archive_enabled(),
            item_timeout_seconds=self._settings.item_timeout_seconds(),
            bulk_files=tuple(bulk_files),
        )
        self.log_panel.clear()
        self._last_result = None
        self._bulk_last_completed = 0
        if mode is PrintMode.BULK_PRINT:
            self.settings_panel.set_bulk_progress_markers(completed_count=0, current_index=0)
        self.start_requested.emit(request)

    def _on_cancel_clicked(self) -> None:
        mode = self._ask_cancel_mode()
        if mode is not None:
            self._worker.control.request_cancel(mode)

    def _ask_cancel_mode(self) -> Optional[CancelMode]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Cancel print session?")
        layout = QVBoxLayout(dialog)

        note = QLabel(
            "The current job may already be printing at the device — cancelling here\n"
            "controls what the app does next, not necessarily the printer itself.\n\n"
            "Either way, the source PDF is not archived, and only this session's own\n"
            "temporary files are cleaned up."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        chosen: dict = {"mode": None}

        stop_after_button = QPushButton("Stop after current job")
        stop_after_button.setToolTip(
            "Let the job already submitted to CUPS finish printing. Nothing new is sent."
        )
        cancel_job_button = QPushButton("Cancel current printer job")
        cancel_job_button.setToolTip("Runs “cancel <job-id>”, then stops immediately.")

        def pick(mode: CancelMode) -> None:
            chosen["mode"] = mode
            dialog.accept()

        stop_after_button.clicked.connect(lambda: pick(CancelMode.STOP_AFTER_CURRENT))
        cancel_job_button.clicked.connect(lambda: pick(CancelMode.CANCEL_CURRENT_JOB))
        layout.addWidget(stop_after_button)
        layout.addWidget(cancel_job_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(dialog.reject)
        buttons.button(QDialogButtonBox.Cancel).setText("Keep Printing")
        layout.addWidget(buttons)

        dialog.exec()
        return chosen["mode"]

    def _on_open_folder_clicked(self) -> None:
        folder: Optional[Path] = None
        if self._last_result and self._last_result.archived_path:
            folder = self._last_result.archived_path.parent
        elif self._last_result and self._last_result.archived_paths:
            folder = self._last_result.archived_paths[0].parent
        else:
            file_text = self.settings_panel.file_edit.text()
            if file_text:
                folder = Path(file_text).parent
            elif self.settings_panel.bulk_files():
                folder = self.settings_panel.bulk_files()[0].parent
        if folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -- worker signal handlers ------------------------------------------------

    def _on_state_changed(self, state: SessionState) -> None:
        self._current_state = state
        self.progress_panel.set_state(state)
        self._apply_control_state()

    def _on_progress_changed(self, progress: SessionProgress) -> None:
        mode = self.settings_panel.current_mode()
        mode_word = _MODE_WORD.get(mode, "Item")
        self.progress_panel.set_progress(progress, mode_word)
        if mode is PrintMode.BULK_PRINT:
            self._bulk_last_completed = progress.completed_items
            # completed_items is 1-based once an item finishes; the "current"
            # (in-flight) row is the next one after that.
            self.settings_panel.set_bulk_progress_markers(
                completed_count=progress.completed_items,
                current_index=progress.completed_items,
            )

    def _on_session_finished(self, result: SessionResult) -> None:
        self._last_result = result
        self._current_state = result.state
        self.progress_panel.set_state(result.state)
        self.progress_panel.set_status_message(result.message)
        self.progress_panel.set_progress_tone(_FINISHED_PROGRESS_TONE.get(result.state, "info"))
        if self.settings_panel.current_mode() is PrintMode.BULK_PRINT:
            # Clear the "in flight" marker — nothing is printing anymore —
            # but keep the checkmarks already earned by files that finished.
            self.settings_panel.set_bulk_progress_markers(
                completed_count=self._bulk_last_completed, current_index=None
            )
        self._apply_control_state()

    # -- File menu ---------------------------------------------------------------

    def _select_pdf(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Select PDF", "", "PDF Files (*.pdf)")
        if path_str:
            self.settings_panel.set_file_path(path_str)
            self._apply_control_state()

    def _select_bulk_files(self) -> None:
        path_strs, _ = QFileDialog.getOpenFileNames(self, "Select PDFs", "", "PDF Files (*.pdf)")
        if path_strs:
            self.settings_panel.add_bulk_files([Path(p) for p in path_strs])
            self._apply_control_state()

    def _open_source_folder(self) -> None:
        file_text = self.settings_panel.file_edit.text()
        if file_text:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(file_text).parent)))
            return
        bulk_files = self.settings_panel.bulk_files()
        if bulk_files:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(bulk_files[0].parent)))
            return
        QMessageBox.information(self, "No file selected", "Select a PDF first.")

    # -- Tools menu ---------------------------------------------------------------

    def _refresh_printers(self) -> None:
        try:
            printers = self._cups.list_printers()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Couldn't list printers", str(exc))
            printers = []
        current = self.settings_panel.selected_printer_name()
        self.settings_panel.set_printers(printers, selected_name=current)
        self._apply_control_state()

    def _open_split_dialog(self) -> None:
        file_text = self.settings_panel.file_edit.text()
        initial_dir = str(Path(file_text).parent) if file_text else ""
        dialog = SplitDialog(self._pdf_service, initial_dir=initial_dir, parent=self)
        dialog.exec()

    # -- Settings menu ------------------------------------------------------------

    def _open_preferences_dialog(self) -> None:
        dialog = PreferencesDialog(self._settings, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.settings_panel.set_defaults(
                self._settings.delay_seconds(), self._settings.archive_completed_pdf()
            )

    # -- Help menu ------------------------------------------------------------------

    def _show_user_guide(self) -> None:
        QMessageBox.information(
            self,
            "User Guide",
            "See README.md, in the application's install folder, for the full user guide "
            "covering printing modes, delays, pause/resume/cancel, PrintedCompleted, and "
            "PDF splitting.",
        )

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PDF Print Manager",
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Prints PDFs with controlled timing and sequencing via CUPS.\n"
            "Licensed under the MIT License.",
        )

    def _view_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(default_log_dir())))

    # -- shutdown -------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        legend = legend_for_state(self._current_state)
        if legend in _ACTIVE_LEGENDS:
            reply = QMessageBox.question(
                self,
                "Session in progress",
                "A print session is still active. Exit anyway? The session will be cancelled.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self._worker.control.request_cancel(CancelMode.STOP_AFTER_CURRENT)

        self._thread.quit()
        self._thread.wait(3000)
        event.accept()
