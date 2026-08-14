"""QSettings-backed persistence for the small set of user preferences the
spec calls out: default delay, archive-on-completion, and the per-item
timeout."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSettings

from ..config import (
    APP_SETTINGS_NAME,
    DEFAULT_ARCHIVE_COMPLETED_PDF,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_ITEM_TIMEOUT_SECONDS,
    ORG_NAME,
)

_KEY_DELAY = "printing/delay_seconds"
_KEY_ARCHIVE = "printing/archive_completed_pdf"
_KEY_TIMEOUT = "printing/item_timeout_seconds"


def _as_bool(value: object, default: bool) -> bool:
    """QSettings may hand back a real bool, or the string 'true'/'false'
    depending on the backing store — normalize both."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return default


class SettingsService:
    def __init__(self, settings: Optional[QSettings] = None) -> None:
        self._settings = settings or QSettings(ORG_NAME, APP_SETTINGS_NAME)

    def delay_seconds(self) -> int:
        return int(self._settings.value(_KEY_DELAY, DEFAULT_DELAY_SECONDS))

    def set_delay_seconds(self, value: int) -> None:
        self._settings.setValue(_KEY_DELAY, int(value))

    def archive_completed_pdf(self) -> bool:
        return _as_bool(
            self._settings.value(_KEY_ARCHIVE, DEFAULT_ARCHIVE_COMPLETED_PDF),
            DEFAULT_ARCHIVE_COMPLETED_PDF,
        )

    def set_archive_completed_pdf(self, value: bool) -> None:
        self._settings.setValue(_KEY_ARCHIVE, bool(value))

    def item_timeout_seconds(self) -> int:
        return int(self._settings.value(_KEY_TIMEOUT, DEFAULT_ITEM_TIMEOUT_SECONDS))

    def set_item_timeout_seconds(self, value: int) -> None:
        self._settings.setValue(_KEY_TIMEOUT, int(value))
