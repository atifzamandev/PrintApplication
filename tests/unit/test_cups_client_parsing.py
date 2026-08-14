"""Pure parsing-function tests for cups_client.py — no subprocess involved."""

from pdf_print_manager.errors import CupsCommandError
from pdf_print_manager.services.cups_client import (
    parse_default_printer,
    parse_job_id,
    parse_job_ids,
    parse_printers,
)

import pytest


def test_parse_job_id_extracts_id_from_lp_output():
    stdout = "request id is HP-LaserJet-1022-42 (1 file(s))\n"
    assert parse_job_id(stdout) == "HP-LaserJet-1022-42"


def test_parse_job_id_raises_when_unparsable():
    with pytest.raises(CupsCommandError):
        parse_job_id("some unrelated output\n")


def test_parse_job_ids_from_not_completed_listing():
    stdout = (
        "HP-LaserJet-1022-42   oliver    20480   Fri 14 Aug 2026 09:05:00 AM UTC\n"
        "HP-LaserJet-1022-43   oliver    20480   Fri 14 Aug 2026 09:05:05 AM UTC\n"
    )
    assert parse_job_ids(stdout) == {"HP-LaserJet-1022-42", "HP-LaserJet-1022-43"}


def test_parse_job_ids_ignores_non_job_chatter():
    assert parse_job_ids("no entries\n") == set()
    assert parse_job_ids("") == set()


def test_parse_printers_combines_enabled_and_accepting_state():
    p_stdout = (
        "printer HP_LaserJet_1022 is idle.  enabled since Fri 14 Aug 2026 09:00:00 AM UTC\n"
        "printer Brother_HL2270DW disabled since Fri 14 Aug 2026 08:00:00 AM UTC -\n"
        "\treason unknown\n"
    )
    a_stdout = (
        "HP_LaserJet_1022 accepting requests since Fri 14 Aug 2026 09:00:00 AM UTC\n"
        "Brother_HL2270DW not accepting requests since Fri 14 Aug 2026 08:00:00 AM UTC\n"
    )
    printers = parse_printers(p_stdout, a_stdout)
    by_name = {p.name: p for p in printers}

    assert by_name["HP_LaserJet_1022"].enabled is True
    assert by_name["HP_LaserJet_1022"].accepting_jobs is True
    assert by_name["HP_LaserJet_1022"].is_usable is True

    assert by_name["Brother_HL2270DW"].enabled is False
    assert by_name["Brother_HL2270DW"].accepting_jobs is False
    assert by_name["Brother_HL2270DW"].is_usable is False


def test_parse_printers_defaults_accepting_true_when_lpstat_a_missing():
    p_stdout = "printer HP_LaserJet_1022 is idle.  enabled since ...\n"
    printers = parse_printers(p_stdout, "")
    assert printers[0].accepting_jobs is True


def test_parse_default_printer():
    assert parse_default_printer("system default destination: HP_LaserJet_1022\n") == "HP_LaserJet_1022"
    assert parse_default_printer("no system default destination\n") is None
