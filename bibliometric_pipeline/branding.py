"""
branding.py
===========
Shared visual identity for the Jarvis Scholar dashboard.

Design language (chosen with Pooja): a LIGHT "scientific lab" theme — pale
ice-blue canvas, white panels with hairline borders and a soft cyan accent,
a clean serif for body/subtext and a crisp sans for headings. Sci-fi but
sophisticated, not pitch black.

Exposes:
  - THEME_CSS            global CSS (inject once per page)
  - hero_html()          page hero with the arc-reactor mark
  - reactor_loader_html() animated "JARVIS is working" loader
  - feature_cards_html()  the clickable dashboard tile grid
  - how_to_use()          a "How to use" step-by-step block for tool pages
  - enrichment_template_bytes(), scopus_input_template_bytes()  blank templates
"""
from __future__ import annotations

import io

import pandas as pd

_SANS = "'Inter', 'Segoe UI', 'Helvetica Neue', Arial, system-ui, sans-serif"
_SERIF = "'Inter', 'Segoe UI', Arial, system-ui, sans-serif"

# ---------------------------------------------------------------------
# Global theme CSS
# ---------------------------------------------------------------------
THEME_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
:root {{
  --js-cyan: #0fb5d6;
  --js-cyan-deep: #0e7f9c;
  --js-cyan-soft: #7fd3e6;
  --js-blue: #2563eb;
  --js-indigo: #4f46e5;
  --js-ink: #12283b;
  --js-sub: #54708a;
  --js-line: #e4eef7;
  --js-line-2: #d3e3f1;
  --js-panel: #ffffff;
  --js-bg: #f7fbfe;
}}
.stApp {{
  background:
    radial-gradient(60% 40% at 82% -6%, rgba(15,181,214,0.07), transparent 60%),
    radial-gradient(52% 38% at 8% 2%, rgba(37,99,235,0.05), transparent 60%),
    var(--js-bg);
}}
/* Serif body / subtext, crisp sans headings */
html, body, .stMarkdown, .stCaption, p, label, .stText, [data-testid="stMarkdownContainer"] {{
  font-family: {_SERIF};
}}
h1, h2, h3, h4 {{ font-family: {_SANS}; letter-spacing: .2px; color: var(--js-ink); }}
[data-testid="stCaptionContainer"], .stCaption p {{ color: var(--js-sub); font-family: {_SERIF}; }}

/* Dashboard tile grid — the WHOLE card is a link */
.js-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; margin: 10px 0 6px; }}
.js-card {{
  display: block; text-decoration: none; color: inherit;
  position: relative; border: 1px solid var(--js-line); border-radius: 16px;
  padding: 20px 20px 18px; background: var(--js-panel);
  box-shadow: 0 1px 2px rgba(18,40,59,0.04), 0 8px 24px rgba(18,40,59,0.06);
  transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease;
  min-height: 172px;
}}
.js-card:hover {{ transform: translateY(-3px); border-color: var(--js-cyan);
  box-shadow: 0 0 0 3px rgba(14,127,156,0.10), 0 14px 30px rgba(18,40,59,0.12); }}
.js-ic-wrap {{ display:inline-flex; align-items:center; justify-content:center;
  width:46px; height:46px; border-radius:12px; background:#e8f6fb;
  border:1px solid var(--js-line); font-size:24px; margin-bottom:10px; }}
