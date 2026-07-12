"""
Merge Sheets
============
Dashboard tool: join two spreadsheets on one or more matched columns. The
join columns don't have to share a name between the two files. Exact match,
with optional case-insensitive / whitespace-trimmed key comparison.
"""
import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.sheet_merge import merge_sheets, JOIN_TYPES
from bibliometric_pipeline.ui_helpers import download_buttons
from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, how_to_use, brand_footer

st.set_page_config(page_title="Jarvis Scholar - Merge Sheets", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()
st.title("Merge two sheets")
st.caption(
    "Upload two spreadsheets, pick the column(s) to match on (names can differ), "
    "and get one merged sheet back, plus a summary of what didn't match."
)


def _load_with_sheet_picker(uploaded, side):
    """Read an upload; if it's a multi-sheet Excel, let the user pick a tab."""
    name = (uploaded.name or "").lower()
    data = uploaded.getvalue()
    if name.endswith((".csv",)):
        return pd.read_csv(io.BytesIO(data))
    if name.endswith((".tsv", ".tab")):
        return pd.read_csv(io.BytesIO(data), sep="\t")
    xl = pd.ExcelFile(io.BytesIO(data))
    sheet = xl.sheet_names[0]
    if len(xl.sheet_names) > 1:
        sheet = st.selectbox(f"Sheet ({side})", xl.sheet_names, key=f"sheet_{side}")
    return xl.parse(sheet)


c1, c2 = st.columns(2)
with c1:
    up_a = st.file_uploader("Sheet A (.xlsx / .csv)", type=["xlsx", "xls", "csv", "tsv"], key="ma")
with c2:
    up_b = st.file_uploader("Sheet B (.xlsx / .csv)", type=["xlsx", "xls", "csv", "tsv"], key="mb")

if not (up_a and up_b):
    st.info("Upload both sheets to begin.")
    st.stop()

try:
    df_a = _load_with_sheet_picker(up_a, "A")
    df_b = _load_with_sheet_picker(up_b, "B")
except Exception as e:
    st.error(f"Could not read a file: {e}")
    st.stop()

st.write(f"Sheet A: **{len(df_a)}** rows × {len(df_a.columns)} cols · "
         f"Sheet B: **{len(df_b)}** rows × {len(df_b.columns)} cols")

n_keys = st.number_input("Number of column(s) to match on", min_value=1, max_value=5, value=1)

left_on, right_on = [], []
for i in range(int(n_keys)):
    k1, k2 = st.columns(2)
    left_on.append(k1.selectbox(f"Sheet A — join column {i + 1}", list(df_a.columns), key=f"lon_{i}"))
    right_on.append(k2.selectbox(f"Sheet B — join column {i + 1}", list(df_b.columns), key=f"ron_{i}"))

o1, o2, o3 = st.columns(3)
how = o1.selectbox("Join type", JOIN_TYPES, index=0,
                   help="inner = only matched rows · left = all of A · right = all of B · outer = everything")
case_insensitive = o2.checkbox("Ignore letter case", value=True)
trim = o3.checkbox("Ignore surrounding spaces", value=True)

if st.button("Merge", type="primary"):
    _loader = st.empty()
    _loader.markdown(reactor_loader_html("JARVIS is merging your sheets…"), unsafe_allow_html=True)
    try:
        with st.spinner("Joining rows…"):
            merged, summary = merge_sheets(
                df_a, df_b, left_on=left_on, right_on=right_on, how=how,
                case_insensitive=case_insensitive, trim=trim,
            )
    except Exception as e:
        _loader.empty()
        st.error(f"Merge failed: {e}")
        st.stop()
    _loader.empty()

    st.success(f"Merged: {summary['rows_out']} rows out ({summary['matched_pairs']} matched pairs).")
    m = st.columns(4)
    m[0].metric("Rows out", summary["rows_out"])
    m[1].metric("Matched pairs", summary["matched_pairs"])
    m[2].metric("A rows unmatched", summary["left_rows_unmatched"])
    m[3].metric("B rows unmatched", summary["right_rows_unmatched"])

    if how == "inner" and summary["matched_pairs"] == 0:
        st.warning(
            "Nothing matched. Check you picked the right columns — and if the "
            "keys look the same by eye, try toggling 'Ignore letter case' / "
            "'Ignore surrounding spaces' above."
        )

    st.subheader("Preview")
    st.dataframe(merged.head(50), use_container_width=True, hide_index=True)
    download_buttons(merged, stem="merged_sheets", key_prefix="merge", sheet_name="Merged")
    brand_footer(note=f"{summary['rows_out']:,} rows merged")

st.markdown("---")
how_to_use([
    ("📤", "Upload two sheets",
     "Sheet A and Sheet B (.xlsx/.csv). For multi-tab Excel files you’ll be asked which tab to use."),
    ("🔗", "Pick the column(s) to match on",
     "Choose one or more join columns from each sheet — the names don’t have to be the same between A and B."),
    ("⚙️", "Choose the join type",
     "inner = only matched rows · left = all of A · right = all of B · outer = everything. Toggle case/space matching if keys look the same but don’t join."),
    ("▶️", "Merge",
     "Click ‘Merge’. The loader shows while rows are joined; you’ll get a summary of matched and unmatched rows."),
    ("⬇️", "Download the merged sheet",
     "Preview the result and download as CSV or Excel."),
])
