"""Static application constants — names, defaults, and limits pulled directly
from the requirements spec, kept in one place so they're never hard-coded
twice with diverging values."""

from __future__ import annotations

APP_NAME = "PDF Print Manager"
APP_VERSION = "0.1.0"
ORG_NAME = "PdfPrintManager"
APP_SETTINGS_NAME = "PdfPrintManager"

ARCHIVE_DIR_NAME = "PrintedCompleted"

DEFAULT_DELAY_SECONDS = 10
MIN_DELAY_SECONDS = 0
MAX_DELAY_SECONDS = 86_400

DEFAULT_ITEM_TIMEOUT_SECONDS = 1800  # 30 minutes, configurable in Preferences
MIN_ITEM_TIMEOUT_MINUTES = 1
MAX_ITEM_TIMEOUT_MINUTES = 24 * 60

DEFAULT_ARCHIVE_COMPLETED_PDF = True

DEFAULT_COPIES = 1
MIN_COPIES = 1
MAX_COPIES = 9999

CUPS_POLL_INTERVAL_SECONDS = 1.0
DELAY_TICK_SECONDS = 0.2
MAX_CONSECUTIVE_UNKNOWN_POLLS = 5
