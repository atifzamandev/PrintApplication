"""Tools -> Split PDF into Pages... — spec section 7.

Splits into a temporary directory first and only moves pages into the
destination folder once the whole split has succeeded (handled by
`PdfService.split_into_folder`), and never silently overwrites an existing
populated `<name>_split` folder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..errors import PdfServiceError, ValidationError
from ..models import SplitConflictChoice
from .icons import icon


class SplitDialog(QDialog):
    def __init__(self, pdf_service, initial_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self._pdf_service = pdf_service
        self._initial_dir = initial_dir
        self._source: Optional[Path] = None
        self.setWindowTitle("Split PDF into Pages…")
        self.setMinimumWidth(420)
        self._build_ui()
        self._choose_source()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source"))
        self.source_label = QLabel("—")
        source_row.addWidget(self.source_label, 1)
        change_button = QPushButton("Choose…")
        change_button.clicked.connect(self._choose_source)
        source_row.addWidget(change_button)
        root.addLayout(source_row)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("Creates"))
        self.dest_label = QLabel("—")
        dest_row.addWidget(self.dest_label, 1)
        root.addLayout(dest_row)

        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        root.addWidget(self.result_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.open_folder_button = QPushButton(icon("folder-open"), "Open Folder")
        self.open_folder_button.setVisible(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        self.split_button = QPushButton(icon("document-page-setup"), "Split into Pages")
        self.split_button.setDefault(True)
        self.split_button.clicked.connect(self._do_split)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.split_button)
        root.addLayout(button_row)

        self._output_dir: Optional[Path] = None

    def _choose_source(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Choose a PDF to split", self._initial_dir, "PDF Files (*.pdf)"
        )
        if not path_str:
            if self._source is None:
                self.reject()
            return
        self._source = Path(path_str)
        self.source_label.setText(self._source.name)
        destination = self._pdf_service.plan_split_destination(self._source)
        self.dest_label.setText(f"{destination.name}/")
        self.result_label.setVisible(False)
        self.open_folder_button.setVisible(False)
        self.split_button.setVisible(True)

    def _do_split(self) -> None:
        if self._source is None:
            return

        destination = self._pdf_service.plan_split_destination(self._source)
        replace = False

        if self._pdf_service.destination_has_conflict(destination):
            choice = self._ask_conflict_choice(destination)
            if choice is SplitConflictChoice.CANCEL:
                return
            if choice is SplitConflictChoice.UNIQUE_FOLDER:
                destination = self._pdf_service.unique_destination(destination)
            else:
                replace = True

        try:
            result = self._pdf_service.split_into_folder(self._source, destination, replace=replace)
        except (PdfServiceError, ValidationError) as exc:
            QMessageBox.critical(self, "Split failed", str(exc))
            return

        self._output_dir = result.output_dir
        self.dest_label.setText(f"{result.output_dir.name}/")
        self.result_label.setText(
            f"{result.page_count} page(s) created in {result.output_dir.name}/. "
            f"The original {self._source.name} was not moved or modified."
        )
        self.result_label.setVisible(True)
        self.open_folder_button.setVisible(True)
        self.split_button.setVisible(False)

    def _ask_conflict_choice(self, destination: Path) -> SplitConflictChoice:
        box = QMessageBox(self)
        box.setWindowTitle("Folder already has split pages")
        box.setText(
            f"{destination.name}/ already contains generated pages. What would you like to do?"
        )
        replace_btn = box.addButton("Replace generated files", QMessageBox.AcceptRole)
        unique_btn = box.addButton("Create a new folder", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is replace_btn:
            return SplitConflictChoice.REPLACE
        if clicked is unique_btn:
            return SplitConflictChoice.UNIQUE_FOLDER
        return SplitConflictChoice.CANCEL

    def _open_output_folder(self) -> None:
        if self._output_dir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
