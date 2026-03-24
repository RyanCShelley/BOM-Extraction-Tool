"""Streamlit web UI for the BOM Extraction Tool."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure the src directory is on the import path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Project root where bundled intake/form files live
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

import pandas as pd
import streamlit as st

from bom_tool.extractors import extract_fields
from bom_tool.form_fill import fill_form_pdf
from bom_tool.intake import load_intake_fields
from bom_tool.output import write_outputs
from bom_tool.pdf_text import load_pdf_pages


def run_pipeline(blueprint_file, intake_path: Path, form_path: Path):
    """Run the full extraction pipeline on uploaded blueprint + bundled files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        bp_path = tmp / "blueprint.pdf"
        bp_path.write_bytes(blueprint_file.getvalue())

        fields = load_intake_fields(intake_path)
        pages = load_pdf_pages(bp_path)
        results = extract_fields(fields, pages)

        output_dir = tmp / "output"
        output_dir.mkdir()
        json_path, csv_path = write_outputs(results, output_dir)
        filled_path = fill_form_pdf(form_path, results, output_dir / "filled_form.pdf")

        json_bytes = json_path.read_bytes()
        csv_bytes = csv_path.read_bytes()
        filled_pdf_bytes = filled_path.read_bytes()

    return results, json_bytes, csv_bytes, filled_pdf_bytes


def main():
    st.set_page_config(page_title="BOM Extraction Tool", layout="wide")
    st.title("BOM Extraction Tool")
    st.caption(
        "Upload a blueprint PDF to extract BOM fields with source citations."
    )

    # Bundled default files
    default_intake = PROJECT_ROOT / "BOM - Intake Form.xlsx"
    default_form = PROJECT_ROOT / "66327 - Phani Bhushan Potu_Bill of Material_(FORM).pdf"

    # --- File Upload ---
    blueprint = st.file_uploader("Blueprint PDF", type=["pdf"])

    # --- Run Button ---
    if st.button("Run Extraction", disabled=blueprint is None, type="primary"):
        if not default_intake.exists():
            st.error(f"Intake file not found: {default_intake.name}")
            return
        if not default_form.exists():
            st.error(f"Form file not found: {default_form.name}")
            return

        with st.spinner("Extracting fields from blueprint..."):
            try:
                results, json_bytes, csv_bytes, filled_pdf_bytes = run_pipeline(
                    blueprint, default_intake, default_form
                )
                st.session_state.results = results
                st.session_state.json_bytes = json_bytes
                st.session_state.csv_bytes = csv_bytes
                st.session_state.filled_pdf_bytes = filled_pdf_bytes
                st.session_state.run_complete = True
            except ValueError as e:
                st.error(f"Input error: {e}")
                st.session_state.run_complete = False
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                st.exception(e)
                st.session_state.run_complete = False

    # --- Results Display ---
    if st.session_state.get("run_complete"):
        results = st.session_state.results

        st.divider()

        # Summary metrics
        total = len(results)
        ok_count = sum(1 for r in results if r.status == "ok")
        review_count = total - ok_count

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Fields", total)
        m2.metric("Extracted", ok_count)
        m3.metric("Needs Review", review_count)

        # Results table
        rows = [r.to_dict() for r in results]
        df = pd.DataFrame(rows)
        display_df = df[
            [
                "field_name",
                "section",
                "value",
                "confidence",
                "status",
                "source_page",
                "sheet",
                "quote",
                "extractor_name",
            ]
        ].copy()

        st.dataframe(
            display_df,
            column_config={
                "confidence": st.column_config.ProgressColumn(
                    "Confidence",
                    min_value=0.0,
                    max_value=1.0,
                    format="%.0f%%",
                ),
            },
            use_container_width=True,
            hide_index=True,
        )

        # Download buttons
        st.subheader("Downloads")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button(
                "Download JSON",
                data=st.session_state.json_bytes,
                file_name="extraction.json",
                mime="application/json",
            )
        with d2:
            st.download_button(
                "Download CSV",
                data=st.session_state.csv_bytes,
                file_name="review.csv",
                mime="text/csv",
            )
        with d3:
            st.download_button(
                "Download Filled Form PDF",
                data=st.session_state.filled_pdf_bytes,
                file_name="filled_form.pdf",
                mime="application/pdf",
            )


if __name__ == "__main__":
    main()
