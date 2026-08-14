"""Custom exceptions shared across services and the job manager.

Kept in their own module (rather than inside each service) so that
``job_manager.py`` can catch specific failure types without importing the
full service modules and risking circular imports.
"""

from __future__ import annotations


class PdfPrintManagerError(Exception):
    """Base class for all application-specific errors."""


class ValidationError(PdfPrintManagerError):
    """The selected PDF or printer failed validation before a session could start."""


class CupsCommandError(PdfPrintManagerError):
    """An `lp`, `lpstat`, or `cancel` invocation failed or returned unparsable output."""


class PdfServiceError(PdfPrintManagerError):
    """Splitting or otherwise processing a PDF with `pdfseparate`/`pdftops` failed."""


class ArchiveError(PdfPrintManagerError):
    """The completed PDF could not be moved into `PrintedCompleted`."""


class SplitConflictError(PdfPrintManagerError):
    """The split destination folder already contains generated pages and the
    caller did not specify how to resolve the conflict."""
