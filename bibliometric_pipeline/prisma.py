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


def r_script(d, reasons=None):
    """Matching PRISMA2020-style flow via DiagrammeR (reviewer-familiar)."""
    reasons = reasons if reasons is not None else EXAMPLE_REASONS
    g = lambda k: int(d.get(k, 0) or 0)
    rlines = "\\n".join(f"{r} (n = {n})" for r, n in reasons)
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
  e  [label = 'Studies included in review (n = {g('studies_included')})\\nReports of included studies (n = {g('reports_included')})']

  a -> b; b -> c; c -> d; d -> e
  a -> a2; b -> b2; c -> c2; d -> d2
  {{ rank = same; a a2 }} {{ rank = same; b b2 }} {{ rank = same; c c2 }} {{ rank = same; d d2 }}
}}
")
'''
