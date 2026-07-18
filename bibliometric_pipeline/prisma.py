"""
prisma.py
=========
PRISMA 2020 flow diagram generator (the "identification of studies via
databases and registers" template — the version used by most new systematic
reviews). Publication-ready matplotlib figure + a matching DiagrammeR R script.

Key PRISMA-2020 specifics vs the old 2009 flow:
  - a dedicated "Records removed before screening" box (duplicates, automation-
    flagged ineligible, other) in the Identification row;
  - "Reports" wording (sought for retrieval / assessed) instead of
    "full-text articles";
  - "Studies included" + "Reports of included studies" in the final box.
"""
from __future__ import annotations

import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK = "#12283b"
BORDER = "#33566f"
FILL = "#ffffff"
BAND = "#0e7f9c"       # stage band
BAND_TX = "#ffffff"
ARROW = "#33566f"

# Field spec: (key, label, default) — drives the on-page form.
FIELDS = [
    ("databases", "Records identified — Databases (n)", 1200),
    ("registers", "Records identified — Registers (n)", 25),
    ("dup_removed", "Duplicate records removed (n)", 290),
    ("auto_ineligible", "Records marked ineligible by automation tools (n)", 0),
    ("other_removed", "Records removed for other reasons (n)", 10),
    ("screened", "Records screened (n)", 925),
    ("records_excluded", "Records excluded after screening (n)", 780),
    ("sought", "Reports sought for retrieval (n)", 145),
    ("not_retrieved", "Reports not retrieved (n)", 5),
    ("assessed", "Reports assessed for eligibility (n)", 140),
    ("studies_included", "Studies included in review (n)", 45),
    ("reports_included", "Reports of included studies (n)", 50),
]

EXAMPLE_REASONS = [("Wrong population", 40), ("Wrong intervention/comparator", 30),
                   ("Wrong outcome", 15), ("No extractable data", 10)]

# Optional second identification stream ("other methods") for the two-stream 2020 diagram.
OM_FIELDS = [
    ("om_websites", "Other methods — Websites (n)", 10),
    ("om_orgs", "Other methods — Organisations (n)", 5),
    ("om_citation", "Other methods — Citation searching (n)", 20),
    ("om_sought", "Other methods — Reports sought for retrieval (n)", 30),
    ("om_not_retrieved", "Other methods — Reports not retrieved (n)", 3),
    ("om_assessed", "Other methods — Reports assessed for eligibility (n)", 27),
]
EXAMPLE_OM_REASONS = [("Wrong outcome", 8), ("No extractable data", 4)]


def _box(ax, cx, cy, w, h, text, fs=10.5, fill=FILL, tc=INK, align="center"):
    ax.add_patch(FancyBboxPatch((cx - w/2, cy - h/2), w, h,
                                boxstyle="round,pad=0.004,rounding_size=0.010",
                                linewidth=1.2, edgecolor=BORDER, facecolor=fill, zorder=2))
    ha = {"center": "center", "left": "left"}[align]
    tx = cx if align == "center" else cx - w/2 + 0.012
    ax.text(tx, cy, text, ha=ha, va="center", fontsize=fs, color=tc, zorder=3,
            linespacing=1.35)


def _arrow(ax, x1, y1, x2, y2):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=16,
                                 lw=1.3, color=ARROW, zorder=1, shrinkA=0, shrinkB=0))


def _band(ax, cy, h, label):
    ax.add_patch(FancyBboxPatch((0.005, cy - h/2), 0.055, h,
                                boxstyle="round,pad=0.002,rounding_size=0.008",
                                linewidth=0, facecolor=BAND, zorder=2))
    ax.text(0.032, cy, label, ha="center", va="center", rotation=90,
            fontsize=11.5, fontweight="bold", color=BAND_TX, zorder=3)


