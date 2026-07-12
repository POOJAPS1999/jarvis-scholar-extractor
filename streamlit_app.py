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
    THEME_CSS, hero_html_v2, enrichment_template_bytes,
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

# Pipeline strip (client-side page_link navigation preserves the login session)
PIPELINE = [
    {"page": "pages/1_Convert_Citations.py", "icon": "📥", "title": "Bring data in",
     "desc": "PubMed / RIS → clean CSV", "tint": "#e6f1fb", "fg": "#2563eb"},
    {"page": "pages/5_Data_Enrichment.py", "icon": "🪄", "title": "Enrich",
     "desc": "PubMed + OpenAlex + Crossref", "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"page": "pages/3_Fuzzy_Title_Match.py", "icon": "🔗", "title": "Match · merge · tag",
     "desc": "Dedup, join, ICMR institutes", "tint": "#efe9fb", "fg": "#7d3c98"},
    {"page": "pages/6_Scopus_Format_Converter.py", "icon": "📊", "title": "Export",
     "desc": "Scopus CSV → Biblioshiny", "tint": "#fdeede", "fg": "#d8572a"},
]
pcols = st.columns(len(PIPELINE))
for col, s in zip(pcols, PIPELINE):
    with col:
        st.page_link(s["page"], label=f"{s['icon']} **{s['title']}**  \n{s['desc']}")

# Module grid + search
hc1, hc2 = st.columns([2, 1])
hc1.markdown("#### Choose a module")
query = hc2.text_input("Search modules", placeholder="Search modules…",
                       label_visibility="collapsed").strip().lower()

TOOLS = [
    {"page": "pages/5_Data_Enrichment.py", "icon": "🗄", "title": "Data Enrichment",
     "desc": "Title/DOI list → PubMed + OpenAlex + Crossref, merged per paper.",
     "pills": ["NEEDS .XLSX", "SNO", "CLEAN TITLE", "DOI"], "tint": "#e6f1fb", "fg": "#2563eb"},
    {"page": "pages/7_Scientometrics_Visualization.py", "icon": "📈", "title": "Scientometrics Visualization",
     "desc": "Biblioshiny-style tables, charts, VOSviewer maps, thematic map.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"page": "pages/6_Scopus_Format_Converter.py", "icon": "🛸", "title": "Scopus-format Converter",
     "desc": "Enriched data → Biblioshiny / VOSviewer-ready Scopus CSV.",
     "pills": ["UPLOAD ENRICHED .XLSX"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"page": "pages/1_Convert_Citations.py", "icon": "📄", "title": "Convert Citations",
     "desc": "PubMed (MEDLINE) or RIS export → clean, pipeline-ready sheet.",
     "pills": ["UPLOAD .TXT", ".NBIB", ".RIS"], "tint": "#fdeede", "fg": "#d8572a"},
    {"page": "pages/2_ICMR_Institute_Tagger.py", "icon": "🏛", "title": "ICMR Institute Tagger",
     "desc": "Tag rows with their ICMR institute (former names, acronyms, multi-site).",
     "pills": ["SHEET WITH AFFILIATIONS"], "tint": "#efe9fb", "fg": "#7d3c98"},
    {"page": "pages/3_Fuzzy_Title_Match.py", "icon": "🔭", "title": "Fuzzy Title Match",
     "desc": "Match titles by similarity — reconcile two lists or find duplicates.",
     "pills": ["ONE OR TWO TITLE LISTS"], "tint": "#fce8ef", "fg": "#c0398b"},
    {"page": "pages/4_Merge_Sheets.py", "icon": "🧬", "title": "Merge Sheets",
     "desc": "Join two sheets on matched column(s) — names can differ.",
     "pills": ["TWO .XLSX / .CSV SHEETS"], "tint": "#e6f6f6", "fg": "#0e8a8a"},
    {"page": "pages/8_AI_Figure_Interpreter.py", "icon": "🤖", "title": "AI Figure Interpreter",
     "desc": "Upload any figure or map → a plain-language interpretation for your paper.",
     "pills": ["UPLOAD PNG / JPG"], "tint": "#f3e9fb", "fg": "#7d3c98"},
]

if query:
    shown = [t for t in TOOLS if query in (t["title"] + " " + t["desc"] + " " + " ".join(t["pills"])).lower()]
else:
    shown = TOOLS

if not shown:
    st.info("No modules match your search.")
else:
    per_row = 3
    for i in range(0, len(shown), per_row):
        row = shown[i:i + per_row]
        cols = st.columns(per_row)
        for col, t in zip(cols, row):
            with col:
                pills = " · ".join(t["pills"])
                st.page_link(
                    t["page"],
                    label=f"{t['icon']} **{t['title']}**  \n{t['desc']}  \n\n`{pills}`")

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
