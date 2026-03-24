# BOM Extraction Tool

Local Python CLI to extract BOM/CPQ values from blueprint PDFs, attach source citations, export JSON/CSV for review, and generate a filled BOM form PDF.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python3 -m bom_tool.cli \
  --blueprint "66327 - 407 Pine Avenue, Anna Maria, FL, 34216_A1.pdf" \
  --intake "BOM - Intake Form.xlsx" \
  --form "66327 - Phani Bhushan Potu_Bill of Material_(FORM).pdf"
```

Outputs are written to `results/<job_id>/`:
- `extraction.json`
- `review.csv`
- `filled_form.pdf`

## Web UI

```bash
streamlit run src/bom_tool/app.py
```

Opens a browser at `http://localhost:8501` where you can upload files and view results interactively.

## Notes

- The first implementation prioritizes deterministic fields from `PV-4`, `PV-5`, `PV-5.1`, and `PV-6`.
- Fields without reliable extraction are marked `needs_review` with best available citation context.
