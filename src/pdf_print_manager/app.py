"""Application entry point: builds the QApplication, wires services together,
and shows MainWindow."""

from __future__ import annotations

import sys
from typing import List, Optional

from PySide6.QtWidgets import QApplication

from .config import APP_NAME, APP_VERSION, ORG_NAME
from .job_manager import JobManager
from .services.archive_service import ArchiveService
from .services.cups_client import CupsClient
from .services.logging_service import configure_logging
from .services.pdf_service import PdfService
from .services.settings_service import SettingsService
from .ui.main_window import MainWindow


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv if argv is not None else sys.argv)

    configure_logging()

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(APP_VERSION)

    settings = SettingsService()
    cups = CupsClient()
    pdf_service = PdfService()
    archive_service = ArchiveService()
    job_manager = JobManager(cups, pdf_service, archive_service)

    window = MainWindow(
        settings=settings,
        cups=cups,
        pdf_service=pdf_service,
        archive_service=archive_service,
        job_manager=job_manager,
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
