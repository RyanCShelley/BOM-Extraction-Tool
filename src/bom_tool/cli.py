from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from .extractors import extract_fields
from .form_fill import fill_form_pdf
from .intake import load_intake_fields
from .output import write_outputs
from .pdf_text import load_pdf_pages


def _job_dir(root: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / stamp


def main() -> None:
    parser = argparse.ArgumentParser(description="BOM extraction and form-fill pipeline")
    parser.add_argument("--blueprint", required=True, type=Path, help="Blueprint PDF path")
    parser.add_argument("--intake", required=True, type=Path, help="Intake XLSX path")
    parser.add_argument("--form", required=True, type=Path, help="Form PDF path")
    parser.add_argument("--output-root", default=Path("results"), type=Path, help="Output directory root")
    args = parser.parse_args()

    output_dir = _job_dir(args.output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    fields = load_intake_fields(args.intake)
    pages = load_pdf_pages(args.blueprint)
    results = extract_fields(fields, pages)

    json_path, csv_path = write_outputs(results, output_dir)
    filled_path = fill_form_pdf(args.form, results, output_dir / "filled_form.pdf")

    print(f"Wrote: {json_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {filled_path}")


if __name__ == "__main__":
    main()
