"""
streamlit_app.py
================
Jarvis Scholar — dashboard HOME (launcher).

A light "scientific lab" command deck: each capability is a clickable tile
(the WHOLE box navigates to the tool). Per-tool instructions live on each
tool page. Streamlit auto-discovers pages/ for the sidebar nav; these tiles
are a friendlier, described entry point to the same pages.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bibliometric_pipeline.branding import (
    THEME_CSS, hero_html, feature_cards_html, enrichment_template_bytes,
)

st.set_page_config(page_title="Jarvis Scholar", layout="wide", page_icon="🛰")
st.markdown(THEME_CSS, unsafe_allow_html=True)

st.markdown(
    hero_html("Jarvis Scholar",
              "Bibliometric intelligence console — enrich · convert · match · merge · tag"),
    unsafe_allow_html=True,
)

# Compact "what this does" infographic strip (pipeline at a glance).
st.markdown(
    """
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:12px 0 4px;">
  <div style="background:#ffffff;border:1px solid #d6e3f2;border-radius:14px;padding:14px 16px;">
    <div style="font-size:22px">📥</div>
    <div style="font-family:'Segoe UI',sans-serif;font-weight:700;color:#12283b;margin-top:4px">Bring data in</div>
    <div style="color:#4a627a;font-size:.86rem">PubMed / RIS → clean CSV</div>
  </div>
  <div style="background:#ffffff;border:1px solid #d6e3f2;border-radius:14px;padding:14px 16px;">
    <div style="font-size:22px">🛰</div>
    <div style="font-family:'Segoe UI',sans-serif;font-weight:700;color:#12283b;margin-top:4px">Enrich</div>
    <div style="color:#4a627a;font-size:.86rem">PubMed + OpenAlex + Crossref</div>
  </div>
  <div style="background:#ffffff;border:1px solid #d6e3f2;border-radius:14px;padding:14px 16px;">
    <div style="font-size:22px">🧪</div>
    <div style="font-family:'Segoe UI',sans-serif;font-weight:700;color:#12283b;margin-top:4px">Match · merge · tag</div>
    <div style="color:#4a627a;font-size:.86rem">Dedup, join, ICMR institutes</div>
  </div>
  <div style="background:#ffffff;border:1px solid #d6e3f2;border-radius:14px;padding:14px 16px;">
    <div style="font-size:22px">📊</div>
    <div style="font-family:'Segoe UI',sans-serif;font-weight:700;color:#12283b;margin-top:4px">Export</div>
    <div style="color:#4a627a;font-size:.86rem">Scopus CSV → Biblioshiny</div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("#### Choose a module")

# href = Streamlit page URL slug (filename without the numeric prefix / .py).
TOOLS = [
    {"href": "Data_Enrichment", "icon": "🛰", "title": "Data Enrichment",
     "desc": "Title/DOI list → PubMed + OpenAlex + Crossref, merged per paper.",
     "tag": "needs .xlsx · Sno · Clean Title · DOI"},
    {"href": "Scopus_Format_Converter", "icon": "🛸", "title": "Scopus-format Converter",
     "desc": "Enriched data → Biblioshiny / VOSviewer-ready Scopus CSV.",
     "tag": "upload enriched .xlsx"},
    {"href": "Convert_Citations", "icon": "📄", "title": "Convert Citations",
     "desc": "PubMed (MEDLINE) or RIS export → clean, pipeline-ready sheet.",
     "tag": "upload .txt / .nbib / .ris"},
    {"href": "ICMR_Institute_Tagger", "icon": "🏛", "title": "ICMR Institute Tagger",
     "desc": "Tag rows with their ICMR institute (former names, acronyms, multi-site).",
     "tag": "sheet with affiliations"},
    {"href": "Fuzzy_Title_Match", "icon": "🔭", "title": "Fuzzy Title Match",
     "desc": "Match titles by similarity — reconcile two lists or find duplicates.",
     "tag": "one or two title lists"},
    {"href": "Merge_Sheets", "icon": "🧬", "title": "Merge Sheets",
     "desc": "Join two sheets on matched column(s) — names can differ.",
     "tag": "two .xlsx / .csv sheets"},
]

st.markdown(feature_cards_html(TOOLS), unsafe_allow_html=True)

st.markdown("---")
c1, c2 = st.columns([2, 1])
with c1:
    st.markdown(
        "**New here?** Start with **Data Enrichment** — download its blank template, "
        "fill in your papers, upload. Or use **Convert Citations** first if your data "
        "is a PubMed/RIS export, then feed the result into enrichment."
    )
with c2:
    st.download_button(
        "⬇ Enrichment template (.xlsx)",
        data=enrichment_template_bytes(),
        file_name="jarvis_scholar_enrichment_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

st.caption("Jarvis Scholar · research preview")
