"""
Convert Citations to CSV/Excel
==============================
Dashboard tool: turn a PubMed MEDLINE (.txt / .nbib) export or an RIS (.ris)
export into a clean spreadsheet. Output leads with the pipeline-ready
`Sno` / `Clean Title` / `DOI` columns, so the result can be fed straight
into the main Jarvis Scholar extractor with no manual remapping.

This page shares one upload -> parse -> preview -> download shell between
both formats (they are structurally identical); only the parser differs.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.converters import medline_to_dataframe, ris_to_dataframe
from bibliometric_pipeline.ui_helpers import download_buttons

st.set_page_config(page_title="Jarvis Scholar - Convert Citations", layout="wide")
st.title("Convert citations to CSV / Excel")
st.caption(
    "Upload a PubMed (MEDLINE .txt/.nbib) or RIS (.ris) export and get back a "
    "clean spreadsheet. The output starts with `Sno`, `Clean Title`, `DOI` so "
    "you can drop it straight into the main extractor."
)


def _detect_format(filename: str, head: str) -> str:
    name = (filename or "").lower()
    if name.endswith(".ris"):
        return "RIS"
    if name.endswith(".nbib"):
        return "PubMed (MEDLINE)"
    # Content sniff: RIS starts with "TY  - "; MEDLINE has "PMID- "
    if "TY  - " in head[:400]:
        return "RIS"
    if "PMID-" in head[:400] or "PMID -" in head[:400]:
        return "PubMed (MEDLINE)"
    return "PubMed (MEDLINE)"


uploaded = st.file_uploader(
    "Upload a citation export",
    type=["txt", "nbib", "ris"],
    help="PubMed 'Send to > File > Format: PubMed' gives a MEDLINE .txt. "
         "Most databases/reference managers export RIS.",
)

if uploaded is None:
    st.info("Upload a .txt / .nbib (PubMed MEDLINE) or .ris (RIS) file to begin.")
    st.stop()

raw = uploaded.getvalue()
try:
    head_text = raw.decode("utf-8", errors="replace")
except Exception:
    head_text = ""

detected = _detect_format(uploaded.name, head_text)
fmt = st.radio(
    "Format",
    ["PubMed (MEDLINE)", "RIS"],
    index=0 if detected.startswith("PubMed") else 1,
    horizontal=True,
    help=f"Auto-detected: {detected}. Override here if that's wrong.",
)

try:
    if fmt == "RIS":
        df = ris_to_dataframe(raw)
    else:
        df = medline_to_dataframe(raw)
except Exception as e:
    st.error(f"Could not parse that file as {fmt}: {e}")
    st.stop()

if df.empty:
    st.warning(
        "No records were found. Double-check the format selector above — a "
        "PubMed file must be the *MEDLINE* export (not 'Summary' or 'Abstract'), "
        "and an RIS file must contain 'TY  -' / 'ER  -' tagged records."
    )
    st.stop()

n_missing_doi = int((df["DOI"].fillna("").astype(str).str.strip() == "").sum())
n_missing_title = int((df["Clean Title"].fillna("").astype(str).str.strip() == "").sum())

st.success(f"Parsed {len(df)} record(s).")
cols = st.columns(3)
cols[0].metric("Records", len(df))
cols[1].metric("Missing DOI", n_missing_doi)
cols[2].metric("Missing title", n_missing_title)

if n_missing_title:
    st.warning(
        f"{n_missing_title} record(s) have no title — those rows won't match "
        "well in the enrichment pipeline unless they have a DOI."
    )

st.subheader("Preview")
st.dataframe(df.head(50), use_container_width=True, hide_index=True)

stem = os.path.splitext(uploaded.name)[0] + "_converted"
download_buttons(df, stem=stem, key_prefix="convert", sheet_name="Converted")

st.caption(
    "Tip: the first three columns (`Sno`, `Clean Title`, `DOI`) are exactly "
    "what the main extractor needs — download the Excel and upload it there to enrich."
)
