"""Enums, dataclasses, and result models used across the app.

Nothing in this module imports PySide6 or subprocess — it stays a plain,
easily-unit-testable description of the domain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import List, Optional, Tuple


class PrintMode(Enum):
    DOCUMENT_REPEAT = "document_repeat"
    PAGE_BY_PAGE = "page_by_page"
    BULK_PRINT = "bulk_print"


class SessionState(Enum):
    IDLE = auto()
    VALIDATING = auto()
    PREPARING = auto()
    SUBMITTING = auto()
    WAITING_FOR_CUPS = auto()
    WAITING_DELAY = auto()
    PAUSED = auto()
    CANCELLING = auto()
    ARCHIVING = auto()
    COMPLETED = auto()
    COMPLETED_WITH_WARNING = auto()
    CANCELLED = auto()
    FAILED = auto()


# States in which the session is actively doing work — as opposed to idle,
# paused, cancelling, or one of the finished states.
ACTIVE_STATES = frozenset(
    {
        SessionState.VALIDATING,
        SessionState.PREPARING,
        SessionState.SUBMITTING,
        SessionState.WAITING_FOR_CUPS,
        SessionState.WAITING_DELAY,
        SessionState.ARCHIVING,
    }
)

FINISHED_STATES = frozenset(
    {
        SessionState.COMPLETED,
        SessionState.COMPLETED_WITH_WARNING,
        SessionState.CANCELLED,
        SessionState.FAILED,
    }
)


class CupsJobState(Enum):
    """A CUPS job's state as best determined by polling `lpstat`.

    UNKNOWN means the job left `lpstat -W not-completed` without turning up in
    any of the completed/aborted/cancelled listings yet — see
    `CupsClient.get_job_state` for why that's tracked separately rather than
    treated as success.
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    ABORTED = "aborted"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class CancelMode(Enum):
    STOP_AFTER_CURRENT = "stop_after_current"
    CANCEL_CURRENT_JOB = "cancel_current_job"


class SplitConflictChoice(Enum):
    REPLACE = "replace"
    UNIQUE_FOLDER = "unique_folder"
    CANCEL = "cancel"


@dataclass(frozen=True)
class PrintRequest:
    source_path: Path
    printer_name: str
    mode: PrintMode
    copies: int = 1
    delay_seconds: int = 10
    archive_completed_pdf: bool = True
    item_timeout_seconds: int = 1800
    # Only used when mode is BULK_PRINT — the full list of files to print in
    # order. `source_path` is still required above; for bulk requests it's
    # just set to the first file and otherwise unused (kept so callers don't
    # need a second, mode-conditional required field).
    bulk_files: Tuple[Path, ...] = ()


@dataclass(frozen=True)
class PrinterInfo:
    name: str
    is_default: bool = False
    enabled: bool = True
    accepting_jobs: bool = True

    @property
    def is_usable(self) -> bool:
        return self.enabled and self.accepting_jobs


@dataclass
class SessionProgress:
    total_items: int = 0
    completed_items: int = 0
    current_item_label: str = ""
    current_job_id: Optional[str] = None

    @property
    def fraction(self) -> float:
        if self.total_items <= 0:
            return 0.0
        return self.completed_items / self.total_items


@dataclass
class SessionResult:
    state: SessionState
    message: str = ""
    archived_path: Optional[Path] = None
    error: Optional[str] = None
    # Only populated for BULK_PRINT sessions — each file is archived right
    # after its own successful print, independently of the others, so a bulk
    # result can have several archived files instead of one.
    archived_paths: List[Path] = field(default_factory=list)