.js-title {{ font-family:{_SANS}; font-weight:700; color:var(--js-ink); font-size:1.08rem; margin:2px 0 5px; }}
.js-desc {{ font-family:{_SERIF}; color:var(--js-sub); font-size:.92rem; line-height:1.45; }}
.js-tag {{ display:inline-block; margin-top:12px; font-family:{_SANS}; font-size:.7rem;
  letter-spacing:.06em; text-transform:uppercase; color:var(--js-cyan);
  background:#e8f6fb; border:1px solid var(--js-line); border-radius:999px; padding:3px 10px; }}
.js-cta {{ margin-top:12px; font-family:{_SANS}; font-weight:600; font-size:.86rem; color:var(--js-cyan); }}

/* How-to-use steps */
.js-how {{ border:1px solid var(--js-line); background:var(--js-panel); border-radius:14px; padding:6px 20px 14px; margin-top:8px; }}
.js-step {{ display:flex; gap:14px; align-items:flex-start; padding:14px 0; border-bottom:1px solid #eef3f9; }}
.js-step:last-child {{ border-bottom:none; }}
.js-step-n {{ flex:0 0 auto; width:30px; height:30px; border-radius:50%; background:var(--js-cyan);
  color:#fff; font-family:{_SANS}; font-weight:700; display:flex; align-items:center; justify-content:center; font-size:.9rem; }}
.js-step-ic {{ flex:0 0 auto; font-size:20px; margin-top:1px; width:26px; text-align:center; }}
.js-step-b {{ flex:1; }}
.js-step-t {{ font-family:{_SANS}; font-weight:600; color:var(--js-ink); font-size:.98rem; }}
.js-step-d {{ font-family:{_SERIF}; color:var(--js-sub); font-size:.9rem; line-height:1.45; margin-top:2px; }}
.js-shot {{ margin-top:8px; border:1px dashed var(--js-line); border-radius:10px; background:#f7fafe;
  color:#8aa0b8; font-family:{_SANS}; font-size:.74rem; padding:9px 12px; }}

.js-hero-sub {{ color:var(--js-sub); font-family:{_SERIF}; font-size:1rem; }}
hr {{ border-color: var(--js-line) !important; }}

/* ---- reference-style dashboard ---- */
.js-hero-wrap {{ position:relative; overflow:hidden; border-radius:18px; padding:6px 4px 2px; }}
.js-badge {{ display:inline-block; font-family:{_SANS}; font-size:.66rem; font-weight:700;
  letter-spacing:.06em; color:#2563eb; background:#e8f0ff; border:1px solid #d3e0fb;
  border-radius:999px; padding:2px 9px; vertical-align:middle; margin-left:10px; }}

.js-pipe {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:16px; margin:14px 0 6px; }}
.js-pipe-card {{ display:block; text-decoration:none; color:inherit; background:#fff;
  border:1px solid var(--js-line); border-radius:16px; padding:18px 18px 16px;
  box-shadow:0 1px 2px rgba(18,40,59,.04); transition:transform .14s, box-shadow .14s, border-color .14s; }}
.js-pipe-card:hover {{ transform:translateY(-2px); border-color:var(--js-cyan);
  box-shadow:0 8px 22px rgba(18,40,59,.10); }}
.js-sq {{ width:46px; height:46px; border-radius:13px; display:flex; align-items:center;
  justify-content:center; font-size:22px; margin-bottom:12px; }}
.js-pipe-t {{ font-family:{_SANS}; font-weight:700; color:var(--js-ink); font-size:1.02rem; }}
.js-pipe-d {{ font-family:{_SERIF}; color:var(--js-sub); font-size:.86rem; margin-top:2px; }}
.js-arrow {{ float:right; color:var(--js-cyan); font-weight:700; margin-top:-22px; }}

.js-tool-card {{ display:block; text-decoration:none; color:inherit; background:#fff;
  border:1px solid var(--js-line); border-radius:16px; padding:18px 18px 16px; height:100%;
  box-shadow:0 1px 2px rgba(18,40,59,.04); transition:transform .14s, box-shadow .14s, border-color .14s; }}
.js-tool-card:hover {{ transform:translateY(-3px); border-color:var(--js-cyan);
  box-shadow:0 10px 26px rgba(18,40,59,.12); }}
.js-tool-head {{ display:flex; gap:13px; align-items:flex-start; }}
.js-tool-t {{ font-family:{_SANS}; font-weight:700; color:var(--js-ink); font-size:1.06rem; }}
.js-tool-d {{ font-family:{_SERIF}; color:var(--js-sub); font-size:.88rem; line-height:1.45; margin-top:3px; }}
.js-pills {{ margin-top:12px; }}
.js-pill {{ display:inline-block; font-family:{_SANS}; font-size:.66rem; font-weight:600;
  letter-spacing:.04em; color:#3763a6; background:#eef3fb; border:1px solid #dde8f7;
  border-radius:7px; padding:3px 8px; margin:0 6px 6px 0; }}
.js-open {{ margin-top:12px; font-family:{_SANS}; font-weight:700; font-size:.9rem; color:var(--js-cyan); }}
.js-footnote {{ text-align:center; color:var(--js-sub); font-family:{_SERIF}; font-size:.86rem; margin-top:18px; }}

/* Make main-area st.page_link render as a big, whole-clickable CARD
   (client-side nav → keeps the login session; not the sidebar nav) */
[data-testid="stMain"] div[data-testid="stPageLink"] {{ margin:0 0 4px; }}
[data-testid="stMain"] div[data-testid="stPageLink"] > a {{
  display:block; text-decoration:none !important; background:#fff;
  border:1px solid var(--js-line); border-radius:16px; padding:16px 18px; min-height:104px;
  box-shadow:0 1px 2px rgba(18,40,59,.04);
  transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
}}
[data-testid="stMain"] div[data-testid="stPageLink"] > a:hover {{
  border-color:var(--js-cyan); transform:translateY(-3px);
  box-shadow:0 10px 26px rgba(18,40,59,.12);
}}
[data-testid="stMain"] div[data-testid="stPageLink"] p {{
  text-align:left !important; font-family:{_SANS}; color:var(--js-ink); }}

/* never underline anything (links, cards, nav) — looks cleaner */
a, a:hover, a:focus, a:active, a:visited,
.js-card, .js-tool-card, .js-pipe-card,
[data-testid="stSidebarNav"] a, [data-testid="stPageLink"] a {{ text-decoration: none !important; }}
a:hover, .js-open:hover {{ text-decoration: none !important; }}

/* Iron-Man mascot loader (replaces the default Streamlit spinner) */
.jarvis-loader {{ display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:8px; padding:14px 10px 10px; }}
.jarvis-loader .ji-stage {{ position:relative; width:80px; height:80px;
  display:flex; align-items:center; justify-content:center; }}
.jarvis-loader .ji-ring {{ position:absolute; width:74px; height:74px; border-radius:50%;
  border:3px solid rgba(216,87,42,0.15); border-top-color:#d8572a; border-right-color:#e0a100;
  animation:jiSpin 0.95s linear infinite; }}
.jarvis-loader .ji-glow {{ position:absolute; width:52px; height:52px; border-radius:50%;
  background:radial-gradient(circle, rgba(34,195,230,0.55), rgba(34,195,230,0) 70%);
  animation:jiPulse 1.35s ease-in-out infinite; }}
.jarvis-loader img.ji-hero {{ position:relative; z-index:2; width:48px; height:auto;
  filter:drop-shadow(0 5px 7px rgba(0,0,0,0.18)); animation:jiFloat 1.5s ease-in-out infinite; }}
.jarvis-loader .ji-text {{ font-family:{_SANS}; font-weight:700; color:var(--js-ink);
  font-size:0.9rem; letter-spacing:.2px; text-align:center; }}
.jarvis-loader .ji-text .ji-dots::after {{ display:inline-block; width:1.1em; text-align:left;
  content:''; animation:jiDots 1.4s steps(1,end) infinite; }}
@keyframes jiFloat {{ 0%,100% {{ transform:translateY(0); }} 50% {{ transform:translateY(-6px); }} }}
@keyframes jiSpin  {{ to {{ transform:rotate(360deg); }} }}
@keyframes jiPulse {{ 0%,100% {{ transform:scale(.82); opacity:.5; }} 50% {{ transform:scale(1.15); opacity:.95; }} }}
@keyframes jiDots  {{ 0%{{content:'';}} 25%{{content:'.';}} 50%{{content:'..';}} 75%{{content:'...';}} 100%{{content:'';}} }}

/* ===== v3 design-system refinements (match the landing page) ===== */
h1, h2, h3, h4 {{ font-weight:800; letter-spacing:-.01em; }}
[data-testid="stMain"] .block-container {{ max-width:1180px; padding-top:2.0rem; padding-bottom:3rem; }}

/* Buttons → cyan gradient for primary/submit, rounded + lift for all */
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] button {{
  font-family:{_SANS} !important; font-weight:600 !important; border-radius:11px !important;
  transition:transform .16s ease, box-shadow .22s ease, background .2s ease, filter .2s ease; }}
.stButton > button:hover, .stDownloadButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {{ transform:translateY(-1px); }}
button[kind="primary"], [data-testid="stBaseButton-primary"], [data-testid="baseButton-primary"], [data-testid="stFormSubmitButton"] button {{
  background:linear-gradient(180deg, var(--js-cyan), var(--js-cyan-deep)) !important;
  color:#fff !important; border:none !important; box-shadow:0 8px 20px rgba(15,181,214,.28) !important; }}
button[kind="primary"]:hover, [data-testid="stBaseButton-primary"]:hover, [data-testid="stFormSubmitButton"] button:hover {{
  box-shadow:0 12px 26px rgba(15,181,214,.42) !important; filter:brightness(1.03); }}

/* Inputs / selects → rounded, cyan focus ring */
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div {{ border-radius:10px !important; }}
[data-baseweb="input"] input:focus, [data-baseweb="textarea"] textarea:focus, textarea:focus, .stNumberInput input:focus {{
  box-shadow:0 0 0 3px rgba(15,181,214,.18) !important; }}
[data-baseweb="base-input"]:focus-within {{ border-color:var(--js-cyan) !important; }}

/* Tabs → cyan active */
[data-baseweb="tab"][aria-selected="true"] {{ color:var(--js-cyan-deep) !important; }}
[data-baseweb="tab-highlight"] {{ background:var(--js-cyan) !important; }}

/* Expanders, alerts, dataframes, uploader */
[data-testid="stExpander"] {{ border:1px solid var(--js-line) !important; border-radius:14px !important; box-shadow:0 1px 2px rgba(18,40,59,.04); }}
[data-testid="stExpander"] summary:hover {{ color:var(--js-cyan-deep); }}
[data-testid="stAlert"] {{ border-radius:12px; }}
[data-testid="stDataFrame"] {{ border-radius:12px; overflow:hidden; border:1px solid var(--js-line); }}
[data-testid="stFileUploaderDropzone"] {{ border-radius:14px !important; border:1.5px dashed var(--js-line-2) !important; background:#fbfdff !important; }}

/* Cards → softer resting shadow + landing-style hover glow */
.js-tool-card, .js-pipe-card, .js-card {{ box-shadow:0 10px 30px rgba(18,40,59,.07) !important; }}
.js-tool-card:hover, .js-card:hover {{ border-color:transparent !important;
  box-shadow:0 22px 56px rgba(18,40,59,.14), inset 0 0 0 1px rgba(15,181,214,.35), 0 0 38px rgba(15,181,214,.12) !important; }}
.js-pipe-card:hover {{ border-color:transparent !important;
  box-shadow:0 16px 40px rgba(18,40,59,.12), inset 0 0 0 1px rgba(15,181,214,.30) !important; }}

/* Sidebar polish */
[data-testid="stSidebar"] {{ background:#fbfdff; border-right:1px solid var(--js-line); }}
</style>
"""


# ---------------------------------------------------------------------
# Animated arc-reactor loader (cyan HUD ring, works on the light canvas)
# ---------------------------------------------------------------------
def reactor_loader_html(label: str = "JARVIS is working…", size: int = 88) -> str:
    return f"""
<div style="display:flex;align-items:center;gap:16px;margin:10px 0;">
  <svg width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="loading">
    <defs>
      <radialGradient id="jsCore" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#ffffff"/><stop offset="45%" stop-color="#22c3e6"/>
        <stop offset="100%" stop-color="#0e7f9c"/>
      </radialGradient>
    </defs>
    <circle cx="50" cy="50" r="31" fill="none" stroke="#4f46e5" stroke-width="2.2"
            stroke-dasharray="6 9" opacity="0.55">
      <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="3.2s" repeatCount="indefinite"/>
    </circle>
    <circle cx="50" cy="50" r="22" fill="none" stroke="#0e7f9c" stroke-width="2.6"
            stroke-dasharray="26 12" stroke-linecap="round" opacity="0.95">
      <animateTransform attributeName="transform" type="rotate" from="360 50 50" to="0 50 50" dur="1.8s" repeatCount="indefinite"/>
    </circle>
    <g>
      <animateTransform attributeName="transform" type="rotate" from="0 50 50" to="360 50 50" dur="2.4s" repeatCount="indefinite"/>
      <circle cx="50" cy="23" r="2.4" fill="#22c3e6"/><circle cx="77" cy="50" r="2" fill="#22c3e6"/>
      <circle cx="50" cy="77" r="2.4" fill="#22c3e6"/><circle cx="23" cy="50" r="2" fill="#22c3e6"/>
    </g>
    <circle cx="50" cy="50" r="10" fill="url(#jsCore)">
      <animate attributeName="r" values="9;11.5;9" dur="1.4s" repeatCount="indefinite"/>
    </circle>
  </svg>
  <div>
    <div style="color:#0e7f9c;font-weight:700;font-family:{_SANS};">{label}</div>
    <div style="color:#7f97ae;font-size:.82rem;font-family:{_SERIF};">standby · processing</div>
  </div>
</div>
"""


def jarvis_loader_html(label: str = "Working") -> str:
    """Markup for the Iron-Man mascot loader (spinning HUD ring + floating
    mascot + pulsing arc-reactor glow + animated dots). CSS lives in THEME_CSS."""
    from .loader_asset import JARVIS_LOADER_PNG_B64
    return (
        '<div class="jarvis-loader">'
        '<div class="ji-stage">'
        '<div class="ji-ring"></div><div class="ji-glow"></div>'
        f'<img class="ji-hero" alt="loading" '
        f'src="data:image/png;base64,{JARVIS_LOADER_PNG_B64}"/>'
        '</div>'
        f'<div class="ji-text">{label}<span class="ji-dots"></span></div>'
        '</div>'
    )


def jarvis_spinner(label: str = "Working…"):
    """Drop-in replacement for `st.spinner(...)` that shows the Iron-Man mascot
    loader instead of Streamlit's default spinner. Usage:

        with jarvis_spinner("Crunching the corpus…"):
            ...heavy work...
    """
    import streamlit as st
    from contextlib import contextmanager

    # strip a trailing ellipsis/… so we don't double up with the animated dots
    clean = label.rstrip(" .…")

    @contextmanager
    def _cm():
        holder = st.empty()
        holder.markdown(jarvis_loader_html(clean), unsafe_allow_html=True)
        try:
            yield
        finally:
            holder.empty()

    return _cm()


def brand_footer(note: str = ""):
    """Small 'Generated with Jarvis Scholar' watermark for the bottom of any
    output block (Biblioshiny-style provenance mark). Call inside a page."""
    import streamlit as st
    from datetime import date
    extra = f" · {note}" if note else ""
    st.markdown(
        f"<div style='margin:10px 0 2px;color:#9fb0c4;font-family:{_SANS};font-size:.75rem;'>"
        f"🛰 Generated with <b>Jarvis Scholar</b> · {date.today().isoformat()}{extra}</div>",
        unsafe_allow_html=True,
    )


def watermark_chart(chart, text: str = "Jarvis Scholar"):
    """Overlay a faint 'Jarvis Scholar' mark on an Altair chart (top-right),
    the way Biblioshiny stamps its plots."""
    import altair as alt
    return chart.properties(
        title=alt.TitleParams(text=" ", subtitle=text, subtitleColor="#b8c6d8",
                              subtitleFontSize=10, subtitleFontStyle="italic", anchor="end"),
    )


def hero_html(title: str, tagline: str) -> str:
    return f"""
<div style="display:flex;align-items:center;gap:18px;margin:2px 0 8px;">
  <svg width="56" height="56" viewBox="0 0 100 100" aria-hidden="true">
    <defs><radialGradient id="jsHeroCore" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="55%" stop-color="#22c3e6"/>
      <stop offset="100%" stop-color="#0e7f9c"/></radialGradient></defs>
    <circle cx="50" cy="50" r="31" fill="none" stroke="#4f46e5" stroke-width="2.2" stroke-dasharray="5 8" opacity="0.5"/>
    <circle cx="50" cy="50" r="21" fill="none" stroke="#0e7f9c" stroke-width="2.6" stroke-dasharray="24 10" stroke-linecap="round"/>
    <circle cx="50" cy="50" r="9" fill="url(#jsHeroCore)"/>
  </svg>
  <div>
    <div style="font-size:1.95rem;font-weight:800;letter-spacing:.4px;color:#12283b;font-family:{_SANS};">{title}</div>
    <div class="js-hero-sub">{tagline}</div>
  </div>
</div>
"""


# ---------------------------------------------------------------------
# Dashboard clickable tile grid
# ---------------------------------------------------------------------
def _href(slug: str, token: str = "") -> str:
    return f"{slug}?jt={token}" if token else slug


def feature_cards_html(tools: list, token: str = "") -> str:
    """Reference-style module grid. Each tool dict: href (page slug), icon,
    title, desc, pills (list), tint, fg. Whole card is an <a> so clicking
    anywhere navigates; the ?jt token keeps the login across the reload."""
    cards = []
    for t in tools:
        pills = "".join(f'<span class="js-pill">{p}</span>' for p in t.get("pills", []))
        tint = t.get("tint", "#e8f6fb")
        fg = t.get("fg", "#0e7f9c")
        cards.append(f"""
  <a class="js-tool-card" href="{_href(t['href'], token)}" target="_self">
    <div class="js-tool-head">
      <div class="js-sq" style="background:{tint};color:{fg}">{t['icon']}</div>
      <div>
        <div class="js-tool-t">{t['title']}</div>
        <div class="js-tool-d">{t['desc']}</div>
      </div>
    </div>
    <div class="js-pills">{pills}</div>
    <div class="js-open">Open {t['title']} →</div>
  </a>""")
    return f'<div class="js-grid">{"".join(cards)}</div>'


def tool_card_html(t: dict) -> str:
    """A single module card's VISUAL (a <div>, not a link) — navigation is
    done by a client-side st.page_link rendered under it, so the session (and
    login) survives page changes. Non-navigating on its own."""
    pills = "".join(f'<span class="js-pill">{p}</span>' for p in t.get("pills", []))
    tint = t.get("tint", "#e8f6fb")
    fg = t.get("fg", "#0e7f9c")
    return f"""
<div class="js-tool-card" style="min-height:148px;">
  <div class="js-tool-head">
    <div class="js-sq" style="background:{tint};color:{fg}">{t['icon']}</div>
    <div>
      <div class="js-tool-t">{t['title']}</div>
      <div class="js-tool-d">{t['desc']}</div>
    </div>
  </div>
  <div class="js-pills">{pills}</div>
</div>"""


def pipeline_card_html(s: dict) -> str:
    """A single pipeline-strip card VISUAL (div; navigation via st.page_link)."""
    return f"""
<div class="js-pipe-card" style="min-height:96px;">
  <div class="js-sq" style="background:{s.get('tint', '#e8f6fb')};color:{s.get('fg', '#0e7f9c')}">{s['icon']}</div>
  <div class="js-pipe-t">{s['title']}</div>
  <div class="js-pipe-d">{s['desc']}</div>
</div>"""


def pipeline_cards_html(stages: list, token: str = "") -> str:
    """Top pipeline strip. Each stage dict: href, icon, title, desc, tint, fg."""
    cards = []
    for s in stages:
        cards.append(f"""
  <a class="js-pipe-card" href="{_href(s['href'], token)}" target="_self">
    <div class="js-sq" style="background:{s.get('tint', '#e8f6fb')};color:{s.get('fg', '#0e7f9c')}">{s['icon']}</div>
    <div class="js-pipe-t">{s['title']}<span class="js-arrow">→</span></div>
    <div class="js-pipe-d">{s['desc']}</div>
  </a>""")
    return f'<div class="js-pipe">{"".join(cards)}</div>'


def hero_html_v2(title: str, tagline: str, badge: str = "v2.0") -> str:
    return f"""
<div class="js-hero-wrap"><div style="display:flex;align-items:center;gap:18px;">
  <svg width="58" height="58" viewBox="0 0 100 100" aria-hidden="true">
    <defs><radialGradient id="jsHeroCore2" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#ffffff"/><stop offset="55%" stop-color="#22c3e6"/>
      <stop offset="100%" stop-color="#0e7f9c"/></radialGradient></defs>
    <circle cx="50" cy="50" r="31" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-dasharray="5 8" opacity="0.55"/>
    <circle cx="50" cy="50" r="21" fill="none" stroke="#0e7f9c" stroke-width="2.6" stroke-dasharray="24 10" stroke-linecap="round"/>
    <circle cx="50" cy="50" r="9" fill="url(#jsHeroCore2)"/></svg>
  <div>
    <div style="font-size:2.1rem;font-weight:800;letter-spacing:.4px;color:#12283b;font-family:{_SANS};">
      {title}<span class="js-badge">{badge}</span></div>
    <div class="js-hero-sub">{tagline}</div>
  </div>
</div></div>
"""


# ---------------------------------------------------------------------
# "How to use" step block (illustrated; real screenshots added later)
# ---------------------------------------------------------------------
def template_preview_png(df, title: str = "", max_cols: int = 6, max_rows: int = 3) -> bytes:
    """Render a styled table image of a tool's blank template — the 'this is
    what your input file should look like' visual used in the instructions."""
    import io as _io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = df.iloc[:max_rows, :max_cols].copy()
    for c in d.columns:
        d[c] = d[c].astype(str).map(lambda v: (v[:26] + "…") if len(v) > 27 else v)
    ncols, nrows = max(1, len(d.columns)), max(1, len(d))
    fig, ax = plt.subplots(figsize=(min(2.4 + 2.3 * ncols, 13), 1.0 + 0.55 * nrows), dpi=150)
    ax.axis("off")
    tbl = ax.table(cellText=d.values if len(d) else [[""] * ncols],
                   colLabels=list(d.columns), cellLoc="left", loc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.7)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#d6e3f2")
        if r == 0:
            cell.set_facecolor("#0e7f9c")
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor("#f2f8fc" if r % 2 else "#ffffff")
            cell.set_text_props(color="#12283b")
    if title:
        ax.set_title(title, loc="left", color="#12283b", fontsize=12, fontweight="bold", pad=12)
    fig.tight_layout()
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def text_preview_png(text: str, title: str = "") -> bytes:
    """Render a monospace snippet image (for file formats that aren't tables,
    e.g. a PubMed MEDLINE / RIS export)."""
    import io as _io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lines = text.strip("\n").split("\n")
    fig, ax = plt.subplots(figsize=(9, 0.55 + 0.28 * len(lines)), dpi=150)
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes,
                               facecolor="#f2f8fc", edgecolor="#d6e3f2"))
    ax.text(0.02, 0.94, "\n".join(lines), va="top", ha="left", family="monospace",
            fontsize=9.5, color="#12283b", transform=ax.transAxes)
    if title:
        ax.set_title(title, loc="left", color="#12283b", fontsize=12, fontweight="bold", pad=10)
    fig.tight_layout()
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def how_to_use(steps: list, preview_image: bytes = None, preview_caption: str = None):
    """Render a 'How to use' section: an optional input-format preview image
    followed by tool-specific numbered steps. `steps` is a list of
    (icon, title, description) tuples."""
    import streamlit as st

    st.markdown("### How to use this tool")
    if preview_image is not None:
        st.image(preview_image, caption=preview_caption or "What your input file should look like",
                 width="stretch")
    rows = []
    for i, (icon, title, desc) in enumerate(steps, start=1):
        rows.append(f"""
  <div class="js-step">
    <div class="js-step-n">{i}</div>
    <div class="js-step-ic">{icon}</div>
    <div class="js-step-b">
      <div class="js-step-t">{title}</div>
      <div class="js-step-d">{desc}</div>
    </div>
  </div>""")
    st.markdown(f'<div class="js-how">{"".join(rows)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Blank upload templates
# ---------------------------------------------------------------------
def enrichment_template_bytes() -> bytes:
    df = pd.DataFrame({
        "Sno": [1, 2],
        "Clean Title": [
            "Leaf miRNAs of Withania somnifera negatively regulate aging-associated genes",
            "Deep learning for medical image analysis: a survey",
        ],
        "DOI": ["10.1038/s41598-021-85123-4", "10.1038/s41591-022-01234-5"],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Enrichment Input")
    return buf.getvalue()


SCOPUS_INPUT_COLUMNS = [
    "EID", "TITLE", "Clean Title", "Authors", "Author(s) ID (synthetic)",
    "YEAR", "Journal", "DOI", "Citations", "Source Link",
    "Affliation", "Author_Affiliation_Map", "Corresponding Author",
    "Corresponding Author Email ID", "Abstract",
    "Author Keywords (Other Terms)", "MeSH Terms", "Concepts",
    "Grants", "References", "Publisher", "ISSN", "PMID",
    "Article Type", "Open Access",
    "Match Status", "Match Score", "Match Source",
    "Fetch Issues", "Reconciliation Notes",
]


def icmr_tagger_template_bytes() -> bytes:
    """Blank template for the ICMR Institute Tagger: the affiliation columns
    it scans, with one example row."""
    df = pd.DataFrame([{
        "Sno": 1,
        "Clean Title": "Example study title",
        "Affliation": "Dept of Virology, ICMR-National Institute of Virology, Pune, India; AIIMS, New Delhi",
        "First Author Affiliation": "ICMR-National Institute of Virology, Pune, India",
        "Corresponding Author Affiliation": "ICMR-National Institute of Virology, Pune, India",
        "Author_Affiliation_Map": '{"Sharma, Pooja": "ICMR-NIV, Pune", "Kumar, Anil": "AIIMS, New Delhi"}',
    }])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="ICMR Tagger Input")
    return buf.getvalue()


def fuzzy_titles_template_bytes() -> bytes:
    """Blank template for the Fuzzy Title Match tool: a single Title column.
    Use one file for de-duplication, or two such files to compare lists."""
    df = pd.DataFrame({"Title": [
        "Circulating tumor DNA in neuroblastoma",
        "Deep learning for medical image analysis: a survey",
        "Global burden of disease, 1990 to 2023",
    ]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Titles")
    return buf.getvalue()


def merge_example_bytes() -> bytes:
    """Example workbook for Merge Sheets: two sheets (A and B) sharing a DOI
    column. Upload each as its own file, or save these tabs separately."""
    a = pd.DataFrame({
        "DOI": ["10.1/aaa", "10.2/bbb", "10.3/ccc"],
        "Title": ["Paper A", "Paper B", "Paper C"],
        "Authors": ["Sharma P", "Kumar A", "Rao M"],
    })
    b = pd.DataFrame({
        "DOI": ["10.1/aaa", "10.2/bbb", "10.9/zzz"],
        "Citations": [12, 4, 30],
        "Journal": ["Nature", "Lancet", "Cell"],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        a.to_excel(xw, index=False, sheet_name="Sheet A")
        b.to_excel(xw, index=False, sheet_name="Sheet B")
    return buf.getvalue()


def _preview_from_bytes(template_bytes, title, sheet=0, max_cols=6):
    import io as _io
    df = pd.read_excel(_io.BytesIO(template_bytes), sheet_name=sheet)
    return template_preview_png(df, title, max_cols=max_cols)


def enrichment_preview():
    return _preview_from_bytes(enrichment_template_bytes(), "Your file: Sno · Clean Title · DOI")


def icmr_tagger_preview():
    return _preview_from_bytes(icmr_tagger_template_bytes(),
                               "Your file: affiliation columns (Affliation, First/Corresponding Author Affiliation…)")


def fuzzy_preview():
    return _preview_from_bytes(fuzzy_titles_template_bytes(), "Your file: a Title column")


def merge_preview():
    return _preview_from_bytes(merge_example_bytes(), "One of your two sheets (join on a shared column)",
                               sheet="Sheet A")


def scientometrics_preview():
    return _preview_from_bytes(scopus_input_template_bytes(),
                               "Your file: an enriched dataset (TITLE, Authors, DOI, Citations…)", max_cols=7)


def convert_citations_preview():
    return text_preview_png(
        "PMID- 39593169\n"
        "TI  - Personalized circulating tumor DNA analysis in neuroblastoma.\n"
        "AU  - Sharma P\n"
        "AU  - Kumar A\n"
        "DP  - 2024\n"
        "TA  - Sci Rep\n"
        "AID - 10.1186/s40364-024-00688-5 [doi]",
        "PubMed MEDLINE export (.txt) — one tag per line (RIS looks similar with TY/TI/AU/DO)")


def scopus_input_template_bytes() -> bytes:
    example = {
        "EID": "2-s2.0-12345678901",
        "TITLE": "Circulating tumor DNA in neuroblastoma",
        "Clean Title": "circulating tumor dna in neuroblastoma",
        "Authors": "Sharma, Pooja; Kumar, Anil",
        "Author(s) ID (synthetic)": "11122233344; 55566677788",
        "YEAR": "2024",
        "Journal": "Pediatric Blood & Cancer",
        "DOI": "10.1002/pbc.28311",
        "Citations": "12",
        "Source Link": "https://doi.org/10.1002/pbc.28311",
        "Affliation": "Dept of Oncology, ICMR-NIV, Pune, India",
        "Author_Affiliation_Map": '{"Sharma, Pooja": "ICMR-NIV, Pune", "Kumar, Anil": "AIIMS, New Delhi"}',
        "Corresponding Author": "Sharma, Pooja",
        "Corresponding Author Email ID": "pooja@example.org",
        "Abstract": "Example abstract text.",
        "Author Keywords (Other Terms)": "ctDNA; liquid biopsy",
        "MeSH Terms": "Neuroblastoma; DNA, Neoplasm",
        "Concepts": "oncology; genetics",
        "Grants": "ICMR grant 12345",
        "References": "Ref 1; Ref 2",
        "Publisher": "Wiley",
        "ISSN": "1545-5017",
        "PMID": "29923838",
        "Article Type": "journal-article",
        "Open Access": "Yes",
        "Match Status": "Auto-accepted",
        "Match Score": "98",
        "Match Source": "Crossref",
        "Fetch Issues": "",
        "Reconciliation Notes": "",
    }
    df = pd.DataFrame([{c: example.get(c, "") for c in SCOPUS_INPUT_COLUMNS}])[SCOPUS_INPUT_COLUMNS]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name="Scopus Converter Input")
    return buf.getvalue()
