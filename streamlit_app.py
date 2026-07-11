"""
streamlit_app.py
================
Jarvis Scholar — dashboard HOME.

This file used to hold the extractor flow directly. That flow now lives in
pages/5_Data_Enrichment.py; this file is the launcher: a sci-fi command-deck
of selectable tools, each with a short description and its own page (with
per-tool instructions + upload-format help + template downloads on the page
itself).

Streamlit multipage: every file under pages/ shows in the left nav
automatically; the cards below are just a nicer, described entry point to
the same pages.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bibliometric_pipeline.branding import THEME_CSS, hero_html, enrichment_template_bytes

st.set_page_config(page_title="Jarvis Scholar", layout="wide", page_icon="🛰")
st.markdown(THEME_CSS, unsafe_allow_html=True)

st.markdown(
    hero_html("JARVIS SCHOLAR",
              "Bibliometric intelligence console · enrich · convert · match · merge · tag"),
    unsafe_allow_html=True,
)
st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# Each tool: page path, icon, title, one-line description, format hint.
TOOLS = [
    {
        "page": "pages/5_Data_Enrichment.py", "icon": "🛰", "title": "Data Enrichment",
        "desc": "Upload a title/DOI list → PubMed + OpenAlex + Crossref merged into one clean row per paper.",
        "fmt": "Needs .xlsx with Sno · Clean Title · DOI (template on the page).",
    },
    {
        "page": "pages/6_Scopus_Format_Converter.py", "icon": "🛸", "title": "Scopus-format Converter",
        "desc": "Convert an already-enriched dataset into Biblioshiny/VOSviewer-ready Scopus CSV — no re-enrichment.",
        "fmt": "Upload a Jarvis Scholar enriched output .xlsx/.csv.",
    },
    {
        "page": "pages/1_Convert_Citations.py", "icon": "📄", "title": "Convert Citations",
        "desc": "Turn a PubMed (MEDLINE .txt/.nbib) or RIS export into a clean CSV/Excel, pipeline-ready.",
        "fmt": "Upload a .txt / .nbib / .ris export.",
    },
    {
        "page": "pages/2_ICMR_Institute_Tagger.py", "icon": "🏛", "title": "ICMR Institute Tagger",
        "desc": "Tag each row with its ICMR institute (handles former names, acronyms, multi-site rows).",
        "fmt": "Upload a sheet with affiliation column(s).",
    },
    {
        "page": "pages/3_Fuzzy_Title_Match.py", "icon": "🔭", "title": "Fuzzy Title Match",
        "desc": "Match titles by similarity — reconcile two lists, or find duplicates within one.",
        "fmt": "Upload one or two .xlsx/.csv lists of titles.",
    },
    {
        "page": "pages/4_Merge_Sheets.py", "icon": "🧬", "title": "Merge Sheets",
        "desc": "Join two spreadsheets on matched column(s) — names can differ — with an unmatched-rows report.",
        "fmt": "Upload two .xlsx/.csv sheets.",
    },
]

st.markdown("#### Select a module")

# Render the cards in rows of up to 3, each with a working page-link button.
per_row = 3
for start in range(0, len(TOOLS), per_row):
    row = TOOLS[start:start + per_row]
    cols = st.columns(len(row))
    for col, t in zip(cols, row):
        with col:
            st.markdown(
                f"""
<div class="js-card">
  <div class="js-ic">{t['icon']}</div>
  <div class="js-title">{t['title']}</div>
  <div class="js-desc">{t['desc']}</div>
  <div class="js-tag">{t['fmt']}</div>
</div>
""",
                unsafe_allow_html=True,
            )
            st.page_link(t["page"], label=f"Open {t['title']} →")

st.markdown("---")

c1, c2 = st.columns([2, 1])
with c1:
    st.markdown(
        "**New here?** Start with **Data Enrichment** — download its blank template, "
        "fill in your papers, and upload. Or use **Convert Citations** first if your "
        "data is a PubMed/RIS export, then feed the result into enrichment."
    )
with c2:
    st.download_button(
        "⬇ Enrichment template (.xlsx)",
        data=enrichment_template_bytes(),
        file_name="jarvis_scholar_enrichment_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.caption("Jarvis Scholar · research preview · more modules coming online.")
