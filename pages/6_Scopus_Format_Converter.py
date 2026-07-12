"""
Scopus-format Converter (standalone)
====================================
Convert an ALREADY-ENRICHED dataset into Biblioshiny/VOSviewer-ready
Scopus-format CSV — without re-running the enrichment pipeline.

This is the standalone counterpart to the "Also prepare Scopus-format CSV"
button inside Data Enrichment (which stays exactly as it was). It reuses the
SAME conversion logic (export_scopus_csv.convert_row + SCOPUS_COLUMNS +
PROVENANCE_COLUMNS), so a file converted here is byte-for-byte the format the
in-flow button produces.

Input: a Jarvis Scholar enriched output .xlsx/.csv (the file the extractor
gives you, with columns like TITLE, Authors, Author_Affiliation_Map, DOI,
Citations, MeSH Terms, etc.).
"""
import csv
import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_scopus_csv import convert_row, SCOPUS_COLUMNS, PROVENANCE_COLUMNS
from bibliometric_pipeline.branding import THEME_CSS, scopus_input_template_bytes
from bibliometric_pipeline.ui_helpers import read_tabular_upload

st.set_page_config(page_title="Jarvis Scholar - Scopus Converter", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.title("Scopus-format converter")
st.caption(
    "Turn an already-enriched dataset into a Scopus-format CSV for Biblioshiny "
    "(bibliometrix) / VOSviewer — no re-enrichment. Same output as the button "
    "inside Data Enrichment, but for a file you already have."
)

# The enriched columns convert_row reads from — used to sanity-check the upload.
_EXPECTED_HINT_COLS = ["TITLE", "Authors", "DOI", "YEAR", "Journal"]
_ALL_OUT_COLS = SCOPUS_COLUMNS + PROVENANCE_COLUMNS

with st.expander("What file does this expect?", expanded=False):
    st.markdown(
        "Upload a **Jarvis Scholar enriched output** — the `.xlsx` the Data "
        "Enrichment tool produces (or an older `bibliometric_output_*.xlsx`). "
        "It should contain the pipeline's own columns such as `TITLE`, "
        "`Authors`, `Author_Affiliation_Map`, `DOI`, `Citations`, `MeSH Terms`, "
        "`EID`, etc.\n\n"
        "The output is the standard 44-column Scopus CSV header plus a few "
        "trailing `Jarvis_*` provenance columns (which Scopus/VOSviewer parsers "
        "ignore). Rows with a blank `EID` are kept, but note Biblioshiny itself "
        "drops blank-EID rows on import."
    )
    st.download_button(
        "⬇ Download blank Scopus-converter input template (.xlsx)",
        data=scopus_input_template_bytes(),
        file_name="jarvis_scholar_scopus_input_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        help="The columns this tool reads, with one worked example row. Normally "
             "you'd just use the enrichment output directly — this is for building "
             "an enriched-style dataset by hand.",
    )

uploaded = st.file_uploader(
    "Upload enriched dataset (.xlsx / .csv)", type=["xlsx", "xls", "csv"]
)

if uploaded is None:
    st.info("Upload a Jarvis Scholar enriched output file to convert.")
    st.stop()

try:
    df = read_tabular_upload(uploaded)
except Exception as e:
    st.error(f"Could not read that file: {e}")
    st.stop()

# Guard: warn (don't hard-fail) if this doesn't look like an enriched output.
present_hints = [c for c in _EXPECTED_HINT_COLS if c in df.columns]
if not present_hints:
    st.error(
        "This doesn't look like a Jarvis Scholar enriched output — none of the "
        f"expected columns {_EXPECTED_HINT_COLS} were found. Found: "
        f"{list(df.columns)[:12]}{' …' if len(df.columns) > 12 else ''}.\n\n"
        "If you have a raw title/DOI list, run **Data Enrichment** first, then "
        "convert its output here."
    )
    st.stop()

st.write(f"**{len(df)}** rows to convert.")

# Rows the reviewer rejected (or that were de-duplicated) shouldn't feed a
# downstream bibliometric analysis. Exclude them by default; the count is
# reported so nothing disappears silently.
drop_rejected = st.checkbox(
    "Exclude rows rejected in manual review / marked duplicate", value=True,
    help="Rows with Match Status 'Rejected (manual review)' or a 'Duplicate' "
         "Dedup Status are left out of the Scopus output.",
)

if st.button("Convert to Scopus format", type="primary"):
    work = df.copy()
    n_excluded = 0
    if drop_rejected:
        mask_keep = pd.Series(True, index=work.index)
        if "Match Status" in work.columns:
            mask_keep &= ~work["Match Status"].astype(str).str.startswith("Rejected")
        if "Dedup Status" in work.columns:
            mask_keep &= ~work["Dedup Status"].astype(str).str.startswith("Duplicate")
        n_excluded = int((~mask_keep).sum())
        work = work[mask_keep]

    # Convert every row through the SAME function the in-flow export uses.
    out_rows = [convert_row(rec) for rec in work.to_dict("records")]
    out_df = pd.DataFrame(out_rows)
    for c in _ALL_OUT_COLS:
        if c not in out_df.columns:
            out_df[c] = ""
    out_df = out_df[_ALL_OUT_COLS]

    # Write with the exact same encoding/quoting as export_scopus_csv.main().
    buf = io.StringIO()
    out_df.to_csv(buf, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    csv_bytes = buf.getvalue().encode("utf-8-sig")

    n_blank_eid = int((out_df["EID"].astype(str).str.strip() == "").sum())
    st.success(f"Converted {len(out_df)} rows to Scopus format.")
    m = st.columns(4)
    m[0].metric("Rows", len(out_df))
    m[1].metric("Excluded", n_excluded)
    m[2].metric("Scopus columns", len(SCOPUS_COLUMNS))
    m[3].metric("Blank-EID rows", n_blank_eid)
    if n_excluded:
        st.caption(f"{n_excluded} row(s) excluded (rejected in review / duplicate).")
    if n_blank_eid:
        st.caption(
            f"{n_blank_eid} row(s) have a blank EID — Biblioshiny will drop those "
            "on import. That's expected for records the pipeline couldn't key."
        )

    st.subheader("Preview")
    st.dataframe(out_df.head(30), use_container_width=True, hide_index=True)

    stem = os.path.splitext(uploaded.name)[0] + "_scopus_format"
    st.download_button(
        "⬇ Download Scopus-format CSV",
        data=csv_bytes,
        file_name=f"{stem}.csv",
        mime="text/csv",
    )
