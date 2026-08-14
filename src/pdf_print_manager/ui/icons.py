"""Icon lookups that prefer the user's own desktop icon theme.

Per the confirmed design review, the real app uses `QIcon.fromTheme` (Breeze,
Adwaita, hicolor, ...) so it matches whatever desktop it's running on, falling
back to a small bundled monochrome SVG set only when the active theme doesn't
provide a name — e.g. a minimal or non-freedesktop-compliant theme.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

_ASSETS_ICON_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"

# Freedesktop icon-naming-spec names -> bundled fallback file.
_FALLBACKS = {
    "document-open": "document-open.svg",
    "document-print": "document-print.svg",
    "view-refresh": "view-refresh.svg",
    "media-playback-start": "media-playback-start.svg",
    "media-playback-pause": "media-playback-pause.svg",
    "process-stop": "process-stop.svg",
    "folder-open": "folder-open.svg",
    "dialog-ok": "dialog-ok.svg",
    "dialog-warning": "dialog-warning.svg",
    "dialog-error": "dialog-error.svg",
    "document-page-setup": "document-page-setup.svg",
    "preferences-system": "preferences-system.svg",
}

_cache: "dict[str, QIcon]" = {}


def icon(theme_name: str) -> QIcon:
    """Look up `theme_name` in the active desktop icon theme; fall back to the
    bundled asset of the same name if the theme doesn't have it."""
    cached = _cache.get(theme_name)
    if cached is not None:
        return cached

    themed = QIcon.fromTheme(theme_name)
    if not themed.isNull():
        _cache[theme_name] = themed
        return themed

    fallback_name = _FALLBACKS.get(theme_name)
    result = QIcon()
    if fallback_name:
        fallback_path = _ASSETS_ICON_DIR / fallback_name
        if fallback_path.exists():
            result = QIcon(str(fallback_path))
    _cache[theme_name] = result
    return result


def app_icon() -> QIcon:
    return QIcon(str(_ASSETS_ICON_DIR / "pdf-print-manager.svg"))
