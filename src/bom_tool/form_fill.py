from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import ExtractionResult


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def fill_form_pdf(form_pdf_path: Path, results: list[ExtractionResult], output_pdf_path: Path) -> Path:
    reader = PdfReader(str(form_pdf_path))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    fields = reader.get_fields() or {}
    if not fields:
        with output_pdf_path.open("wb") as f:
            writer.write(f)
        return output_pdf_path

    name_to_value = {_norm(r.field_name): "" if r.value is None else str(r.value) for r in results}

    updates: dict[str, str] = {}
    for field_name in fields.keys():
        n = _norm(field_name)
        if n in name_to_value:
            updates[field_name] = name_to_value[n]
            continue
        for key, value in name_to_value.items():
            if key and (key in n or n in key):
                updates[field_name] = value
                break

    for i, page in enumerate(writer.pages):
        writer.update_page_form_field_values(page, updates)

    with output_pdf_path.open("wb") as f:
        writer.write(f)
    return output_pdf_path
