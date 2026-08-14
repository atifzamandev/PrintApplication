"""Small shared helper used by every service that shells out to a system
command. Kept separate so services never need to import one another just to
get consistent diagnostic logging."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def log_subprocess(command_name: str, result: "subprocess.CompletedProcess[str]") -> None:
    """Log return code, stdout, and stderr for diagnostics, as required by
    the spec for every `lp`/`lpstat`/`cancel`/`pdfseparate` invocation."""
    logger.info(
        "%s exit=%s stdout=%r stderr=%r",
        command_name,
        result.returncode,
        result.stdout.strip(),
        result.stderr.strip(),
    )
