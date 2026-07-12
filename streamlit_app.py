"""
streamlit_app.py
================
Jarvis Scholar — dashboard HOME (launcher), styled after the v2 reference:
hero + pipeline strip + searchable module grid. Each capability is a
clickable tile; per-tool instructions live on each tool page.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bibliometric_pipeline.branding import (
    THEME_CSS, hero_html_v2, feature_cards_html, pipeline_cards_html, enrichment_template_bytes,
)
from bibliometric_pipeline.auth import require_login, sidebar_account

st.set_page_config(page_title="Jarvis Scholar", layout="wide", page_icon="🛰")
st.markdown(THEME_CSS, unsafe_allow_html=True)
require_login()
sidebar_account()

# Sidebar quick-tip + footer (reference-style)
with st.sidebar:
    st.markdown(
        "<div style='margin-top:10px;padding:12px 14px;border:1px solid #d6e3f2;border-radius:12px;"
        "background:#f2f8fc;'>"
        "<div style='font-family:\"Segoe UI\",sans-serif;font-weight:700;color:#12283b;'>💡 Quick tip</div>"
        "<div style='color:#4a627a;font-size:.84rem;margin-top:4px;'>New here? Start with "
        "<b>Data Enrichment</b> to clean and unify your bibliographic data.</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='color:#9fb0c4;font-size:.76rem;margin-top:14px;'>© 2026 Jarvis Scholar<br>"
                "Built for researchers, by researchers.</div>", unsafe_allow_html=True)

st.markdown(hero_html_v2("Jarvis Scholar",
                         "Bibliometric intelligence console — enrich · convert · match · merge · tag"),
            unsafe_allow_html=True)

# Pipeline strip
st.markdown(pipeline_cards_html([
    {"href": "Convert_Citations", "icon": "📥", "title": "Bring data in",
     "desc": "PubMed / RIS → clean CSV", "tint": "#e6f1fb", "fg": "#2563eb"},
    {"href": "Data_Enrichment", "icon": "🪄", "title": "Enrich",
     "desc": "PubMed + OpenAlex + Crossref", "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Fuzzy_Title_Match", "icon": "🔗", "title": "Match · merge · tag",
     "desc": "Dedup, join, ICMR institutes", "tint": "#efe9fb", "fg": "#7d3c98"},
    {"href": "Scopus_Format_Converter", "icon": "📊", "title": "Export",
     "desc": "Scopus CSV → Biblioshiny", "tint": "#fdeede", "fg": "#d8572a"},
]), unsafe_allow_html=True)

# Module grid + search
hc1, hc2 = st.columns([2, 1])
hc1.markdown("#### Choose a module")
query = hc2.text_input("Search modules", placeholder="Search modules…",
                       label_visibility="collapsed").strip().lower()

TOOLS = [
    {"href": "Data_Enrichment", "icon": "🗄", "title": "Data Enrichment",
     "desc": "Title/DOI list → PubMed + OpenAlex + Crossref, merged per paper.",
     "pills": ["NEEDS .XLSX", "SNO", "CLEAN TITLE", "DOI"], "tint": "#e6f1fb", "fg": "#2563eb"},
    {"href": "Scientometrics_Visualization", "icon": "📈", "title": "Scientometrics Visualization",
     "desc": "Biblioshiny-style tables, charts, VOSviewer maps, thematic map.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Scopus_Format_Converter", "icon": "🛸", "title": "Scopus-format Converter",
     "desc": "Enriched data → Biblioshiny / VOSviewer-ready Scopus CSV.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Convert_Citations", "icon": "📄", "title": "Convert Citations",
     "desc": "PubMed (MEDLINE) or RIS export → clean, pipeline-ready sheet.",
     "pills": ["UPLOAD .TXT", ".NBIB", ".RIS"], "tint": "#fdeede", "fg": "#d8572a"},
    {"href": "ICMR_Institute_Tagger", "icon": "🏛", "title": "ICMR Institute Tagger",
     "desc": "Tag rows with their ICMR institute (former names, acronyms, multi-site).",
     "pills": ["SHEET WITH AFFILIATIONS"], "tint": "#efe9fb", "fg": "#7d3c98"},
    {"href": "Fuzzy_Title_Match", "icon": "🔭", "title": "Fuzzy Title Match",
     "desc": "Match titles by similarity — reconcile two lists or find duplicates.",
     "pills": ["ONE OR TWO TITLE LISTS"], "tint": "#fce8ef", "fg": "#c0398b"},
    {"href": "Merge_Sheets", "icon": "🧬", "title": "Merge Sheets",
     "desc": "Join two sheets on matched column(s) — names can differ.",
     "pills": ["TWO .XLSX / .CSV SHEETS"], "tint": "#e6f6f6", "fg": "#0e8a8a"},
]

if query:
    shown = [t for t in TOOLS if query in (t["title"] + " " + t["desc"] + " " + " ".join(t["pills"])).lower()]
else:
    shown = TOOLS

if shown:
    st.markdown(feature_cards_html(shown), unsafe_allow_html=True)
else:
    st.info("No modules match your search.")

c1, c2 = st.columns([3, 1])
c2.download_button(
    "⬇ Enrichment template (.xlsx)",
    data=enrichment_template_bytes(),
    file_name="jarvis_scholar_enrichment_template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)
st.markdown('<div class="js-footnote">🛡 Your data stays private and secure · Jarvis Scholar · research preview</div>',
            unsafe_allow_html=True)
