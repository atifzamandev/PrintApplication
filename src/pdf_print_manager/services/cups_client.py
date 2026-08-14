"""Printer listing, job submission, monitoring, and cancellation via CUPS.

Everything that talks to `lp` / `lpstat` / `cancel` goes through this module,
always as argument lists (never `shell=True`, never interpolated strings).
The output-parsing logic is split into plain functions at module level so it
can be unit-tested against captured `lpstat`/`lp` text without running any
subprocess at all.

Job-state note
--------------
`lpstat` has no single "tell me the final state of job X" query that works
identically across CUPS configurations (job history retention varies with
`PreserveJobHistory`/`MaxJobs`). The approach here is:

1. While the job id still appears in `lpstat -W not-completed`, it's PROCESSING.
2. Once it disappears from that list, check `-W completed`, `-W aborted`, and
   `-W canceled`/`-W cancelled` (CUPS has used both spellings) in turn.
3. If it isn't found in any of those either, report UNKNOWN rather than
   guessing — the spec is explicit that an empty queue must never be treated
   as success. `JobManager` is responsible for deciding how many UNKNOWN
   polls to tolerate before treating the job as failed/timed out.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import List, Optional, Set

from ..errors import CupsCommandError
from ..models import CupsJobState, PrinterInfo
from ._subprocess_utils import log_subprocess

logger = logging.getLogger(__name__)

_JOB_ID_RE = re.compile(r"request id is (\S+)")
_PRINTER_LINE_RE = re.compile(r"^printer\s+(\S+)\s+(.*)$")
_ACCEPTING_LINE_RE = re.compile(r"^(\S+)\s+(accepting requests|not accepting requests)\b")
_DEFAULT_DEST_RE = re.compile(r"system default destination:\s*(\S+)")

# `-W` job-listing windows we probe, in the order the caller should check them.
_JOB_LISTING_STATES = {
    "not-completed": CupsJobState.PROCESSING,
    "completed": CupsJobState.COMPLETED,
    "aborted": CupsJobState.ABORTED,
    "canceled": CupsJobState.CANCELLED,
    "cancelled": CupsJobState.CANCELLED,
}


def parse_job_id(lp_stdout: str) -> str:
    """Extract the CUPS job id from `lp`'s stdout, e.g.
    "request id is HP-LaserJet-1022-42 (1 file(s))" -> "HP-LaserJet-1022-42".
    """
    match = _JOB_ID_RE.search(lp_stdout)
    if not match:
        raise CupsCommandError(f"Could not find a job id in lp output: {lp_stdout!r}")
    return match.group(1)


def parse_job_ids(lpstat_w_stdout: str) -> Set[str]:
    """Parse the first whitespace-separated token of each non-empty line of an
    `lpstat -W <window>` listing as a job id. Lines like "no entries" or
    similar chatter simply won't match a real job's `printer-name-123` shape
    closely enough to matter here — we just collect first tokens defensively.
    """
    ids: Set[str] = set()
    for line in lpstat_w_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        token = line.split()[0]
        # A real CUPS job id always ends in "-<digits>".
        if re.search(r"-\d+$", token):
            ids.add(token)
    return ids


def parse_printers(lpstat_p_stdout: str, lpstat_a_stdout: str = "") -> List[PrinterInfo]:
    """Combine `lpstat -p` (enabled/disabled) with `lpstat -a` (accepting
    requests) into a list of PrinterInfo. Either input may be empty.
    """
    accepting = {}
    for line in lpstat_a_stdout.splitlines():
        match = _ACCEPTING_LINE_RE.match(line.strip())
        if match:
            accepting[match.group(1)] = match.group(2) == "accepting requests"

    printers: List[PrinterInfo] = []
    for line in lpstat_p_stdout.splitlines():
        match = _PRINTER_LINE_RE.match(line.strip())
        if not match:
            continue
        name, rest = match.group(1), match.group(2)
        enabled = "disabled" not in rest.lower()
        printers.append(
            PrinterInfo(
                name=name,
                enabled=enabled,
                accepting_jobs=accepting.get(name, True),
            )
        )
    return printers


def parse_default_printer(lpstat_d_stdout: str) -> Optional[str]:
    match = _DEFAULT_DEST_RE.search(lpstat_d_stdout)
    return match.group(1) if match else None


class CupsClient:
    """Thin, argument-list-only wrapper around the `lp`/`lpstat`/`cancel` CLIs."""

    def __init__(self, runner=subprocess.run) -> None:
        self._runner = runner

    def list_printers(self) -> List[PrinterInfo]:
        p_result = self._run(["lpstat", "-p"])
        a_result = self._run(["lpstat", "-a"])
        printers = parse_printers(p_result.stdout, a_result.stdout)
        default = self.default_printer()
        if default:
            printers = [
                PrinterInfo(
                    name=p.name,
                    is_default=(p.name == default),
                    enabled=p.enabled,
                    accepting_jobs=p.accepting_jobs,
                )
                for p in printers
            ]
        return printers

    def default_printer(self) -> Optional[str]:
        result = self._run(["lpstat", "-d"])
        return parse_default_printer(result.stdout)

    def submit_job(self, printer_name: str, pdf_path: Path) -> str:
        result = self._run(["lp", "-d", printer_name, str(pdf_path)])
        if result.returncode != 0:
            raise CupsCommandError(
                f"lp failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return parse_job_id(result.stdout)

    def get_job_state(self, job_id: str) -> CupsJobState:
        for window, state in _JOB_LISTING_STATES.items():
            result = self._run(["lpstat", "-W", window])
            if result.returncode != 0:
                # Some CUPS versions reject "canceled" or "cancelled" spelling;
                # treat a non-zero exit for a probe window as "not found here".
                continue
            if job_id in parse_job_ids(result.stdout):
                return state
        return CupsJobState.UNKNOWN

    def cancel_job(self, job_id: str) -> bool:
        result = self._run(["cancel", job_id])
        return result.returncode == 0

    def _run(self, args: List[str]) -> "subprocess.CompletedProcess[str]":
        result = self._runner(args, capture_output=True, text=True, check=False)
        log_subprocess(args[0], result)
        return result
