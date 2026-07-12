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

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline import scientometrics as sci
from bibliometric_pipeline import charts
from bibliometric_pipeline.branding import (
    THEME_CSS, reactor_loader_html, how_to_use, brand_footer,
)
from bibliometric_pipeline.ui_helpers import download_buttons, read_tabular_upload

st.set_page_config(page_title="Jarvis Scholar - Scientometrics", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
st.title("Scientometrics visualization")
st.caption(
    "Upload an enriched dataset and get Biblioshiny-style tables and charts. "
    "Phase 1: overview, trends, sources, citation structure. Network maps and "
    "thematic analysis are coming next."
)

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

def _safe(fn, default):
    """Run one metric; if it fails on an unusual file, degrade gracefully
    (empty result + a note) instead of crashing the whole page."""
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001
        return default, str(e)


_EMPTY = pd.DataFrame()
_loader = st.empty()
_loader.markdown(reactor_loader_html("JARVIS is computing scientometrics…"), unsafe_allow_html=True)
_errs = {}
with st.spinner("Crunching the corpus…"):
    overview, _errs["Dataset overview"] = _safe(lambda: sci.dataset_overview(df), _EMPTY)
    missing, _errs["Missing data"] = _safe(lambda: sci.missing_data(df), _EMPTY)
    annual_prod, _errs["Annual production"] = _safe(lambda: sci.annual_production(df), _EMPTY)
    annual_cit, _errs["Annual citations"] = _safe(lambda: sci.annual_citations(df), _EMPTY)
    sources, _errs["Most relevant sources"] = _safe(lambda: sci.most_relevant_sources(df, top_n), _EMPTY)
    bradford, _errs["Bradford"] = _safe(lambda: sci.bradford(df), _EMPTY)
    hindex, _errs["h-index"] = _safe(lambda: sci.sources_h_index(df, top_n), _EMPTY)
    topcited, _errs["Top cited"] = _safe(lambda: sci.top_cited(df, top_n), _EMPTY)
    localcited, _errs["Local cited"] = _safe(lambda: sci.most_local_cited_references(df, top_n), _EMPTY)
_loader.empty()

_failed = {k: v for k, v in _errs.items() if v}
if _failed:
    st.warning("Some sections could not be computed for this file (the rest are shown below): "
               + "; ".join(f"{k}" for k in _failed))

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
        charts.render_chart(
            charts.vbar(annual_prod["Year"].tolist(), annual_prod["Documents"].tolist(),
                        title="Annual scientific production", ylabel="Documents"),
            "annual_production", "annprod")
    st.dataframe(annual_prod, use_container_width=True, hide_index=True)
with cc2:
    st.subheader("Total citations per year")
    if not annual_cit.empty:
        charts.render_chart(
            charts.line(annual_cit["Year"].tolist(), annual_cit["Total Citations"].tolist(),
                        title="Annual total citations", ylabel="Citations"),
            "annual_citations", "anncit")
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
        charts.render_chart(
            charts.bradford_curve(bradford["Rank"].tolist(), bradford["Cumulative"].tolist(),
                                  zones=bradford["Zone"].tolist()),
            "bradford_law", "brad")
    download_buttons(bradford, stem="bradford_law", key_prefix="br", sheet_name="Bradford")

# --- Most relevant sources ---
st.header("5 · Most relevant sources")
if not sources.empty:
    charts.render_chart(
        charts.hbar(sources["Source"].tolist(), sources["Documents"].tolist(),
                    title="Most relevant sources", xlabel="Documents"),
        "most_relevant_sources", "src")
    st.dataframe(sources, use_container_width=True, hide_index=True)
    download_buttons(sources, stem="most_relevant_sources", key_prefix="src", sheet_name="Sources")

# --- Sources local impact by h-index ---
st.header("6 · Sources — local impact by h-index")
if not hindex.empty:
    charts.render_chart(
        charts.hbar(hindex["Source"].tolist(), hindex["h-index"].tolist(),
                    title="Sources by local h-index", xlabel="h-index"),
        "sources_h_index", "hx")
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

brand_footer(note=f"{len(df):,} records analysed")
st.markdown("---")
st.caption("Phase 1 of Scientometrics Visualization. Coming next: co-authorship / institutional / "
           "country / keyword co-occurrence maps, keyword density, strategic thematic map, and "
           "bibliographic coupling.")
