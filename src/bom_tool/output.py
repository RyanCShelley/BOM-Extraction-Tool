from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import ExtractionResult


def write_outputs(results: list[ExtractionResult], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "extraction.json"
    csv_path = output_dir / "review.csv"

    rows = [r.to_dict() for r in results]
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    headers = [
        "field_id",
        "field_name",
        "value",
        "confidence",
        "source_page",
        "sheet",
        "quote",
        "status",
        "extractor_name",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "field_id": row["field_id"],
                    "field_name": row["field_name"],
                    "value": row["value"],
                    "confidence": row["confidence"],
                    "source_page": row["source_page"],
                    "sheet": row["sheet"],
                    "quote": row["quote"],
                    "status": row["status"],
                    "extractor_name": row["extractor_name"],
                }
            )

    return json_path, csv_path
