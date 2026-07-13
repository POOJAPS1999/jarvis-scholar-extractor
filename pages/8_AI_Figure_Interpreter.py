"""
AI Figure Interpreter
=====================
Upload any figure — a Biblioshiny/VOSviewer output, one of Jarvis Scholar's
own maps/charts, or a figure from a paper — and get a plain-language,
researcher-ready interpretation from a vision model.
"""
import os
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline.ai import interpret_figure

st.set_page_config(page_title="Jarvis Scholar - AI Figure Interpreter", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("AI figure interpreter")
st.caption(
    "Upload a bibliometric figure — a VOSviewer/Biblioshiny map, a Jarvis Scholar chart, or a "
    "figure from a paper — and get a plain-language interpretation for your Results/Discussion."
)

uploaded = st.file_uploader("Upload a figure (PNG / JPG)", type=["png", "jpg", "jpeg", "webp"])
context = st.text_input(
    "Optional context",
    placeholder="e.g. 'Keyword co-occurrence map of 2,632 ICMR publications, 2025–2026'",
    help="A one-line description helps the model interpret the figure more accurately.",
)

if uploaded is not None:
    st.image(uploaded, caption="Figure to interpret", use_container_width=True)
    if st.button("🔍 Interpret with AI", type="primary"):
        _loader = st.empty()
        _loader.markdown(reactor_loader_html("JARVIS is reading the figure…"), unsafe_allow_html=True)
        try:
            with jarvis_spinner("Interpreting…"):
                text = interpret_figure(
                    uploaded.getvalue(), context=context,
                    filename=uploaded.name, mime=uploaded.type or "image/png")
        except Exception as e:
            _loader.empty()
            st.error(str(e))
            st.stop()
        _loader.empty()
        st.subheader("Interpretation")
        st.write(text)
        st.download_button("⬇ Download interpretation (.txt)", data=text.encode("utf-8"),
                           file_name="figure_interpretation.txt", mime="text/plain")
        st.caption("AI-generated — always sanity-check against the figure before quoting it in a manuscript.")
        brand_footer()
else:
    st.info("Upload a figure to interpret.")

st.markdown("---")
how_to_use([
    ("🖼", "Get your figure ready",
     "Any chart or map image works — export a VOSviewer/Biblioshiny figure, or download a PNG from "
     "any Jarvis Scholar chart/map (each has a Download PNG button)."),
    ("📤", "Upload it",
     "Drop the PNG/JPG here. Add a one-line context (what the figure is) for a sharper reading."),
    ("🔍", "Interpret with AI",
     "Click the button. A vision model reads the figure and describes the patterns, clusters, and takeaways."),
    ("✅", "Review & use",
     "Read the interpretation, download it as text, and adapt it for your manuscript — always verify it against the figure."),
])
st.caption("Note: figures are sent to the AI provider for interpretation. Needs a (free) GEMINI_API_KEY "
           "or an ANTHROPIC_API_KEY configured on the server.")
