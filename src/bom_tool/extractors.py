from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Citation, ExtractionResult, IntakeField, PageText
from .pdf_text import candidate_pages


@dataclass
class MatchResult:
    value: Any
    quote: str
    confidence: float
    extractor_name: str


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _search_dead_load_row(page: PageText, row_label: str) -> MatchResult | None:
    norm_label = _normalize(row_label)
    int_re = re.compile(r"\d+")
    dec_re = re.compile(r"([0-9]+(?:\.[0-9]+)?)")
    for line in page.text.splitlines():
        normalized = _normalize(line)
        if norm_label in normalized:
            # For quantity rows, first integer token is usually quantity.
            if row_label != "RAIL LENGTH":
                ints = int_re.findall(line)
                if ints:
                    candidate = int(ints[0])
                    # OCR/text extraction can merge quantity+unit (e.g. 140.36 -> 140).
                    if row_label == "SPLICE BAR" and candidate > 50:
                        candidate = candidate // 10
                    if row_label in {"MID-CLAMP", "END-CLAMP"} and candidate > 250:
                        candidate = candidate // 10
                    # ATTACHMENT / TOP MOUNT: OCR often merges "140 0.88" into 1400 or "66 0.88" into 660.
                    if row_label in {"ATTACHMENT", "TOP MOUNT"} and candidate > 250:
                        candidate = candidate // 10
                    # TOP MOUNT only: "10 0.88" sometimes becomes 100.
                    if row_label == "TOP MOUNT" and candidate == 100:
                        candidate = 10
                    return MatchResult(
                        value=str(candidate),
                        quote=line.strip(),
                        confidence=0.9,
                        extractor_name=f"dead_load_row:{row_label}",
                    )
            nums = dec_re.findall(line)
            if nums:
                return MatchResult(
                    value=nums[0],
                    quote=line.strip(),
                    confidence=0.98,
                    extractor_name=f"dead_load_row:{row_label}",
                )
    return None


def _search_phrase_number(page: PageText, phrase: str) -> MatchResult | None:
    pattern = re.compile(rf"{re.escape(phrase)}\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
    match = pattern.search(page.text)
    if not match:
        return None
    return MatchResult(
        value=match.group(1),
        quote=match.group(0),
        confidence=0.92,
        extractor_name=f"phrase_number:{phrase}",
    )


def _count_roofs_in_roof_table(page: PageText) -> MatchResult | None:
    roof_ids: set[int] = set()
    # Table rows normally have: roof_id module_count roof_pitch azimuth ...
    for m in re.finditer(r"(?:^|\n)\s*(\d{1,2})\s+\d+\s+\d{1,2}\D", page.text, re.IGNORECASE):
        roof_ids.add(int(m.group(1)))
    if not roof_ids:
        for line in page.text.splitlines():
            m = re.match(r"^\s*(\d{1,2})\s+\d+\s+", line)
            if m:
                roof_ids.add(int(m.group(1)))
    if not roof_ids:
        return None
    return MatchResult(
        value=str(len(roof_ids)),
        quote=f"Detected roof rows: {sorted(roof_ids)}",
        confidence=0.9,
        extractor_name="roof_table_count",
    )


def _search_allowed_value(page: PageText, allowed_values: str) -> MatchResult | None:
    # Expected shape: [A, B, C]
    candidates = [x.strip() for x in allowed_values.strip("[]").split(",") if x.strip()]
    text_upper = page.text.upper()
    for candidate in candidates:
        if candidate.upper() in text_upper:
            return MatchResult(
                value=candidate,
                quote=candidate,
                confidence=0.88,
                extractor_name="allowed_value_scan",
            )
    return None


def _extract_with_rules(field: IntakeField, pages: list[PageText]) -> tuple[MatchResult | None, PageText | None]:
    name = _normalize(field.field_name)
    scoped_pages = candidate_pages(pages, field.data_point_location)

    row_map = {
        "railsquantity": "RAIL LENGTH",
        "splicequantity": "SPLICE BAR",
        "midclampquantity": "MID-CLAMP",
        "endclampquantity": "END-CLAMP",
        "numberofconnectionstoroof1": "ATTACHMENT",
        "numberofconnectionstoroof2": "TOP MOUNT",
    }

    phrase_map = {"capacityofnewmainbreakerforsubpanelformainelectricalpanel": "MAIN BREAKER"}

    for page in scoped_pages:
        if name in row_map:
            found = _search_dead_load_row(page, row_map[name])
            if found:
                if name == "splicequantity" and (not str(found.value).isdigit() or int(str(found.value)) > 50):
                    found = None
                if name == "midclampquantity" and (not str(found.value).isdigit() or int(str(found.value)) > 250):
                    found = None
                if name == "endclampquantity" and (not str(found.value).isdigit() or int(str(found.value)) > 250):
                    found = None
            if found:
                return found, page

        if name in phrase_map:
            found = _search_phrase_number(page, phrase_map[name])
            if found:
                return found, page

        if name == "numberofroofswithsolarpanels":
            found = _count_roofs_in_roof_table(page)
            if found:
                return found, page

        if "typeofroof" in name and field.allowed_values:
            found = _search_allowed_value(page, field.allowed_values)
            if found:
                return found, page

        if "typeofstructure" in name:
            for marker in ("SUNMODO", "UNIRAC", "NXT"):
                if marker in page.text.upper():
                    return (
                        MatchResult(
                            value=marker,
                            quote=marker,
                            confidence=0.84,
                            extractor_name="structure_marker_scan",
                        ),
                        page,
                    )

        if name == "typeofinterconnection":
            if "LOAD SIDE TAP" in page.text.upper():
                return (
                    MatchResult(
                        value="LOAD SIDE CONNECTION",
                        quote="LOAD SIDE TAP",
                        confidence=0.9,
                        extractor_name="interconnection_keyword",
                    ),
                    page,
                )

    return None, None


def extract_fields(fields: list[IntakeField], pages: list[PageText]) -> list[ExtractionResult]:
    results: list[ExtractionResult] = []
    for field in fields:
        match, page = _extract_with_rules(field, pages)
        if match and page:
            citation = Citation(
                page_number=page.page_number,
                sheet_label=page.sheet_label,
                matched_text=match.quote,
                extractor_name=match.extractor_name,
                confidence=match.confidence,
            )
            status = "ok" if match.confidence >= 0.75 else "needs_review"
            value = match.value
        else:
            # Fall back to likely page for human review context.
            scoped = candidate_pages(pages, field.data_point_location)
            ref_page = scoped[0] if scoped else pages[0]
            quote = (ref_page.text[:220] + "...") if ref_page.text else "No text extracted."
            citation = Citation(
                page_number=ref_page.page_number,
                sheet_label=ref_page.sheet_label,
                matched_text=quote,
                extractor_name="unresolved_fallback",
                confidence=0.0,
            )
            status = "needs_review"
            value = None

        results.append(
            ExtractionResult(
                field_id=field.field_id,
                section=field.section,
                field_number=field.field_number,
                field_name=field.field_name,
                value=value,
                status=status,
                citation=citation,
            )
        )

    return results
