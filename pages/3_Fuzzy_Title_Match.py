"""
Fuzzy Title Match
=================
Dashboard tool: fuzzy-match titles without running the full enrichment
pipeline. Two modes:
  - Compare two lists (cross-match): best match in list B for each title in A.
  - Find duplicates in one list (self-dedup): near-duplicate pairs within one list.

Reuses the same hardened matching primitives as the main pipeline
(text_utils.fuzzy_score, including the length-guard fix that stops a short
generic candidate from falsely matching a much longer unrelated title).
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.fuzzy_tools import cross_match, self_dedup
from bibliometric_pipeline.ui_helpers import download_buttons, read_tabular_upload
from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, how_to_use, brand_footer, fuzzy_titles_template_bytes, fuzzy_preview

st.set_page_config(page_title="Jarvis Scholar - Fuzzy Title Match", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()
st.title("Fuzzy title match")
st.caption(
    "Match titles by similarity — no OpenAlex/PubMed/Crossref lookups. "
    "Great for reconciling two title lists or finding duplicates in one."
)

with st.expander("📋 Required format — download a blank template", expanded=False):
    st.markdown(
        "Each file just needs a column of titles (a `Title` column works out of the box; "
        "any column can be picked after upload). Use **one** file to find duplicates, or "
        "**two** files to compare lists."
    )
    st.download_button(
        "⬇ Download blank titles template (.xlsx)",
        data=fuzzy_titles_template_bytes(),
        file_name="jarvis_scholar_titles_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _pick_title_column(df, key, label="title column"):
    guess = 0
    for i, c in enumerate(df.columns):
        if str(c).strip().lower() in ("clean title", "title", "titles"):
            guess = i
            break
    return st.selectbox(f"Which column holds the {label}?", list(df.columns),
                        index=guess, key=key)


mode = st.radio(
    "Mode",
    ["Compare two lists", "Find duplicates in one list"],
    horizontal=True,
)

threshold = st.slider(
    "Match threshold (similarity score)", min_value=50, max_value=100, value=85,
    help="Higher = stricter. 85 matches the main pipeline's auto-accept level; "
         "75 is its 'needs review' floor.",
)

if mode == "Compare two lists":
    c1, c2 = st.columns(2)
    with c1:
        up_a = st.file_uploader("List A (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="a")
    with c2:
        up_b = st.file_uploader("List B (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="b")

    if not (up_a and up_b):
        st.info("Upload both lists to compare. Each title in A gets its single best match from B.")
        st.stop()

    try:
        df_a = read_tabular_upload(up_a)
        df_b = read_tabular_upload(up_b)
    except Exception as e:
        st.error(f"Could not read a file: {e}")
        st.stop()

    col_a = _pick_title_column(df_a, "col_a", "titles in List A")
    col_b = _pick_title_column(df_b, "col_b", "titles in List B")

    if st.button("Run match", type="primary"):
        _loader = st.empty()
        _loader.markdown(reactor_loader_html("JARVIS is matching titles…"), unsafe_allow_html=True)
        with st.spinner("Comparing every title in A against List B…"):
            result = cross_match(df_a[col_a].tolist(), df_b[col_b].tolist(), threshold=threshold)
        _loader.empty()
        n_matched = int((result["Matched"] == "Yes").sum())
        st.success(f"{n_matched} of {len(result)} titles in List A matched at ≥ {threshold}.")
        m = st.columns(3)
        m[0].metric("List A titles", len(df_a))
        m[1].metric("Matched", n_matched)
        m[2].metric("Unmatched", len(result) - n_matched)
        st.dataframe(result, use_container_width=True, hide_index=True)
        download_buttons(result, stem="fuzzy_cross_match", key_prefix="xmatch", sheet_name="Matches")

else:  # self-dedup
    up = st.file_uploader("Title list (.xlsx / .csv)", type=["xlsx", "xls", "csv"], key="dedup")
    if not up:
        st.info("Upload one list. Every pair of near-duplicate titles above the threshold is reported.")
        st.stop()

    try:
        df = read_tabular_upload(up)
    except Exception as e:
        st.error(f"Could not read that file: {e}")
        st.stop()

    col = _pick_title_column(df, "col_dedup")

    if st.button("Find duplicates", type="primary"):
        _loader = st.empty()
        _loader.markdown(reactor_loader_html("JARVIS is scanning for duplicates…"), unsafe_allow_html=True)
        with st.spinner("Comparing every pair of titles… (this can take a moment on long lists)"):
            result = self_dedup(df[col].tolist(), threshold=threshold)
        _loader.empty()
        if result.empty:
            st.success(f"No near-duplicate pairs found at ≥ {threshold}.")
        else:
            n_titles = df[col].astype(str).str.strip().ne("").sum()
            st.success(f"Found {len(result)} near-duplicate pair(s) among {n_titles} titles.")
            st.dataframe(result, use_container_width=True, hide_index=True)
            download_buttons(result, stem="fuzzy_duplicates", key_prefix="dedup", sheet_name="Duplicates")

brand_footer()
st.markdown("---")
how_to_use([
    ("🔀", "Pick a mode",
     "‘Compare two lists’ finds the best match in list B for each title in A. "
     "‘Find duplicates in one list’ reports near-duplicate pairs within a single list."),
    ("📤", "Upload your list(s)",
     "Upload one .xlsx/.csv (dedup) or two (compare). Each just needs a column of titles."),
    ("🎚", "Set the match threshold",
     "Higher = stricter. 85 matches the pipeline’s auto-accept level; 75 is its ‘needs review’ floor."),
    ("▶️", "Run it",
     "Click the button. The JARVIS loader shows while it compares — long lists take a few seconds."),
    ("⬇️", "Review & download",
     "Check the matched/duplicate pairs and scores, then download as CSV or Excel."),
], preview_image=fuzzy_preview(),
   preview_caption="A simple Title column is all each file needs (download the template above)")
