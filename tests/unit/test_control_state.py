"""The button-enablement table — framework-free, so it's tested without
importing PySide6 at all. Mirrors spec section 8's table plus the two
confirmed refinements from the design review."""

from pdf_print_manager.models import SessionState
from pdf_print_manager.ui.control_state import control_state_for


def test_ready_state_allows_start_and_editing():
    cs = control_state_for(SessionState.IDLE, has_valid_printer=True)
    assert cs.start is True
    assert cs.edit_settings is True
    assert cs.pause is False
    assert cs.resume is False
    assert cs.cancel is False


def test_ready_state_blocks_start_without_a_valid_printer():
    cs = control_state_for(SessionState.IDLE, has_valid_printer=False)
    assert cs.start is False
    # The printer field itself must stay editable so the user can fix it.
    assert cs.edit_settings is True


def test_running_state_allows_pause_and_cancel_only():
    for state in (
        SessionState.SUBMITTING,
        SessionState.WAITING_FOR_CUPS,
        SessionState.WAITING_DELAY,
    ):
        cs = control_state_for(state)
        assert cs.start is False
        assert cs.pause is True
        assert cs.resume is False
        assert cs.cancel is True
        assert cs.edit_settings is False


def test_paused_state_allows_resume_and_cancel_only():
    cs = control_state_for(SessionState.PAUSED)
    assert cs.pause is False
    assert cs.resume is True
    assert cs.cancel is True


def test_cancelling_state_disables_cancel_per_confirmed_design():
    cs = control_state_for(SessionState.CANCELLING)
    assert cs.start is False
    assert cs.pause is False
    assert cs.resume is False
    assert cs.cancel is False
    assert cs.edit_settings is False


def test_finished_states_allow_open_folder_and_restart():
    for state in (
        SessionState.COMPLETED,
        SessionState.COMPLETED_WITH_WARNING,
        SessionState.FAILED,
        SessionState.CANCELLED,
    ):
        cs = control_state_for(state)
        assert cs.start is True
        assert cs.edit_settings is True
        assert cs.open_folder is True
        assert cs.cancel is False
