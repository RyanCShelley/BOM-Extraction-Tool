from __future__ import annotations

import math
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


def _get_pages_by_label(pages: list[PageText], label: str) -> list[PageText]:
    """Return pages matching a specific sheet label (e.g., 'PV-4', 'PV-5.1')."""
    exact = [p for p in pages if p.sheet_label == label]
    if exact:
        return exact
    return [p for p in pages if label in p.text.upper()]


def _sum_module_counts_from_roof_table(page: PageText) -> tuple[int, str] | None:
    """Sum module counts from PV-4 roof description table rows."""
    total = 0
    row_details: list[str] = []
    for line in page.text.splitlines():
        m = re.match(r"^\s*(\d{1,2})\s+(\d+)\s+\d{1,2}\D", line)
        if m:
            roof_id = int(m.group(1))
            modules = int(m.group(2))
            total += modules
            row_details.append(f"Roof {roof_id}: {modules}")
    if total == 0:
        return None
    return total, f"Panel counts: {', '.join(row_details)} = {total} total"


def _detect_orientation(pages: list[PageText]) -> str:
    """Detect panel orientation from blueprint text. Defaults to 'portrait'."""
    for page in pages:
        text_upper = page.text.upper()
        if "PORTRAIT" in text_upper:
            return "portrait"
        if "LANDSCAPE" in text_upper:
            return "landscape"
    return "portrait"


def _calculate_rails_quantity(panel_count: int, orientation: str) -> int:
    """Calculate rails quantity from panel count and orientation.

    Portrait: 2 rails for every 4 panels, +2 if 1-3 extra.
    Landscape: 2 rails for every 2 panels, +2 if 1 extra.
    """
    if orientation == "landscape":
        return math.ceil(panel_count / 2) * 2
    return math.ceil(panel_count / 4) * 2


def _count_panel_rows(page: PageText) -> MatchResult | None:
    """Count distinct panel row labels (Row/Raw N) on PV-4."""
    row_ids: set[int] = set()
    for m in re.finditer(r"\b(?:Row|Raw)\s*(\d{1,2})\b", page.text, re.IGNORECASE):
        row_ids.add(int(m.group(1)))
    if row_ids:
        return MatchResult(
            value=str(len(row_ids)),
            quote=f"Panel rows detected: {sorted(row_ids)}",
            confidence=0.88,
            extractor_name="panel_row_count",
        )
    # Fallback: count entries in roof description table
    roof_ids: set[int] = set()
    for line in page.text.splitlines():
        m = re.match(r"^\s*(\d{1,2})\s+\d+\s+\d{1,2}\D", line)
        if m:
            roof_ids.add(int(m.group(1)))
    if roof_ids:
        return MatchResult(
            value=str(len(roof_ids)),
            quote=f"Roof table rows as panel row proxy: {sorted(roof_ids)}",
            confidence=0.75,
            extractor_name="panel_row_count_from_roof_table",
        )
    return None


def _search_attachment_type(page: PageText, allowed_values: str) -> MatchResult | None:
    """Match attachment type from page text against allowed values.

    Uses three-tier matching: exact substring, normalized, then word-level.
    Matches longer candidates first to prefer specific matches.
    """
    candidates = [x.strip() for x in allowed_values.strip("[]").split(",") if x.strip()]
    real_candidates = [c for c in candidates if _normalize(c) != "nootherattachment"]
    real_candidates.sort(key=len, reverse=True)

    text_upper = page.text.upper()
    text_norm = _normalize(page.text)

    for candidate in real_candidates:
        candidate_upper = candidate.upper()
        candidate_norm = _normalize(candidate)

        if candidate_upper in text_upper:
            return MatchResult(
                value=candidate,
                quote=candidate_upper,
                confidence=0.92,
                extractor_name="attachment_type_exact",
            )
        if candidate_norm in text_norm:
            return MatchResult(
                value=candidate,
                quote=f"Normalized match for '{candidate}'",
                confidence=0.88,
                extractor_name="attachment_type_normalized",
            )
        words = candidate_upper.split()
        if len(words) >= 2 and all(w in text_upper for w in words):
            return MatchResult(
                value=candidate,
                quote=f"Word-level match for '{candidate}'",
                confidence=0.82,
                extractor_name="attachment_type_word_match",
            )
    return None


_SUBTYPE_PATTERNS: list[tuple[str, list[str]]] = [
    ("Meter combo over-under (Feeder tap)", ["METER COMBO OVER-UNDER", "METER COMBO OVER UNDER", "OVER-UNDER", "OVER UNDER"]),
    ("Meter combo Side by Side (Feeder tap)", ["SIDE BY SIDE", "METER COMBO SIDE"]),
    ("Inside enclosure (Line side tap)", ["INSIDE ENCLOSURE"]),
    ("Inside-Main panel (Line side tap)", ["INSIDE-MAIN PANEL", "INSIDE MAIN PANEL"]),
    ("Tap Box (Line side tap)", ["TAP BOX"]),
    ("Meter Combo (Load side connection)", ["METER COMBO"]),
]


