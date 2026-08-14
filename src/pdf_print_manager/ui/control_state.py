"""Single source of truth for which controls are enabled in each session
state — this is the control-state table from the spec, plus the two
confirmed refinements from the design review:

* Start also requires a valid printer to be selected, even while Ready.
* Cancel is disabled once teardown starts (Cancelling), instead of staying
  clickable as the spec's table literally shows.
* Open Folder is enabled for every finished outcome (Completed,
  Completed-with-warning, Failed, and Cancelled) — not just Completed.

Framework-free by design, so the button-enablement logic itself can be unit
tested without importing PySide6.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..models import SessionState

LEGEND_READY = "ready"
LEGEND_RUNNING = "running"
LEGEND_PAUSED = "paused"
LEGEND_CANCELLING = "cancelling"
LEGEND_FINISHED = "finished"

_STATE_TO_LEGEND = {
    SessionState.IDLE: LEGEND_READY,
    SessionState.VALIDATING: LEGEND_RUNNING,
    SessionState.PREPARING: LEGEND_RUNNING,
    SessionState.SUBMITTING: LEGEND_RUNNING,
    SessionState.WAITING_FOR_CUPS: LEGEND_RUNNING,
    SessionState.WAITING_DELAY: LEGEND_RUNNING,
    SessionState.PAUSED: LEGEND_PAUSED,
    SessionState.CANCELLING: LEGEND_CANCELLING,
    SessionState.ARCHIVING: LEGEND_RUNNING,
    SessionState.COMPLETED: LEGEND_FINISHED,
    SessionState.COMPLETED_WITH_WARNING: LEGEND_FINISHED,
    SessionState.CANCELLED: LEGEND_FINISHED,
    SessionState.FAILED: LEGEND_FINISHED,
}


@dataclass(frozen=True)
class ControlState:
    start: bool
    pause: bool
    resume: bool
    cancel: bool
    edit_settings: bool
    open_folder: bool


_TABLE = {
    LEGEND_READY: ControlState(
        start=True, pause=False, resume=False, cancel=False, edit_settings=True, open_folder=False
    ),
    LEGEND_RUNNING: ControlState(
        start=False, pause=True, resume=False, cancel=True, edit_settings=False, open_folder=False
    ),
    LEGEND_PAUSED: ControlState(
        start=False, pause=False, resume=True, cancel=True, edit_settings=False, open_folder=False
    ),
    LEGEND_CANCELLING: ControlState(
        start=False, pause=False, resume=False, cancel=False, edit_settings=False, open_folder=False
    ),
    LEGEND_FINISHED: ControlState(
        start=True, pause=False, resume=False, cancel=False, edit_settings=True, open_folder=True
    ),
}


def legend_for_state(state: SessionState) -> str:
    return _STATE_TO_LEGEND[state]


def control_state_for(state: SessionState, *, has_valid_printer: bool = True) -> ControlState:
    legend = legend_for_state(state)
    base = _TABLE[legend]
    if legend == LEGEND_READY and not has_valid_printer:
        base = replace(base, start=False)
    return base
