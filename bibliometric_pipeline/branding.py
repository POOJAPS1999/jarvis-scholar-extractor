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

_SANS = "'Segoe UI', 'Helvetica Neue', Arial, system-ui, sans-serif"
_SERIF = "Georgia, 'Times New Roman', 'Iowan Old Style', serif"

# ---------------------------------------------------------------------
# Global theme CSS
# ---------------------------------------------------------------------
THEME_CSS = f"""
<style>
:root {{
  --js-cyan: #0e7f9c;
  --js-cyan-soft: #7fd3e6;
  --js-indigo: #4f46e5;
  --js-ink: #12283b;
  --js-sub: #4a627a;
  --js-line: #d6e3f2;
  --js-panel: #ffffff;
  --js-bg: #eff5fc;
}}
.stApp {{
  background:
    radial-gradient(1100px 520px at 12% -8%, rgba(79,70,229,0.06), transparent 60%),
    radial-gradient(900px 460px at 100% 0%, rgba(14,127,156,0.08), transparent 55%),
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
def feature_cards_html(tools: list) -> str:
    """tools: list of dicts with keys href, icon, title, desc, tag.
    The whole card is an <a> so clicking anywhere navigates to the tool."""
    cards = []
    for t in tools:
        cards.append(f"""
  <a class="js-card" href="{t['href']}" target="_self">
    <div class="js-ic-wrap">{t['icon']}</div>
    <div class="js-title">{t['title']}</div>
    <div class="js-desc">{t['desc']}</div>
    <div class="js-tag">{t['tag']}</div>
    <div class="js-cta">Open {t['title']} →</div>
  </a>""")
    return f'<div class="js-grid">{"".join(cards)}</div>'


# ---------------------------------------------------------------------
# "How to use" step block (illustrated; real screenshots added later)
# ---------------------------------------------------------------------
def how_to_use(steps: list, shot_hint: bool = True):
    """Render a 'How to use' section. `steps` is a list of (icon, title,
    description) tuples. Call inside a Streamlit page (uses st)."""
    import streamlit as st

    st.markdown("### How to use this tool")
    rows = []
    for i, (icon, title, desc) in enumerate(steps, start=1):
        shot = ('<div class="js-shot">🖼 Step screenshot coming soon</div>' if shot_hint else "")
        rows.append(f"""
  <div class="js-step">
    <div class="js-step-n">{i}</div>
    <div class="js-step-ic">{icon}</div>
    <div class="js-step-b">
      <div class="js-step-t">{title}</div>
      <div class="js-step-d">{desc}</div>
      {shot}
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
