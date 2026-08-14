"""CupsClient class behaviour with an injected fake `subprocess.run`-alike
runner — still no real system commands involved."""

import subprocess

from pdf_print_manager.models import CupsJobState
from pdf_print_manager.services.cups_client import CupsClient


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class ScriptedRunner:
    """Maps a command's first two args (e.g. ("lpstat", "-W")) to canned
    stdout, so tests can script exactly what each probe should see."""

    def __init__(self):
        self.responses = {}
        self.calls = []

    def set_response(self, *args, stdout="", returncode=0):
        self.responses[tuple(args)] = (stdout, returncode)

    def __call__(self, args, capture_output=True, text=True, check=False):
        self.calls.append(list(args))
        key = tuple(args[:2]) if len(args) >= 2 else tuple(args)
        stdout, returncode = self.responses.get(key, ("", 0))
        return _completed(stdout=stdout, returncode=returncode)


def test_get_job_state_returns_processing_while_in_not_completed():
    runner = ScriptedRunner()
    runner.set_response("lpstat", "-W", stdout="HP-1022-42   oliver   ...\n")
    client = CupsClient(runner=runner)

    assert client.get_job_state("HP-1022-42") is CupsJobState.PROCESSING


def test_get_job_state_falls_through_to_completed_listing():
    runner = ScriptedRunner()
    # "-W not-completed" never actually distinguishes by window text in this
    # fake since we key on the first two args; instead we emulate the real
    # sequence of distinct calls CupsClient makes.
    calls = iter(
        [
            ("", 0),  # not-completed: empty, job already left the active queue
            ("HP-1022-42   oliver   ...\n", 0),  # completed: found here
        ]
    )

    def runner_fn(args, capture_output=True, text=True, check=False):
        stdout, returncode = next(calls)
        return _completed(stdout=stdout, returncode=returncode)

    client = CupsClient(runner=runner_fn)
    assert client.get_job_state("HP-1022-42") is CupsJobState.COMPLETED


def test_get_job_state_returns_unknown_when_job_not_found_anywhere():
    def runner_fn(args, capture_output=True, text=True, check=False):
        return _completed(stdout="", returncode=0)

    client = CupsClient(runner=runner_fn)
    assert client.get_job_state("HP-1022-99") is CupsJobState.UNKNOWN


def test_submit_job_parses_job_id():
    def runner_fn(args, capture_output=True, text=True, check=False):
        assert args[0] == "lp"
        return _completed(stdout="request id is HP-1022-42 (1 file(s))\n")

    client = CupsClient(runner=runner_fn)
    job_id = client.submit_job("HP-1022", __file__)
    assert job_id == "HP-1022-42"


def test_cancel_job_runs_cancel_with_job_id():
    seen = {}

    def runner_fn(args, capture_output=True, text=True, check=False):
        seen["args"] = args
        return _completed(returncode=0)

    client = CupsClient(runner=runner_fn)
    assert client.cancel_job("HP-1022-42") is True
    assert seen["args"] == ["cancel", "HP-1022-42"]
