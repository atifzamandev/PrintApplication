"""Tools -> Split PDF into Pages... against a real, multi-page PDF split by
the real `pdfseparate` binary. Requires poppler-utils; skipped otherwise —
install it on the target Debian machine with:

    sudo apt install poppler-utils
"""

import shutil

import pytest

from pdf_print_manager.services.pdf_service import PdfService
from tests.pdf_fixtures import build_minimal_pdf

pytestmark = pytest.mark.skipif(
    shutil.which("pdfseparate") is None,
    reason="requires poppler-utils (pdfseparate) on PATH",
)


def test_split_into_folder_creates_one_file_per_page(tmp_path):
    source = tmp_path / "AI article.pdf"
    source.write_bytes(build_minimal_pdf(5))

    service = PdfService()
    destination = service.plan_split_destination(source)
    result = service.split_into_folder(source, destination)

    assert result.page_count == 5
    created = sorted(p.name for p in destination.glob("Page_*.pdf"))
    assert created == [f"Page_{i}.pdf" for i in range(1, 6)]
    assert source.exists()  # original untouched


def test_split_conflict_replace_only_overwrites_generated_pages(tmp_path):
    source = tmp_path / "Invoice_2381.pdf"
    source.write_bytes(build_minimal_pdf(3))

    service = PdfService()
    destination = service.plan_split_destination(source)
    destination.mkdir()
    (destination / "Page_1.pdf").write_bytes(b"stale")
    (destination / "notes.txt").write_text("keep me")

    assert service.destination_has_conflict(destination) is True

    result = service.split_into_folder(source, destination, replace=True)

    assert result.page_count == 3
    assert (destination / "notes.txt").exists()  # untouched, non-generated file
    assert (destination / "Page_1.pdf").read_bytes() != b"stale"


def test_split_conflict_unique_folder_leaves_original_untouched(tmp_path):
    source = tmp_path / "Invoice_2381.pdf"
    source.write_bytes(build_minimal_pdf(2))

    service = PdfService()
    destination = service.plan_split_destination(source)
    destination.mkdir()
    (destination / "Page_1.pdf").write_bytes(b"stale")

    unique = service.unique_destination(destination)
    result = service.split_into_folder(source, unique)

    assert result.output_dir.name == "Invoice_2381_split (1)"
    assert (destination / "Page_1.pdf").read_bytes() == b"stale"  # untouched
