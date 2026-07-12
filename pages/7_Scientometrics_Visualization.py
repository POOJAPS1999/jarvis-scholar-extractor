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
import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline import scientometrics as sci
from bibliometric_pipeline import charts
from bibliometric_pipeline import networks as nw
from bibliometric_pipeline import icmr_tables as it
from bibliometric_pipeline.branding import (
    THEME_CSS, reactor_loader_html, how_to_use, brand_footer,
)
from bibliometric_pipeline.ui_helpers import download_buttons, read_tabular_upload

st.set_page_config(page_title="Jarvis Scholar - Scientometrics", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()
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
                      help="Adds ICMR-specific tables (institute benchmarking, divisions, leadership, "
                           "mandate fidelity, international partners) — needs an ICMR-tagged, enriched dataset.")
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
    themes, _errs["Thematic map"] = _safe(lambda: nw.thematic_map(df, min_occurrence=5), _EMPTY)
    funders, _errs["Grants"] = _safe(lambda: sci.top_funders(df, top_n), _EMPTY)
_loader.empty()

_failed = {k: v for k, v in _errs.items() if v}
if _failed:
    st.warning("Some sections could not be computed for this file (the rest are shown below): "
               + "; ".join(f"{k}" for k in _failed))

if icmr_mode and not it.has_required(df):
    st.warning(
        "ICMR mode is on, but this dataset can't produce the ICMR tables yet — it needs an ICMR "
        "**institute column** (run the ICMR Institute Tagger, or enrich with ICMR mode) **and** a "
        "`Citations` column. The generic analysis below still runs.", icon="🏛")

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

# --- Network maps (Phase 2) ---
st.header("9 · Network maps (VOSviewer-style)")
st.caption("Interactive collaboration & co-occurrence maps. Pick a map, tune it, and generate. "
           "Zoom/pan/hover in the chart; use the 📷 icon (or the PNG button) to save, or download "
           "the VOSviewer .map/.net files to open in the real VOSviewer.")

_MAPS = [
    "Co-authorship (first / last / corresponding)",
    "Institutional collaboration",
    "Country collaboration",
    "Country collaboration (excl. India)",
    "Keyword co-occurrence",
    "Keyword density",
    "Bibliographic coupling",
]
map_choice = st.selectbox("Map type", _MAPS, key="mapchoice")
mc1, mc2 = st.columns(2)
top_n = mc1.slider("Nodes to show (top by weight)", 20, 150, 60, key="topn")
min_occ = min_shared = 5
if map_choice.startswith("Keyword"):
    min_occ = mc2.slider("Min keyword occurrences", 3, 30, 5, key="minocc")
elif map_choice == "Bibliographic coupling":
    min_shared = mc2.slider("Min shared references", 2, 10, 2, key="minshared")

if st.button("Generate map", type="primary", key="genmap"):
    from bibliometric_pipeline import networks as nw, network_viz as nv
    import zipfile
    _l = st.empty()
    _l.markdown(reactor_loader_html("JARVIS is mapping the network…"), unsafe_allow_html=True)
    try:
        with st.spinner("Building the network…"):
            weight_name = "Documents"
            density = False
            if map_choice.startswith("Co-authorship"):
                items, edges, extra = nw.author_collab(df)
            elif map_choice == "Institutional collaboration":
                items, edges, extra = nw.institution_collab(df, icmr_mode=icmr_mode)
            elif map_choice == "Country collaboration":
                items, edges, extra = nw.country_collab(df, exclude_india=False)
            elif map_choice == "Country collaboration (excl. India)":
                items, edges, extra = nw.country_collab(df, exclude_india=True)
            elif map_choice == "Keyword co-occurrence":
                items, edges, extra = nw.keyword_cooccurrence(df, min_occ); weight_name = "Occurrences"
            elif map_choice == "Keyword density":
                items, edges, extra = nw.keyword_cooccurrence(df, min_occ); weight_name = "Occurrences"; density = True
            else:  # Bibliographic coupling
                items, edges, extra = nw.bibliographic_coupling(df, min_shared); weight_name = "References"
            fig = (nv.density_figure(items, edges, extra, title=map_choice, top_n=max(top_n, 80))
                   if density else
                   nv.network_figure(items, edges, extra, title=map_choice, top_n=top_n, weight_name=weight_name))
        _l.empty()
        st.caption(f"{len(items):,} total nodes · {len(edges):,} links · showing top {top_n} by weight.")
        st.plotly_chart(fig, use_container_width=True,
                        config={"displaylogo": False,
                                "toImageButtonOptions": {"format": "png", "filename": "jarvis_network",
                                                         "scale": 2}})
        dl1, dl2 = st.columns(2)
        if not density:
            with dl1:
                st.download_button("⬇ Download PNG", key="netpng",
                    data=nv.network_png(items, edges, extra, title=map_choice, top_n=top_n, weight_name=weight_name),
                    file_name="jarvis_network.png", mime="image/png")
        # VOSviewer .map + .net as a zip
        mb, nb = nw.vosviewer_bytes(items, edges, extra)
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("network_map.txt", mb)
            z.writestr("network_network.txt", nb)
        with dl2:
            st.download_button("⬇ VOSviewer files (.map + .net)", data=zbuf.getvalue(),
                               file_name="jarvis_vosviewer_network.zip", mime="application/zip", key="netvos")
    except Exception as e:
        _l.empty()
        st.error(f"Could not build this map: {e}")