def flow_png(d, reasons=None, title="PRISMA 2020 flow diagram"):
    reasons = reasons if reasons is not None else EXAMPLE_REASONS
    g = lambda k: int(d.get(k, 0) or 0)

    fig = plt.figure(figsize=(11.2, 12.4), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    mx, mw = 0.36, 0.40      # main column centre / width
    sx, sw = 0.80, 0.32      # side (excluded) column centre / width

    # y-centres
    yA, yB, yC, yD, yE = 0.885, 0.660, 0.500, 0.335, 0.120

    # stage bands
    _band(ax, (yA + 0.055 + yA - 0.055)/2, 0.16, "Identification")  # around A
    _band(ax, (yB + yD)/2, 0.40, "Screening")
    _band(ax, yE, 0.13, "Included")

    # ---- Identification ----
    _box(ax, mx, yA, mw, 0.11,
         f"Records identified from:\nDatabases  (n = {g('databases')})\nRegisters  (n = {g('registers')})",
         align="left")
    _box(ax, sx, yA, sw, 0.13,
         "Records removed before screening:\n"
         f"Duplicate records removed  (n = {g('dup_removed')})\n"
         f"Records marked as ineligible by\nautomation tools  (n = {g('auto_ineligible')})\n"
         f"Records removed for other\nreasons  (n = {g('other_removed')})",
         fs=9.3, align="left")
    _arrow(ax, mx + mw/2, yA, sx - sw/2, yA)

    # ---- Screening ----
    _box(ax, mx, yB, mw, 0.075, f"Records screened\n(n = {g('screened')})")
    _box(ax, sx, yB, sw, 0.065, f"Records excluded\n(n = {g('records_excluded')})", align="left")
    _arrow(ax, mx + mw/2, yB, sx - sw/2, yB)
    _arrow(ax, mx, yA - 0.055, mx, yB + 0.038)

    _box(ax, mx, yC, mw, 0.075, f"Reports sought for retrieval\n(n = {g('sought')})")
    _box(ax, sx, yC, sw, 0.065, f"Reports not retrieved\n(n = {g('not_retrieved')})", align="left")
    _arrow(ax, mx + mw/2, yC, sx - sw/2, yC)
    _arrow(ax, mx, yB - 0.038, mx, yC + 0.038)

    reason_txt = "Reports excluded:\n" + "\n".join(f"{r}  (n = {n})" for r, n in reasons)
    rh = 0.045 + 0.024*len(reasons)
    _box(ax, mx, yD, mw, 0.075, f"Reports assessed for eligibility\n(n = {g('assessed')})")
    _box(ax, sx, yD, sw, rh, reason_txt, fs=9.3, align="left")
    _arrow(ax, mx + mw/2, yD, sx - sw/2, yD)
    _arrow(ax, mx, yC - 0.038, mx, yD + 0.038)

    # ---- Included ----
    _box(ax, mx, yE, mw, 0.095,
         f"Studies included in review\n(n = {g('studies_included')})\n"
         f"Reports of included studies\n(n = {g('reports_included')})")
    _arrow(ax, mx, yD - 0.038, mx, yE + 0.048)

    fig.text(0.5, 0.985, title, ha="center", va="top", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.99, 0.008, "Jarvis Scholar", ha="right", va="bottom", fontsize=8,
             color="#9fb0c4", style="italic")

    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=200, bbox_inches="tight",
                                    facecolor="white"); plt.close(fig)
    return buf.getvalue()


