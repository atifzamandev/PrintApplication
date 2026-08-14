"""ArchiveService: collision-safe moves into PrintedCompleted, and the
fingerprint check that guards against archiving a file that changed mid-session."""

import pytest

from pdf_print_manager.errors import ArchiveError
from pdf_print_manager.services.archive_service import ArchiveService


def test_archive_moves_file_into_printed_completed(sample_pdf):
    service = ArchiveService()
    destination = service.archive(sample_pdf)

    assert destination.parent.name == "PrintedCompleted"
    assert destination.name == sample_pdf.name
    assert destination.exists()
    assert not sample_pdf.exists()


def test_archive_never_overwrites_existing_file(tmp_path, sample_pdf):
    service = ArchiveService()
    archive_dir = sample_pdf.parent / "PrintedCompleted"
    archive_dir.mkdir()
    (archive_dir / sample_pdf.name).write_bytes(b"already here")

    destination = service.archive(sample_pdf)

    assert destination.name == "Invoice_2381 (1).pdf"
    assert destination.exists()
    assert (archive_dir / sample_pdf.name).exists()  # original archived copy untouched


def test_archive_increments_past_multiple_collisions(sample_pdf):
    service = ArchiveService()
    archive_dir = sample_pdf.parent / "PrintedCompleted"
    archive_dir.mkdir()
    (archive_dir / sample_pdf.name).write_bytes(b"first")
    (archive_dir / "Invoice_2381 (1).pdf").write_bytes(b"second")

    destination = service.archive(sample_pdf)
    assert destination.name == "Invoice_2381 (2).pdf"


def test_archive_raises_if_source_missing(tmp_path):
    service = ArchiveService()
    with pytest.raises(ArchiveError):
        service.archive(tmp_path / "gone.pdf")


def test_archive_raises_if_source_changed_since_fingerprint(sample_pdf):
    service = ArchiveService()
    fingerprint = service.stat_fingerprint(sample_pdf)

    sample_pdf.write_bytes(b"%PDF-1.4\nmodified content that changes size\n")

    with pytest.raises(ArchiveError):
        service.archive(sample_pdf, expected_fingerprint=fingerprint)
    assert sample_pdf.exists()  # never moved


def test_archive_succeeds_when_fingerprint_unchanged(sample_pdf):
    service = ArchiveService()
    fingerprint = service.stat_fingerprint(sample_pdf)

    destination = service.archive(sample_pdf, expected_fingerprint=fingerprint)
    assert destination.exists()
