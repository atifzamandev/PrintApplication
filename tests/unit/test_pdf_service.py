"""PdfService's pure logic: numeric page sorting, filename sanitizing, split
destination planning, and conflict/uniqueness handling. None of this touches
the real `pdfseparate` binary."""

from pathlib import Path

import pytest

from pdf_print_manager.errors import ValidationError
from pdf_print_manager.services.pdf_service import PdfService, page_sort_key, sanitize_stem


def test_page_sort_key_orders_numerically_not_lexically():
    paths = [Path("Page_10.pdf"), Path("Page_2.pdf"), Path("Page_1.pdf")]
    ordered = sorted(paths, key=page_sort_key)
    assert [p.name for p in ordered] == ["Page_1.pdf", "Page_2.pdf", "Page_10.pdf"]


def test_sanitize_stem_replaces_invalid_characters():
    assert sanitize_stem('weird:name/with*bad?chars') == "weird_name_with_bad_chars"


def test_sanitize_stem_falls_back_when_empty():
    assert sanitize_stem("   ") == "untitled"


def test_plan_split_destination_appends_split_suffix(tmp_path):
    service = PdfService()
    source = tmp_path / "AI article.pdf"
    destination = service.plan_split_destination(source)
    assert destination == tmp_path / "AI article_split"


def test_destination_has_conflict_true_only_when_pages_present(tmp_path):
    service = PdfService()
    destination = tmp_path / "Invoice_2381_split"
    assert service.destination_has_conflict(destination) is False

    destination.mkdir()
    assert service.destination_has_conflict(destination) is False

    (destination / "Page_1.pdf").write_bytes(b"x")
    assert service.destination_has_conflict(destination) is True


def test_unique_destination_increments(tmp_path):
    service = PdfService()
    destination = tmp_path / "Invoice_2381_split"
    destination.mkdir()
    (tmp_path / "Invoice_2381_split (1)").mkdir()  # sibling, not a child

    unique = service.unique_destination(destination)
    assert unique == tmp_path / "Invoice_2381_split (2)"


def test_validate_rejects_missing_file(tmp_path):
    service = PdfService()
    with pytest.raises(ValidationError):
        service.validate(tmp_path / "missing.pdf")


def test_validate_rejects_non_pdf_extension(tmp_path):
    service = PdfService()
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(ValidationError):
        service.validate(path)


def test_validate_accepts_readable_pdf(sample_pdf):
    service = PdfService()
    service.validate(sample_pdf)  # should not raise