def flow_png_2stream(d, om, reasons=None, om_reasons=None, title="PRISMA 2020 flow diagram"):
    """Two-stream PRISMA 2020: 'databases & registers' (left) + 'other methods'
    (right, websites / organisations / citation searching), both feeding the
    single 'studies included' box."""
    reasons = reasons if reasons is not None else EXAMPLE_REASONS
    om_reasons = om_reasons if om_reasons is not None else EXAMPLE_OM_REASONS
    g = lambda k: int(d.get(k, 0) or 0)
    go = lambda k: int(om.get(k, 0) or 0)

    fig = plt.figure(figsize=(15.6, 12.6), dpi=200)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    mxL, mwL = 0.205, 0.23      # left main
    sxL, swL = 0.405, 0.165     # left excluded
    mxR, mwR = 0.665, 0.23      # right main
    sxR, swR = 0.865, 0.165     # right excluded
    xE = (mxL + mxR) / 2        # included box centre

    yA, yB, yC, yD, yE = 0.855, 0.640, 0.490, 0.335, 0.105

    _band(ax, yA, 0.15, "Identification")
    _band(ax, (yB + yD)/2, 0.36, "Screening")
    _band(ax, yE, 0.12, "Included")

    # stream titles
    fig.text((mxL + sxL)/2, 0.965, "Identification of new studies via databases and registers",
             ha="center", va="center", fontsize=12, fontweight="bold", color=INK)
    fig.text((mxR + sxR)/2, 0.965, "Identification of studies via other methods",
             ha="center", va="center", fontsize=12, fontweight="bold", color=INK)

    # ---- LEFT stream (databases & registers) ----
    _box(ax, mxL, yA, mwL, 0.10,
         f"Records identified from:\nDatabases  (n = {g('databases')})\nRegisters  (n = {g('registers')})",
         fs=10, align="left")
    _box(ax, sxL, yA, swL, 0.12,
         "Records removed before\nscreening:\n"
         f"Duplicates removed  (n = {g('dup_removed')})\n"
         f"Automation-ineligible  (n = {g('auto_ineligible')})\n"
         f"Other reasons  (n = {g('other_removed')})", fs=8.6, align="left")
    _arrow(ax, mxL + mwL/2, yA, sxL - swL/2, yA)

    _box(ax, mxL, yB, mwL, 0.07, f"Records screened\n(n = {g('screened')})", fs=10)
    _box(ax, sxL, yB, swL, 0.06, f"Records excluded\n(n = {g('records_excluded')})", fs=9, align="left")
    _arrow(ax, mxL + mwL/2, yB, sxL - swL/2, yB)
    _arrow(ax, mxL, yA - 0.05, mxL, yB + 0.036)

    _box(ax, mxL, yC, mwL, 0.07, f"Reports sought for retrieval\n(n = {g('sought')})", fs=10)
    _box(ax, sxL, yC, swL, 0.06, f"Reports not retrieved\n(n = {g('not_retrieved')})", fs=9, align="left")
    _arrow(ax, mxL + mwL/2, yC, sxL - swL/2, yC)
    _arrow(ax, mxL, yB - 0.036, mxL, yC + 0.036)

    rtxtL = "Reports excluded:\n" + "\n".join(f"{r}  (n = {n})" for r, n in reasons)
    _box(ax, mxL, yD, mwL, 0.07, f"Reports assessed for eligibility\n(n = {g('assessed')})", fs=10)
    _box(ax, sxL, yD, swL, 0.05 + 0.022*len(reasons), rtxtL, fs=8.6, align="left")
    _arrow(ax, mxL + mwL/2, yD, sxL - swL/2, yD)
    _arrow(ax, mxL, yC - 0.036, mxL, yD + 0.036)

    # ---- RIGHT stream (other methods) ----
    _box(ax, mxR, yA, mwR, 0.10,
         f"Records identified from:\nWebsites  (n = {go('om_websites')})\n"
         f"Organisations  (n = {go('om_orgs')})\nCitation searching  (n = {go('om_citation')})",
         fs=10, align="left")
    _box(ax, mxR, yC, mwR, 0.07, f"Reports sought for retrieval\n(n = {go('om_sought')})", fs=10)
    _box(ax, sxR, yC, swR, 0.06, f"Reports not retrieved\n(n = {go('om_not_retrieved')})", fs=9, align="left")
    _arrow(ax, mxR + mwR/2, yC, sxR - swR/2, yC)
    _arrow(ax, mxR, yA - 0.05, mxR, yC + 0.036)

    rtxtR = "Reports excluded:\n" + "\n".join(f"{r}  (n = {n})" for r, n in om_reasons)
    _box(ax, mxR, yD, mwR, 0.07, f"Reports assessed for eligibility\n(n = {go('om_assessed')})", fs=10)
    _box(ax, sxR, yD, swR, 0.05 + 0.022*len(om_reasons), rtxtR, fs=8.6, align="left")
    _arrow(ax, mxR + mwR/2, yD, sxR - swR/2, yD)
    _arrow(ax, mxR, yC - 0.036, mxR, yD + 0.036)

    # ---- Included (fed by both streams) ----
    _box(ax, xE, yE, 0.30, 0.09,
         f"Studies included in review  (n = {g('studies_included')})\n"
         f"Reports of included studies  (n = {g('reports_included')})", fs=10.5)
    _arrow(ax, mxL, yD - 0.036, xE - 0.06, yE + 0.045)
    _arrow(ax, mxR, yD - 0.036, xE + 0.06, yE + 0.045)

    fig.text(0.5, 0.992, title, ha="center", va="top", fontsize=15, fontweight="bold", color=INK)
    fig.text(0.995, 0.006, "Jarvis Scholar", ha="right", va="bottom", fontsize=8,
             color="#9fb0c4", style="italic")
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=200, bbox_inches="tight",
                                    facecolor="white"); plt.close(fig)
    return buf.getvalue()


