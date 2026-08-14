"""Builds a minimal, valid multi-page PDF byte-for-byte at test time, so
integration tests have a real file for `pdfseparate` to split without
depending on any PDF-authoring library. Byte offsets for the xref table are
computed from what was actually written, not hand-calculated, so this stays
correct regardless of how the object bodies change."""

from __future__ import annotations


def build_minimal_pdf(page_count: int) -> bytes:
    if page_count < 1:
        raise ValueError("page_count must be >= 1")

    page_obj_numbers = list(range(3, 3 + page_count))
    kids = " ".join(f"{n} 0 R" for n in page_obj_numbers)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode("ascii"),
    ]
    objects.extend(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> >>"
        for _ in page_obj_numbers
    )

    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]  # index 0 is the free-list head; real object offsets start at index 1

    for i, obj_body in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode("ascii")
        body += obj_body
        body += b"\nendobj\n"

    xref_offset = len(body)
    total_objects = len(objects) + 1

    body += f"xref\n0 {total_objects}\n".encode("ascii")
    body += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        body += f"{offset:010d} 00000 n \n".encode("ascii")

    body += b"trailer\n"
    body += f"<< /Size {total_objects} /Root 1 0 R >>\n".encode("ascii")
    body += b"startxref\n"
    body += f"{xref_offset}\n".encode("ascii")
    body += b"%%EOF"

    return bytes(body)
