"""
Bibliometric Analysis
=====================
Hub page grouping the full bibliometric pipeline — ingest, enrich, match,
merge, tag, convert and visualize — so the home dashboard can stay a clean
top-level launcher. Each card is a whole-clickable tile carrying the auth
token; the tools themselves live on their own pages.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bibliometric_pipeline.branding import (
    THEME_CSS, hero_html_v2, feature_cards_html, pipeline_cards_html, enrichment_template_bytes,
)

st.set_page_config(page_title="Jarvis Scholar - Bibliometric Analysis", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account, auth_token
require_login()
sidebar_account()

st.markdown(hero_html_v2("Bibliometric Analysis",
                         "Enrich · convert · match · merge · tag · map", badge="7 tools"),
            unsafe_allow_html=True)

_JT = auth_token()

# Pipeline strip (whole card clickable)
PIPELINE = [
    {"href": "Convert_Citations", "icon": "📥", "title": "Bring data in",
     "desc": "PubMed / RIS → clean CSV", "tint": "#e6f1fb", "fg": "#2563eb"},
    {"href": "Data_Enrichment", "icon": "🪄", "title": "Enrich",
     "desc": "PubMed + OpenAlex + Crossref", "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Fuzzy_Title_Match", "icon": "🔗", "title": "Match · merge · tag",
     "desc": "Dedup, join, ICMR institutes", "tint": "#efe9fb", "fg": "#7d3c98"},
    {"href": "Scopus_Format_Converter", "icon": "📊", "title": "Export",
     "desc": "Scopus CSV → Biblioshiny", "tint": "#fdeede", "fg": "#d8572a"},
]
st.markdown(pipeline_cards_html(PIPELINE, token=_JT), unsafe_allow_html=True)

st.markdown("#### Bibliometric tools")

BIBLIO = [
    {"href": "Convert_Citations", "icon": "📄", "title": "Convert Citations",
     "desc": "PubMed (MEDLINE) or RIS export → clean, pipeline-ready sheet.",
     "pills": ["UPLOAD .TXT", ".NBIB", ".RIS"], "tint": "#fdeede", "fg": "#d8572a"},
    {"href": "Data_Enrichment", "icon": "🗄", "title": "Data Enrichment",
     "desc": "Title/DOI list → PubMed + OpenAlex + Crossref, merged per paper.",
     "pills": ["NEEDS .XLSX", "SNO", "CLEAN TITLE", "DOI"], "tint": "#e6f1fb", "fg": "#2563eb"},
    {"href": "Fuzzy_Title_Match", "icon": "🔭", "title": "Fuzzy Title Match",
     "desc": "Match titles by similarity — reconcile two lists or find duplicates.",
     "pills": ["ONE OR TWO TITLE LISTS"], "tint": "#fce8ef", "fg": "#c0398b"},
    {"href": "Merge_Sheets", "icon": "🧬", "title": "Merge Sheets",
     "desc": "Join two sheets on matched column(s) — names can differ.",
     "pills": ["TWO .XLSX / .CSV SHEETS"], "tint": "#e6f6f6", "fg": "#0e8a8a"},
    {"href": "ICMR_Institute_Tagger", "icon": "🏛", "title": "ICMR Institute Tagger",
     "desc": "Tag rows with their ICMR institute (former names, acronyms, multi-site).",
     "pills": ["SHEET WITH AFFILIATIONS"], "tint": "#efe9fb", "fg": "#7d3c98"},
    {"href": "Scopus_Format_Converter", "icon": "🛸", "title": "Scopus-format Converter",
     "desc": "Enriched data → Biblioshiny / VOSviewer-ready Scopus CSV.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Scientometrics_Visualization", "icon": "📈", "title": "Scientometrics Visualization",
     "desc": "Biblioshiny-style tables, charts, VOSviewer maps, thematic map.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
]
st.markdown(feature_cards_html(BIBLIO, token=_JT), unsafe_allow_html=True)

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
