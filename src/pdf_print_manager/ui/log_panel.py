"""The collapsible "Activity log" panel at the bottom of the main window."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QToolButton, QVBoxLayout, QWidget


class LogPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        self.toggle_button = QToolButton()
        self.toggle_button.setText("Activity log")
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(False)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(Qt.RightArrow)
        self.toggle_button.toggled.connect(self._on_toggled)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setMaximumBlockCount(2000)
        self.text_edit.setFixedHeight(120)
        self.text_edit.setVisible(False)

        root.addWidget(self.toggle_button)
        root.addWidget(self.text_edit)

    def _on_toggled(self, checked: bool) -> None:
        self.text_edit.setVisible(checked)
        self.toggle_button.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)

    def append_line(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.text_edit.appendPlainText(f"{timestamp}  {message}")

    def clear(self) -> None:
        self.text_edit.clear()
