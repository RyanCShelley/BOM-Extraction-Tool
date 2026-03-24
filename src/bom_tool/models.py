from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class IntakeField:
    section: str
    field_number: str
    field_name: str
    field_type: str
    allowed_values: str
    source_process: str
    data_point_location: str

    @property
    def field_id(self) -> str:
        return f"{self.section}|{self.field_number}|{self.field_name}"


@dataclass
class PageText:
    page_number: int
    text: str
    sheet_label: str


@dataclass
class Citation:
    page_number: int
    sheet_label: str
    matched_text: str
    extractor_name: str
    confidence: float


@dataclass
class ExtractionResult:
    field_id: str
    section: str
    field_number: str
    field_name: str
    value: Any
    status: str
    citation: Citation

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = self.citation.confidence
        data["source_page"] = self.citation.page_number
        data["sheet"] = self.citation.sheet_label
        data["quote"] = self.citation.matched_text
        data["extractor_name"] = self.citation.extractor_name
        return data