def r_script(d, reasons=None, om=None, om_reasons=None):
    """Matching PRISMA2020-style flow via DiagrammeR (reviewer-familiar).
    Pass `om` (+ `om_reasons`) to add the second 'other methods' stream."""
    reasons = reasons if reasons is not None else EXAMPLE_REASONS
    g = lambda k: int(d.get(k, 0) or 0)
    rlines = "\\n".join(f"{r} (n = {n})" for r, n in reasons)
    om_nodes = om_edges = ""
    if om:
        om_reasons = om_reasons if om_reasons is not None else EXAMPLE_OM_REASONS
        go = lambda k: int(om.get(k, 0) or 0)
        orlines = "\\n".join(f"{r} (n = {n})" for r, n in om_reasons)
        om_nodes = f'''
  oa [label = 'Records identified from:\\nWebsites (n = {go('om_websites')})\\nOrganisations (n = {go('om_orgs')})\\nCitation searching (n = {go('om_citation')})']
  oc [label = 'Reports sought for retrieval (n = {go('om_sought')})']
  oc2[label = 'Reports not retrieved (n = {go('om_not_retrieved')})']
  od [label = 'Reports assessed for eligibility (n = {go('om_assessed')})']
  od2[label = 'Reports excluded:\\n{orlines}']'''
        om_edges = '''
  oa -> oc; oc -> od; od -> e
  oc -> oc2; od -> od2
  { rank = same; oc oc2 } { rank = same; od od2 }'''
    return f'''# PRISMA 2020 flow diagram — reproduce in RStudio
# install.packages("DiagrammeR")
library(DiagrammeR)
grViz("
digraph prisma {{
  graph [layout = dot, rankdir = TB, fontname = Helvetica]
  node  [shape = box, style = filled, fillcolor = white, fontname = Helvetica]

  a  [label = 'Records identified from:\\nDatabases (n = {g('databases')})\\nRegisters (n = {g('registers')})']
  a2 [label = 'Records removed before screening:\\nDuplicates (n = {g('dup_removed')})\\nAutomation-ineligible (n = {g('auto_ineligible')})\\nOther reasons (n = {g('other_removed')})']
  b  [label = 'Records screened (n = {g('screened')})']
  b2 [label = 'Records excluded (n = {g('records_excluded')})']
  c  [label = 'Reports sought for retrieval (n = {g('sought')})']
  c2 [label = 'Reports not retrieved (n = {g('not_retrieved')})']
  d  [label = 'Reports assessed for eligibility (n = {g('assessed')})']
  d2 [label = 'Reports excluded:\\n{rlines}']
  e  [label = 'Studies included in review (n = {g('studies_included')})\\nReports of included studies (n = {g('reports_included')})']{om_nodes}

  a -> b; b -> c; c -> d; d -> e
  a -> a2; b -> b2; c -> c2; d -> d2
  {{ rank = same; a a2 }} {{ rank = same; b b2 }} {{ rank = same; c c2 }} {{ rank = same; d d2 }}{om_edges}
}}
")
'''