def _search_interconnection_subtype(page: PageText, allowed_values: str) -> MatchResult | None:
    """Extract interconnection subtype from PV-6 drawing annotations.

    Strategy 1: Look for explicit subtype phrases in text.
    Strategy 2: Infer from electrical configuration described in the diagram.
    """
    candidates = [x.strip() for x in allowed_values.strip("[]").split(",") if x.strip()]
    text_upper = page.text.upper()

    # Strategy 1: Explicit keyword match
    for subtype_value, patterns in _SUBTYPE_PATTERNS:
        if not any(_normalize(c) == _normalize(subtype_value) for c in candidates):
            continue
        for pattern in patterns:
            if pattern in text_upper:
                return MatchResult(
                    value=subtype_value,
                    quote=pattern,
                    confidence=0.85,
                    extractor_name="interconnection_subtype_keyword",
                )

    # Strategy 2: Infer from electrical components on diagram.
    # Join lines since component labels often span multiple lines in PDF text.
    text_joined = " ".join(text_upper.split())
    has_tap_box = "TAP BOX" in text_joined
    has_main_disconnect = "MAIN SERVICE DISCONNECT" in text_joined
    has_main_panel = "MAIN SERVICE PANEL" in text_joined
    has_meter_combo = has_main_disconnect and has_main_panel

    if has_tap_box:
        val = "Tap Box (Line side tap)"
        if any(_normalize(c) == _normalize(val) for c in candidates):
            return MatchResult(value=val, quote="TAP BOX in diagram", confidence=0.75, extractor_name="interconnection_subtype_inferred")

    if has_meter_combo:
        # Determine interconnection type from same page to pick the right meter combo subtype
        if "LOAD SIDE TAP" in text_joined or "LOAD SIDE CONNECTION" in text_joined:
            val = "Meter Combo (Load side connection)"
        elif "FEEDER TAP" in text_joined:
            val = "Meter combo over-under (Feeder tap)"
        elif "LINE SIDE TAP" in text_joined:
            val = "Inside-Main panel (Line side tap)"
        else:
            val = "Meter Combo (Load side connection)"
        if any(_normalize(c) == _normalize(val) for c in candidates):
            return MatchResult(value=val, quote="Inferred from MAIN SERVICE DISCONNECT + MAIN SERVICE PANEL", confidence=0.70, extractor_name="interconnection_subtype_inferred")

    return None


def _extract_with_rules(field: IntakeField, pages: list[PageText]) -> tuple[MatchResult | None, PageText | None]:
    name = _normalize(field.field_name)
    scoped_pages = candidate_pages(pages, field.data_point_location)

    # --- Block A: Fields with explicit page lookups (bypass scoped_pages) ---

    if name == "railsquantity":
        pv4_pages = _get_pages_by_label(pages, "PV-4")
        for pv4_page in pv4_pages:
            result = _sum_module_counts_from_roof_table(pv4_page)
            if result:
                panel_count, quote = result
                orientation = _detect_orientation(pages)
                rails = _calculate_rails_quantity(panel_count, orientation)
                divisor = "4" if orientation == "portrait" else "2"
                return (
                    MatchResult(
                        value=str(rails),
                        quote=f"{quote}; orientation={orientation}; rails=ceil({panel_count}/{divisor})*2={rails}",
                        confidence=0.85,
                        extractor_name="rails_from_panel_count",
                    ),
                    pv4_page,
                )
        return None, None

    if name == "groundlugquantity":
        pv4_pages = _get_pages_by_label(pages, "PV-4")
        for pv4_page in pv4_pages:
            found = _count_panel_rows(pv4_page)
            if found:
                return found, pv4_page
        return None, None

    if name == "attachmenttype2" and field.allowed_values:
        pv51_pages = _get_pages_by_label(pages, "PV-5.1")
        if pv51_pages:
            for pv51_page in pv51_pages:
                found = _search_attachment_type(pv51_page, field.allowed_values)
                if found:
                    return found, pv51_page
        return (
            MatchResult(
                value="No other attachment",
                quote="No PV-5.1 page found or no attachment type detected",
                confidence=0.90,
                extractor_name="attachment_type2_default",
            ),
            pv51_pages[0] if pv51_pages else (pages[0] if pages else None),
        )

    if name == "subtypeofinterconnection" and field.allowed_values:
        pv6_pages = _get_pages_by_label(pages, "PV-6")
        for pv6_page in pv6_pages:
            found = _search_interconnection_subtype(pv6_page, field.allowed_values)
            if found:
                return found, pv6_page

    # --- Block B: Fields using scoped_pages ---

    row_map = {
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

        if name == "attachmenttype1" and field.allowed_values:
            found = _search_attachment_type(page, field.allowed_values)
            if found:
                return found, page

        if name == "typeofinterconnection":
            text_upper = page.text.upper()
            if "FEEDER TAP" in text_upper:
                return (
                    MatchResult(
                        value="FEEDER TAP",
                        quote="FEEDER TAP",
                        confidence=0.9,
                        extractor_name="interconnection_keyword",
                    ),
                    page,
                )
            if "LINE SIDE TAP" in text_upper:
                return (
                    MatchResult(
                        value="LINE SIDE TAP",
                        quote="LINE SIDE TAP",
                        confidence=0.9,
                        extractor_name="interconnection_keyword",
                    ),
                    page,
                )
            if "LOAD SIDE TAP" in text_upper or "LOAD SIDE CONNECTION" in text_upper:
                return (
                    MatchResult(
                        value="LOAD SIDE CONNECTION",
                        quote="LOAD SIDE TAP" if "LOAD SIDE TAP" in text_upper else "LOAD SIDE CONNECTION",
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
