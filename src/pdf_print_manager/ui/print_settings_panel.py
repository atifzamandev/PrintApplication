"""File/printer selection, printing mode, delay, and the archive checkbox —
everything the spec's "2. Core requirements" and "3. Printing modes"
sections describe as user-facing controls, plus Bulk Print's multi-file list.

Per the confirmed design review: the printer field stays interactive even
when no valid printer is selected, so the user can pick one right there
rather than being routed through some other control to unblock Start.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import MAX_COPIES, MAX_DELAY_SECONDS, MIN_COPIES, MIN_DELAY_SECONDS
from ..models import PrintMode, PrinterInfo
from .icons import icon


class PrintSettingsPanel(QWidget):
    select_pdf_clicked = Signal()
    select_files_clicked = Signal()
    refresh_printers_clicked = Signal()
    printer_selected = Signal(str)
    mode_changed = Signal(object)  # PrintMode
    copies_changed = Signal(int)
    delay_changed = Signal(int)
    archive_toggled = Signal(bool)
    bulk_files_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._printers: List[PrinterInfo] = []
        self._bulk_paths: List[Path] = []
        self._build_ui()
        self._wire_signals()

    # -- construction -----------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # -- single-file row (Repeat / Page-by-Page) --
        self.single_file_widget = QWidget()
        file_row = QHBoxLayout(self.single_file_widget)
        file_row.setContentsMargins(0, 0, 0, 0)
        file_label = QLabel("File")
        file_label.setFixedWidth(54)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText("No PDF selected")
        self.select_button = QPushButton(icon("document-open"), "Select…")
        file_row.addWidget(file_label)
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(self.select_button)
        root.addWidget(self.single_file_widget)

        # -- multi-file list (Bulk Print) --
        self.bulk_files_widget = QWidget()
        bulk_layout = QVBoxLayout(self.bulk_files_widget)
        bulk_layout.setContentsMargins(0, 0, 0, 0)
        bulk_layout.setSpacing(6)

        self.bulk_count_label = QLabel("No files selected")
        bulk_layout.addWidget(self.bulk_count_label)

        self.bulk_list = QListWidget()
        self.bulk_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.bulk_list.setFixedHeight(110)
        bulk_layout.addWidget(self.bulk_list)

        bulk_button_row = QHBoxLayout()
        self.select_files_button = QPushButton(icon("document-open"), "Select Files…")
        self.remove_files_button = QPushButton("Remove Selected")
        self.clear_files_button = QPushButton("Clear All")
        bulk_button_row.addWidget(self.select_files_button)
        bulk_button_row.addWidget(self.remove_files_button)
        bulk_button_row.addWidget(self.clear_files_button)
        bulk_button_row.addStretch(1)
        bulk_layout.addLayout(bulk_button_row)

        root.addWidget(self.bulk_files_widget)
        self.bulk_files_widget.setVisible(False)

        # -- printer row --
        printer_row = QHBoxLayout()
        printer_label = QLabel("Printer")
        printer_label.setFixedWidth(54)
        self.printer_combo = QComboBox()
        self.printer_combo.setEditable(False)
        self.refresh_button = QPushButton(icon("view-refresh"), "Refresh")
        printer_row.addWidget(printer_label)
        printer_row.addWidget(self.printer_combo, 1)
        printer_row.addWidget(self.refresh_button)
        root.addLayout(printer_row)

        self.printer_error_label = QLabel()
        self.printer_error_label.setWordWrap(True)
        self.printer_error_label.setStyleSheet("color: #a6362f;")
        self.printer_error_label.setVisible(False)
        root.addWidget(self.printer_error_label)

        mode_box = QGroupBox("Printing mode")
        mode_layout = QVBoxLayout(mode_box)

        repeat_row = QHBoxLayout()
        self.repeat_radio = QRadioButton("Repeat full document")
        self.repeat_radio.setChecked(True)
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(MIN_COPIES, MAX_COPIES)
        self.copies_spin.setValue(1)
        repeat_row.addWidget(self.repeat_radio)
        repeat_row.addWidget(QLabel("Copies"))
        repeat_row.addWidget(self.copies_spin)
        repeat_row.addStretch(1)
        mode_layout.addLayout(repeat_row)

        self.page_radio = QRadioButton("Print page by page")
        mode_layout.addWidget(self.page_radio)

        self.bulk_radio = QRadioButton("Bulk print (multiple files)")
        mode_layout.addWidget(self.bulk_radio)

        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.repeat_radio)
        self.mode_group.addButton(self.page_radio)
        self.mode_group.addButton(self.bulk_radio)

        delay_row = QFormLayout()
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
        self.delay_spin.setValue(10)
        self.delay_spin.setSuffix(" s")
        delay_row.addRow("Delay between jobs/pages/files", self.delay_spin)
        mode_layout.addLayout(delay_row)

        self.archive_checkbox = QCheckBox("Move completed PDF to PrintedCompleted")
        self.archive_checkbox.setChecked(True)
        mode_layout.addWidget(self.archive_checkbox)

        root.addWidget(mode_box)

    def _wire_signals(self) -> None:
        self.select_button.clicked.connect(self.select_pdf_clicked)
        self.select_files_button.clicked.connect(self.select_files_clicked)
        self.remove_files_button.clicked.connect(self._remove_selected_bulk_files)
        self.clear_files_button.clicked.connect(self.clear_bulk_files)
        self.refresh_button.clicked.connect(self.refresh_printers_clicked)
        self.printer_combo.currentIndexChanged.connect(self._on_printer_index_changed)
        self.repeat_radio.toggled.connect(self._on_mode_toggled)
        self.page_radio.toggled.connect(self._on_mode_toggled)
        self.bulk_radio.toggled.connect(self._on_mode_toggled)
        self.copies_spin.valueChanged.connect(self.copies_changed)
        self.delay_spin.valueChanged.connect(self.delay_changed)
        self.archive_checkbox.toggled.connect(self.archive_toggled)

    def _on_mode_toggled(self, checked: bool) -> None:
        if not checked:
            return  # only react to the radio that just became checked
        mode = self.current_mode()
        is_bulk = mode is PrintMode.BULK_PRINT
        self.single_file_widget.setVisible(not is_bulk)
        self.bulk_files_widget.setVisible(is_bulk)
        self.copies_spin.setEnabled(mode is PrintMode.DOCUMENT_REPEAT and self.isEnabled())
        self.mode_changed.emit(mode)

    def _on_printer_index_changed(self, _index: int) -> None:
        name = self.selected_printer_name()
        if name:
            self.printer_selected.emit(name)

    # -- public API ---------------------------------------------------------

    def set_file_path(self, path: str) -> None:
        self.file_edit.setText(path)

    def set_printers(self, printers: List[PrinterInfo], selected_name: Optional[str] = None) -> None:
        self._printers = printers
        self.printer_combo.blockSignals(True)
        self.printer_combo.clear()
        for printer in printers:
            self.printer_combo.addItem(printer.name)
            index = self.printer_combo.count() - 1
            if not printer.is_usable:
                item_model = self.printer_combo.model().item(index)
                if item_model is not None:
                    item_model.setEnabled(False)
        self.printer_combo.blockSignals(False)

        target = selected_name or next((p.name for p in printers if p.is_default), None)
        if target:
            i = self.printer_combo.findText(target)
            if i >= 0:
                self.printer_combo.setCurrentIndex(i)
        self._refresh_printer_error()

    def selected_printer_name(self) -> Optional[str]:
        return self.printer_combo.currentText() or None

    def has_valid_printer(self) -> bool:
        name = self.selected_printer_name()
        if not name:
            return False
        info = next((p for p in self._printers if p.name == name), None)
        return bool(info and info.is_usable)

    def _refresh_printer_error(self) -> None:
        if not self._printers:
            self.printer_error_label.setText(
                "No printers found — click Refresh, or check that CUPS is running."
            )
            self.printer_error_label.setVisible(True)
        elif not self.has_valid_printer():
            self.printer_error_label.setText(
                "Select a printer, or click Refresh — the current selection is offline or rejecting jobs."
            )
            self.printer_error_label.setVisible(True)
        else:
            self.printer_error_label.setVisible(False)

    def current_mode(self) -> PrintMode:
        if self.bulk_radio.isChecked():
            return PrintMode.BULK_PRINT
        if self.page_radio.isChecked():
            return PrintMode.PAGE_BY_PAGE
        return PrintMode.DOCUMENT_REPEAT

    def copies(self) -> int:
        return self.copies_spin.value()

    def delay_seconds(self) -> int:
        return self.delay_spin.value()

    def archive_enabled(self) -> bool:
        return self.archive_checkbox.isChecked()

    def set_defaults(self, delay_seconds: int, archive_completed: bool) -> None:
        self.delay_spin.setValue(delay_seconds)
        self.archive_checkbox.setChecked(archive_completed)

    def set_editable(self, editable: bool) -> None:
        self.select_button.setEnabled(editable)
        self.printer_combo.setEnabled(editable)
        self.refresh_button.setEnabled(editable)
        self.repeat_radio.setEnabled(editable)
        self.page_radio.setEnabled(editable)
        self.bulk_radio.setEnabled(editable)
        self.copies_spin.setEnabled(editable and self.repeat_radio.isChecked())
        self.delay_spin.setEnabled(editable)
        self.archive_checkbox.setEnabled(editable)
        self.select_files_button.setEnabled(editable)
        self.remove_files_button.setEnabled(editable)
        self.clear_files_button.setEnabled(editable)
        self.bulk_list.setEnabled(editable)

    def refresh_validation(self) -> None:
        self._refresh_printer_error()

    # -- bulk file list -------------------------------------------------------

    def bulk_files(self) -> List[Path]:
        return list(self._bulk_paths)

    def set_bulk_files(self, paths: List[Path]) -> None:
        self._bulk_paths = list(paths)
        self._refresh_bulk_list()

    def add_bulk_files(self, paths: List[Path]) -> None:
        existing = set(self._bulk_paths)
        for path in paths:
            if path not in existing:
                self._bulk_paths.append(path)
                existing.add(path)
        self._refresh_bulk_list()

    def clear_bulk_files(self) -> None:
        self._bulk_paths = []
        self._refresh_bulk_list()

    def _remove_selected_bulk_files(self) -> None:
        rows = sorted((self.bulk_list.row(item) for item in self.bulk_list.selectedItems()), reverse=True)
        for row in rows:
            del self._bulk_paths[row]
        self._refresh_bulk_list()

    def _refresh_bulk_list(self) -> None:
        self.bulk_list.clear()
        for path in self._bulk_paths:
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            self.bulk_list.addItem(item)
        count = len(self._bulk_paths)
        self.bulk_count_label.setText(
            "No files selected" if count == 0 else f"{count} file{'s' if count != 1 else ''} selected"
        )
        self.bulk_files_changed.emit()

    def set_bulk_progress_markers(
        self, completed_count: int, current_index: Optional[int] = None
    ) -> None:
        """Reflects live progress in the list: a check mark for files already
        printed (and archived), a play glyph for the one in flight, nothing
        for files still pending."""
        for row in range(self.bulk_list.count()):
            item = self.bulk_list.item(row)
            if row < completed_count:
                item.setIcon(icon("dialog-ok"))
            elif current_index is not None and row == current_index:
                item.setIcon(icon("media-playback-start"))
            else:
                item.setIcon(QIcon())
