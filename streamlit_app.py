"""
streamlit_app.py
================
Jarvis Scholar — dashboard HOME (launcher). Top-level modules only: the
bibliometric pipeline is grouped under its own "Bibliometric Analysis" page;
the Plot Studio, Statistics and AI Figure Interpreter are their own modules.
Each capability is a whole-clickable tile carrying the auth token.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bibliometric_pipeline.branding import THEME_CSS, hero_html_v2, feature_cards_html
from bibliometric_pipeline.auth import require_login, sidebar_account, auth_token

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
        "<div style='color:#4a627a;font-size:.84rem;margin-top:4px;'>New here? Open "
        "<b>Bibliometric Analysis</b> to clean and unify your data — or jump straight into the "
        "<b>Plot Studio</b> or <b>Statistics</b>.</div></div>",
        unsafe_allow_html=True,
    )
    st.markdown("<div style='color:#9fb0c4;font-size:.76rem;margin-top:14px;'>© 2026 Jarvis Scholar<br>"
                "Built for researchers, by researchers.</div>", unsafe_allow_html=True)

st.markdown(hero_html_v2("Jarvis Scholar",
                         "Your no-code research analytics workbench — bibliometrics · plots · statistics · AI"),
            unsafe_allow_html=True)

# auth token → appended to card links so a click (full reload) keeps you logged in
_JT = auth_token()

# Module grid + search
hc1, hc2 = st.columns([2, 1])
hc1.markdown("#### Choose a module")
query = hc2.text_input("Search modules", placeholder="Search modules…",
                       label_visibility="collapsed").strip().lower()

TOOLS = [
    {"href": "Bibliometric_Analysis", "icon": "📚", "title": "Bibliometric Analysis",
     "desc": "The full bibliometric pipeline — ingest, enrich, match, merge, tag, convert and visualize "
             "(scientometrics tables, charts & VOSviewer maps).",
     "pills": ["ENRICH", "SCIENTOMETRICS", "VOSVIEWER MAPS"], "tint": "#e6f1fb", "fg": "#2563eb"},
    {"href": "Scientific_Plot_Studio", "icon": "📊", "title": "Scientific Plot Studio",
     "desc": "~60 publication-ready plots from Excel templates — no code, no biostatistician.",
     "pills": ["PICK PLOT", "FILL TEMPLATE", "UPLOAD"], "tint": "#e6f7ee", "fg": "#1d9e75"},
    {"href": "Statistics", "icon": "🧮", "title": "Statistics",
     "desc": "t-tests, ANOVA, regression, survival & more from Excel — APA output, assumption checks, "
             "test-chooser wizard.",
     "pills": ["PICK TEST", "FILL TEMPLATE", "APA RESULT"], "tint": "#efe9fb", "fg": "#7d3c98"},
    {"href": "AI_Figure_Interpreter", "icon": "🤖", "title": "AI Figure Interpreter",
     "desc": "Upload any figure or map → a plain-language interpretation for your paper.",
     "pills": ["UPLOAD PNG / JPG"], "tint": "#fdeede", "fg": "#d8572a"},
]

if query:
    shown = [t for t in TOOLS if query in (t["title"] + " " + t["desc"] + " " + " ".join(t["pills"])).lower()]
else:
    shown = TOOLS

if shown:
    st.markdown(feature_cards_html(shown, token=_JT), unsafe_allow_html=True)
else:
    st.info("No modules match your search.")

st.markdown('<div class="js-footnote">🛡 Your data stays private and secure · Jarvis Scholar · research preview</div>',
            unsafe_allow_html=True)
