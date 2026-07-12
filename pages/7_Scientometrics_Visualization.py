"""
Scientometrics Visualization
============================
Biblioshiny / VOSviewer-style analysis of an enriched bibliometric dataset,
rendered in-app. Phase 1: dataset overview, missing-data, annual production &
citations, Bradford's law, most-relevant sources, sources by h-index,
top-cited records, most locally-cited references.

(Network maps — co-authorship, institutional, country, keyword co-occurrence,
bibliographic coupling — and the strategic thematic map arrive in later
phases.)
"""
import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline import scientometrics as sci
from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, how_to_use
from bibliometric_pipeline.ui_helpers import download_buttons, read_tabular_upload

st.set_page_config(page_title="Jarvis Scholar - Scientometrics", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.title("Scientometrics visualization")
st.caption(
    "Upload an enriched dataset and get Biblioshiny-style tables and charts. "
    "Phase 1: overview, trends, sources, citation structure. Network maps and "
    "thematic analysis are coming next."
)

_CYAN = "#0e7f9c"
_INDIGO = "#4f46e5"


def _bar(data, x, y, *, horizontal=False, color=_CYAN, height=320):
    enc_x, enc_y = (alt.X(f"{y}:Q", title=y), alt.Y(f"{x}:N", sort="-x", title=None)) if horizontal \
        else (alt.X(f"{x}:O", title=x), alt.Y(f"{y}:Q", title=y))
    return alt.Chart(data).mark_bar(color=color, cornerRadius=3).encode(
        x=enc_x, y=enc_y, tooltip=list(data.columns)
    ).properties(height=height)


with st.expander("What file does this expect?", expanded=False):
    st.markdown(
        "Upload a **Jarvis Scholar enriched dataset** (.xlsx/.csv) — the output "
        "of Data Enrichment, ideally after de-duplication. The tool auto-detects "
        "columns like journal, year, citations, authors, references, countries, "
        "and keywords, so most enriched sheets work as-is."
    )

uploaded = st.file_uploader("Upload enriched dataset (.xlsx / .csv)", type=["xlsx", "xls", "csv"])
if uploaded is None:
    st.info("Upload an enriched dataset to generate the analysis.")
    how_to_use([
        ("🛰", "Enrich & de-duplicate first",
         "Run Data Enrichment, then (optionally) Fuzzy Title Match to remove duplicates, so the metrics are clean."),
        ("📤", "Upload the enriched sheet",
         "Drop the .xlsx/.csv here. Columns are auto-detected — journal, year, citations, authors, references, keywords."),
        ("⚙️", "Choose options",
         "Turn on ICMR mode for ICMR-specific breakdowns (coming in a later phase). Set how many rows each ‘top N’ table shows."),
        ("📊", "Read the tables & charts",
         "Dataset overview, missing-data, annual trends, Bradford’s law, leading sources, h-index, and top-cited records render below."),
        ("⬇️", "Download any table",
         "Each table has CSV/Excel download buttons for your manuscript or further analysis."),
    ])
    st.stop()

try:
    df = read_tabular_upload(uploaded)
except Exception as e:
    st.error(f"Could not read that file: {e}")
    st.stop()

c1, c2 = st.columns([3, 1])
c1.write(f"**{len(df):,}** records · **{len(df.columns)}** columns loaded.")
icmr_mode = c2.toggle("ICMR mode", value=False,
                      help="ICMR-specific breakdowns (institute/division tables) — added in a later phase.")
top_n = st.slider("Rows to show in ‘top N’ tables", 5, 30, 15)

_loader = st.empty()
_loader.markdown(reactor_loader_html("JARVIS is computing scientometrics…"), unsafe_allow_html=True)
with st.spinner("Crunching the corpus…"):
    overview = sci.dataset_overview(df)
    missing = sci.missing_data(df)
    annual_prod = sci.annual_production(df)
    annual_cit = sci.annual_citations(df)
    sources = sci.most_relevant_sources(df, top_n)
    bradford = sci.bradford(df)
    hindex = sci.sources_h_index(df, top_n)
    topcited = sci.top_cited(df, top_n)
    localcited = sci.most_local_cited_references(df, top_n)
_loader.empty()

if icmr_mode:
    st.info("ICMR mode is on. ICMR-specific institute/division tables arrive in a later phase; "
            "the generic analysis below already runs on your ICMR dataset.", icon="🏛")

# --- Dataset overview ---
st.header("1 · Dataset overview")
st.table(overview)
download_buttons(overview, stem="dataset_overview", key_prefix="ov", sheet_name="Overview")

# --- Missing data ---
st.header("2 · Missing data")
st.dataframe(missing, use_container_width=True, hide_index=True)
download_buttons(missing, stem="missing_data", key_prefix="md", sheet_name="Missing")

# --- Annual production & citations ---
st.header("3 · Annual production & citations")
cc1, cc2 = st.columns(2)
with cc1:
    st.subheader("Documents per year")
    if not annual_prod.empty:
        st.altair_chart(_bar(annual_prod, "Year", "Documents"), use_container_width=True)
    st.dataframe(annual_prod, use_container_width=True, hide_index=True)
with cc2:
    st.subheader("Total citations per year")
    if not annual_cit.empty:
        line = alt.Chart(annual_cit).mark_line(point=True, color=_INDIGO).encode(
            x=alt.X("Year:O"), y=alt.Y("Total Citations:Q"),
            tooltip=list(annual_cit.columns)).properties(height=320)
        st.altair_chart(line, use_container_width=True)
    st.dataframe(annual_cit, use_container_width=True, hide_index=True)

# --- Bradford's law ---
st.header("4 · Bradford's law of scattering")
if not bradford.empty:
    zone_sum = bradford.groupby("Zone").agg(
        Journals=("Source", "nunique"), Documents=("Documents", "sum")).reset_index()
    zc1, zc2 = st.columns([1, 2])
    with zc1:
        st.caption("Zone 1 = the core journals carrying ~1/3 of all documents.")
        st.dataframe(zone_sum, use_container_width=True, hide_index=True)
    with zc2:
        curve = alt.Chart(bradford).mark_line(color=_CYAN).encode(
            x=alt.X("Rank:Q", title="Source rank"),
            y=alt.Y("Cumulative:Q", title="Cumulative documents"),
            tooltip=["Rank", "Source", "Documents", "Zone"]).properties(height=300)
        st.altair_chart(curve, use_container_width=True)
    download_buttons(bradford, stem="bradford_law", key_prefix="br", sheet_name="Bradford")

# --- Most relevant sources ---
st.header("5 · Most relevant sources")
if not sources.empty:
    st.altair_chart(_bar(sources, "Source", "Documents", horizontal=True,
                         height=28 * len(sources) + 40), use_container_width=True)
    st.dataframe(sources, use_container_width=True, hide_index=True)
    download_buttons(sources, stem="most_relevant_sources", key_prefix="src", sheet_name="Sources")

# --- Sources local impact by h-index ---
st.header("6 · Sources — local impact by h-index")
if not hindex.empty:
    st.altair_chart(_bar(hindex, "Source", "h-index", horizontal=True, color=_INDIGO,
                         height=28 * len(hindex) + 40), use_container_width=True)
    st.dataframe(hindex, use_container_width=True, hide_index=True)
    download_buttons(hindex, stem="sources_h_index", key_prefix="hx", sheet_name="h-index")

# --- Top-cited records ---
st.header("7 · Top-cited individual records")
if not topcited.empty:
    st.dataframe(topcited, use_container_width=True, hide_index=True)
    download_buttons(topcited, stem="top_cited_records", key_prefix="tc", sheet_name="Top cited")

# --- Most locally-cited references ---
st.header("8 · Most locally-cited references")
st.caption("How often each reference is cited by documents *within this dataset*.")
if not localcited.empty:
    st.dataframe(localcited, use_container_width=True, hide_index=True)
    download_buttons(localcited, stem="local_cited_references", key_prefix="lc", sheet_name="Local cited")

st.markdown("---")
st.caption("Phase 1 of Scientometrics Visualization. Coming next: co-authorship / institutional / "
           "country / keyword co-occurrence maps, keyword density, strategic thematic map, and "
           "bibliographic coupling.")
