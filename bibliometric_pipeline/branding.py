"""
branding.py
===========
Shared visual identity for the Jarvis Scholar dashboard: the sci-fi CSS
theme, an animated "arc-reactor" loading icon (a nod to Jarvis, built from
scratch as inline SVG/CSS — no copyrighted assets), and blank-template
generators so users can download a correctly-formatted upload file.

All strings are plain HTML/CSS injected via st.markdown(..., unsafe_allow_html=True).
"""
from __future__ import annotations

import io

import pandas as pd

# ---------------------------------------------------------------------
# Global theme CSS (injected once per page)
# ---------------------------------------------------------------------
THEME_CSS = """
<style>
:root {
  --js-cyan: #22d3ee;
  --js-blue: #3b82f6;
  --js-deep: #0a0f1e;
  --js-panel: #111a30;
  --js-line: rgba(34, 211, 238, 0.25);
}
.stApp {
  background:
    radial-gradient(1200px 600px at 15% -10%, rgba(59,130,246,0.10), transparent 60%),
    radial-gradient(900px 500px at 100% 0%, rgba(34,211,238,0.08), transparent 55%),
    var(--js-deep);
}
/* Feature tiles */
.js-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 16px; margin: 8px 0 4px; }
.js-card {
  position: relative; border: 1px solid var(--js-line); border-radius: 14px;
  padding: 18px 18px 16px; background: linear-gradient(180deg, rgba(17,26,48,0.85), rgba(10,15,30,0.85));
  box-shadow: 0 0 0 1px rgba(34,211,238,0.04), 0 10px 30px rgba(0,0,0,0.35);
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease; height: 100%;
}
.js-card:hover { transform: translateY(-3px); border-color: var(--js-cyan);
  box-shadow: 0 0 22px rgba(34,211,238,0.18), 0 14px 34px rgba(0,0,0,0.45); }
.js-ic { font-size: 30px; line-height: 1; }
.js-title { font-weight: 700; letter-spacing: .3px; margin: 8px 0 4px; color: #eaf6ff; font-size: 1.05rem; }
.js-desc { color: #9fb4d4; font-size: .86rem; line-height: 1.4; }
.js-tag { display:inline-block; margin-top:10px; font-size:.68rem; letter-spacing:.12em;
  text-transform:uppercase; color: var(--js-cyan); border:1px solid var(--js-line);
  border-radius: 999px; padding: 2px 9px; }
.js-hero-sub { color:#9fb4d4; font-size:.95rem; letter-spacing:.02em; }
hr { border-color: var(--js-line) !important; }
</style>
"""

# ---------------------------------------------------------------------
# Animated arc-reactor loader
# ---------------------------------------------------------------------
def reactor_loader_html(label: str = "JARVIS is working…", size: int = 96) -> str:
    """A small glowing, rotating 'arc reactor' loader. Two counter-rotating
    rings, a pulsing core, and orbiting nodes — a cute Jarvis-style 'thinking'
    indicator, drawn from scratch (no copyrighted imagery)."""
    return f"""
<div style="display:flex;align-items:center;gap:16px;margin:10px 0;">
  <svg width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="loading">
    <defs>
      <radialGradient id="jsCore" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#e6fbff"/>
        <stop offset="45%" stop-color="#22d3ee"/>
        <stop offset="100%" stop-color="#0e7490"/>
      </radialGradient>
      <filter id="jsGlow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="2.2" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
    </defs>
    <g filter="url(#jsGlow)">
      <circle cx="50" cy="50" r="30" fill="none" stroke="#3b82f6" stroke-width="2"
              stroke-dasharray="6 9" opacity="0.75">
        <animateTransform attributeName="transform" type="rotate" from="0 50 50"
                          to="360 50 50" dur="3.2s" repeatCount="indefinite"/>
      </circle>
      <circle cx="50" cy="50" r="22" fill="none" stroke="#22d3ee" stroke-width="2.4"
              stroke-dasharray="26 12" stroke-linecap="round" opacity="0.9">
        <animateTransform attributeName="transform" type="rotate" from="360 50 50"
                          to="0 50 50" dur="1.8s" repeatCount="indefinite"/>
      </circle>
      <g>
        <animateTransform attributeName="transform" type="rotate" from="0 50 50"
                          to="360 50 50" dur="2.4s" repeatCount="indefinite"/>
        <circle cx="50" cy="22" r="2.4" fill="#8be9ff"/>
        <circle cx="78" cy="50" r="2.0" fill="#8be9ff"/>
        <circle cx="50" cy="78" r="2.4" fill="#8be9ff"/>
        <circle cx="22" cy="50" r="2.0" fill="#8be9ff"/>
      </g>
      <circle cx="50" cy="50" r="10" fill="url(#jsCore)">
        <animate attributeName="r" values="9;11.5;9" dur="1.4s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.85;1;0.85" dur="1.4s" repeatCount="indefinite"/>
      </circle>
    </g>
  </svg>
  <div>
    <div style="color:#22d3ee;font-weight:700;letter-spacing:.06em;font-family:monospace;">{label}</div>
    <div style="color:#7f97ba;font-size:.8rem;font-family:monospace;">standby · processing telemetry</div>
  </div>
</div>
"""


def hero_html(title: str, tagline: str) -> str:
    return f"""
<div style="display:flex;align-items:center;gap:18px;margin:2px 0 6px;">
  <svg width="58" height="58" viewBox="0 0 100 100" aria-hidden="true">
    <defs><radialGradient id="jsHeroCore" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="#e6fbff"/><stop offset="55%" stop-color="#22d3ee"/>
      <stop offset="100%" stop-color="#0e7490"/></radialGradient></defs>
    <circle cx="50" cy="50" r="30" fill="none" stroke="#3b82f6" stroke-width="2" stroke-dasharray="5 8" opacity="0.7"/>
    <circle cx="50" cy="50" r="21" fill="none" stroke="#22d3ee" stroke-width="2.5" stroke-dasharray="24 10" stroke-linecap="round"/>
    <circle cx="50" cy="50" r="9" fill="url(#jsHeroCore)"/>
  </svg>
  <div>
    <div style="font-size:1.9rem;font-weight:800;letter-spacing:.5px;color:#eaf6ff;font-family:monospace;">{title}</div>
    <div class="js-hero-sub">{tagline}</div>
  </div>
</div>
"""


# ---------------------------------------------------------------------
# Blank upload templates
# ---------------------------------------------------------------------
def enrichment_template_bytes() -> bytes:
    """Blank .xlsx with the exact columns the Data Enrichment tool needs,
    plus two example rows the user can overwrite/delete."""
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