# --- Strategic thematic map (Phase 3) ---
st.header("10 · Strategic thematic map")
st.caption("Keyword themes placed by relevance (centrality) and development (density). "
           "Upper-right = motor themes; upper-left = niche; lower-right = basic/transversal; "
           "lower-left = emerging or declining.")
if themes is None or themes.empty:
    st.info("Not enough co-occurring keywords to build themes (needs a larger corpus, or lower the "
            "keyword-occurrence threshold). Works well on full datasets.", icon="ℹ️")
else:
    charts.render_chart(charts.thematic_map(themes), "strategic_thematic_map", "themap")
    st.dataframe(themes, use_container_width=True, hide_index=True)
    download_buttons(themes, stem="strategic_thematic_map", key_prefix="tm", sheet_name="Themes")

# --- Grants / funding (Phase 3) ---
st.header("11 · Funding sources")
if funders is None or funders.empty:
    st.info("No Grants/Funding column found (or it's empty) in this dataset.", icon="ℹ️")
else:
    charts.render_chart(
        charts.hbar(funders["Funder"].tolist(), funders["Papers"].tolist(),
                    title="Leading funders", xlabel="Papers"),
        "top_funders", "fund")
    st.dataframe(funders, use_container_width=True, hide_index=True)
    download_buttons(funders, stem="top_funders", key_prefix="fn", sheet_name="Funders")

# --- ICMR institute analysis (ICMR mode only) ---
if icmr_mode and it.has_required(df):
    st.header("12 · ICMR institute analysis")
    st.caption("ICMR-specific tables (matches the ICMR bibliometric results document).")
    _li = st.empty()
    _li.markdown(reactor_loader_html("JARVIS is building the ICMR tables…"), unsafe_allow_html=True)
    with st.spinner("Computing institute-level bibliometrics…"):
        t3 = it.institute_benchmarking(df)
        t4_summary, _ = it.division_summary(df)
        t5, t5_overall = it.leadership_vs_contribution(df)
        t8 = it.mandate_fidelity(df)
        t10 = it.international_partners_by_institute(df)
    _li.empty()

    st.markdown("**Table 3 · Institute-level bibliometric benchmarking** (top 15 by volume)")
    st.dataframe(t3, use_container_width=True, hide_index=True)
    download_buttons(t3, stem="icmr_T3_benchmarking", key_prefix="it3", sheet_name="Table 3")

    st.markdown("**Table 4 · Publications by inferred ICMR HQ scientific division**")
    st.dataframe(t4_summary, use_container_width=True, hide_index=True)
    download_buttons(t4_summary, stem="icmr_T4_divisions", key_prefix="it4", sheet_name="Table 4")

    st.markdown("**Table 5 · Leadership vs. contribution, by institute**")
    if not t5.empty:
        st.caption("Corpus-wide: " + ", ".join(f"{k} — {v}" for k, v in t5_overall.items()))
        st.dataframe(t5, use_container_width=True, hide_index=True)
        download_buttons(t5, stem="icmr_T5_leadership", key_prefix="it5", sheet_name="Table 5")
    else:
        st.caption("Needs ‘Corresponding Author from ICMR’ and ‘Any Author from ICMR’ columns.")

    st.markdown("**Table 8 · Mandate fidelity, by institute** (top 15 by fidelity %)")
    if not t8.empty:
        st.dataframe(t8, use_container_width=True, hide_index=True)
        download_buttons(t8, stem="icmr_T8_mandate", key_prefix="it8", sheet_name="Table 8")
    else:
        st.caption("No institute-vision matches found for this dataset.")

    st.markdown("**Table 10 · Leading international partner countries, by disease-focus institute**")
    if not t10.empty:
        st.dataframe(t10, use_container_width=True, hide_index=True)
        download_buttons(t10, stem="icmr_T10_partners", key_prefix="it10", sheet_name="Table 10")
    else:
        st.caption("Needs an ‘All Country’ column.")

brand_footer(note=f"{len(df):,} records analysed")
st.markdown("---")
how_to_use([
    ("🛰", "Enrich & de-duplicate first",
     "Run Data Enrichment, then Fuzzy Title Match to remove duplicates, so metrics and maps are clean."),
    ("📤", "Upload the enriched sheet",
     "Columns (journal, year, citations, authors, references, keywords, countries) are auto-detected."),
    ("📊", "Read the tables & charts",
     "Overview, missing-data, annual trends, Bradford, sources, h-index, top-cited render automatically. Each chart has a PNG download."),
    ("🕸", "Generate a network map",
     "In section 9, pick a map (co-authorship, institutional, country, keyword, coupling), tune the sliders, and click Generate."),
    ("⬇️", "Export",
     "Every table downloads as CSV/Excel; every chart & map as PNG; and maps also export VOSviewer .map/.net files."),
])
st.caption("Coming next (Phase 3): strategic thematic map (motor-theme quadrant) and grants visualization.")
