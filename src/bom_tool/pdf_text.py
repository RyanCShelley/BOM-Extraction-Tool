from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from .models import PageText

SHEET_RE = re.compile(r"\bPV-\d+(?:\.\d+)?\b", re.IGNORECASE)
SHEET_LINE_RE = re.compile(r"^\s*(PV-\d+(?:\.\d+)?)\s*$", re.IGNORECASE)


def _detect_sheet_label(text: str) -> str:
    lines = text.splitlines()
    for line in lines[:80]:
        m = SHEET_LINE_RE.match(line)
        if m:
            return m.group(1).upper()
    match = SHEET_RE.search(text)
    return match.group(0).upper() if match else "UNKNOWN"


def load_pdf_pages(pdf_path: Path) -> list[PageText]:
    reader = PdfReader(str(pdf_path))
    pages: list[PageText] = []
    for idx, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(
            PageText(
                page_number=idx,
                text=text,
                sheet_label=_detect_sheet_label(text),
            )
        )
    return pages


def candidate_pages(pages: list[PageText], location_hint: str) -> list[PageText]:
    hint = (location_hint or "").upper()
    labels = []
    for label in ("PV-4", "PV-5.1", "PV-5", "PV-6"):
        if label in hint:
            labels.append(label)
    if not labels:
        return pages
    by_label = [p for p in pages if p.sheet_label in labels]
    if by_label:
        return by_label
    # Fallback text cues when sheet labels are noisy.
    cue_map = {
        "PV-4": "ROOF PLAN",
        "PV-5": "ATTACHMENT DETAIL",
        "PV-5.1": "ATTACHMENT DETAIL",
        "PV-6": "SINGLE LINE DIAGRAM",
    }
    matched = []
    for label in labels:
        cue = cue_map.get(label)
        if not cue:
            continue
        matched.extend([p for p in pages if cue in p.text.upper()])
    return matched or pages
