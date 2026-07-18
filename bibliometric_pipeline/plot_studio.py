"""
plot_studio.py
==============
Jarvis Scholar — No-Code Scientific Plot Studio.

One engine, many plots. Every plot is a `PlotSpec` in `REGISTRY` describing:
  - the Excel template columns the user fills,
  - example rows (used to generate the downloadable template),
  - a matplotlib renderer  render(df, opt) -> Figure.

The page code only ever talks to the registry + a few helpers, so adding a
new plot = one spec + one renderer, and everything else (template download,
upload validation, publication styling, watermark, high-res PNG, AI caption)
is reused.

Design choices:
  - matplotlib (Agg) static output -> publication-ready + reliable PNG.
  - heavy/optional libs (scipy, sklearn, statsmodels, lifelines, seaborn,
    squarify) are imported LAZILY inside their renderer, so a missing lib
    only affects that one plot, never the whole app.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable, List, Tuple

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# ---------------------------------------------------------------------------
# Options passed from the UI (all optional; renderers read what they need)
# ---------------------------------------------------------------------------
@dataclass
class PlotOptions:
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    palette: str = "Jarvis"            # named palette (see PALETTES)
    figsize: Tuple[float, float] = (8.0, 5.0)
    dpi: int = 200
    logx: bool = False
    logy: bool = False
    grid: bool = True
    legend: bool = True
    annotate: bool = True              # value labels / stat annotations where relevant
    watermark: bool = True


@dataclass
class Column:
    name: str
    kind: str = "number"               # "number" | "text" | "int"
    required: bool = True
    help: str = ""


@dataclass
class PlotSpec:
    id: str
    name: str
    category: str
    desc: str
    columns: List[Column]
    example: dict                       # {col: [values...]} -> template rows
    render: Callable[[pd.DataFrame, PlotOptions], Figure]
    notes: str = ""
    tags: List[str] = field(default_factory=list)


REGISTRY: "dict[str, PlotSpec]" = {}


def register(spec: PlotSpec):
    REGISTRY[spec.id] = spec
    return spec


def by_category() -> "dict[str, list[PlotSpec]]":
    out: "dict[str, list[PlotSpec]]" = {}
    for s in REGISTRY.values():
        out.setdefault(s.category, []).append(s)
    return out


# ---------------------------------------------------------------------------
# Palettes + publication styling
# ---------------------------------------------------------------------------
PALETTES = {
    "Jarvis":    ["#2563eb", "#1d9e75", "#d8572a", "#7d3c98", "#0e8a8a",
                  "#c0398b", "#e0a100", "#41566b"],
    "Vibrant":   ["#4361ee", "#f72585", "#4cc9f0", "#7209b7", "#f8961e",
                  "#43aa8b", "#577590", "#90be6d"],
    "Colorblind":["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
                  "#D55E00", "#F0E442", "#999999"],
    "Grayscale": ["#222222", "#555555", "#888888", "#aaaaaa", "#333333",
                  "#666666", "#999999", "#bbbbbb"],
}


def palette(opt: PlotOptions, n: int = 8) -> List[str]:
    cols = PALETTES.get(opt.palette, PALETTES["Jarvis"])
    if n <= len(cols):
        return cols[:n]
    reps = (n // len(cols)) + 1
    return (cols * reps)[:n]


def new_fig(opt: PlotOptions):
    fig, ax = plt.subplots(figsize=opt.figsize, dpi=opt.dpi)
    return fig, ax


def style_axes(ax, opt: PlotOptions, default_x="", default_y=""):
    if opt.title:
        ax.set_title(opt.title, fontsize=14, fontweight="bold", color="#12283b", pad=12)
    ax.set_xlabel(opt.xlabel or default_x, fontsize=11, color="#41566b")
    ax.set_ylabel(opt.ylabel or default_y, fontsize=11, color="#41566b")
    if opt.logx:
        ax.set_xscale("log")
    if opt.logy:
        ax.set_yscale("log")
    if opt.grid:
        ax.grid(True, which="major", color="#e6edf5", linewidth=0.9, zorder=0)
        ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3d0dd")
    ax.tick_params(colors="#41566b", labelsize=9.5)


def finish(fig, ax, opt: PlotOptions, default_x="", default_y="", legend_ok=True):
    style_axes(ax, opt, default_x, default_y)
    if opt.legend and legend_ok and ax.get_legend_handles_labels()[0]:
        ax.legend(frameon=False, fontsize=9)
    if opt.watermark:
        fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom",
                 fontsize=8, color="#b8c6d6", alpha=0.8, style="italic")
    fig.tight_layout()
    return fig


def fig_to_png(fig, dpi: int = 200) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Excel template generation (per plot)
# ---------------------------------------------------------------------------
def template_bytes(spec: PlotSpec) -> bytes:
    """Build a plot-specific .xlsx: a Data sheet (headers + example rows) and
    an Instructions sheet describing each column."""
    data = pd.DataFrame({c.name: spec.example.get(c.name, []) for c in spec.columns})
    info = pd.DataFrame(
        {"Column": [c.name for c in spec.columns],
         "Type": [c.kind for c in spec.columns],
         "Required": ["Yes" if c.required else "Optional" for c in spec.columns],
         "What to enter": [c.help for c in spec.columns]}
    )
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        data.to_excel(xl, sheet_name="Data", index=False)
        info.to_excel(xl, sheet_name="Instructions", index=False)
    return buf.getvalue()


def validate(spec: PlotSpec, df: pd.DataFrame) -> "list[str]":
    """Return a list of human-friendly problems (empty = OK)."""
    problems = []
    cols = {c.strip().lower(): c for c in df.columns}
    for c in spec.columns:
        if c.required and c.name.strip().lower() not in cols:
            problems.append(f"Missing required column '{c.name}'.")
    if df.dropna(how="all").empty:
        problems.append("The Data sheet is empty.")
    return problems


def _col(df: pd.DataFrame, name: str):
    """Case-insensitive column fetch."""
    for c in df.columns:
        if c.strip().lower() == name.strip().lower():
            return df[c]
    return None


def _num(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


# ---------------------------------------------------------------------------
# Helpers for non-cartesian plots
# ---------------------------------------------------------------------------
def bare_finish(fig, opt: PlotOptions, ax=None):
    if opt.title and ax is not None:
        ax.set_title(opt.title, fontsize=14, fontweight="bold", color="#12283b", pad=12)
    elif opt.title:
        fig.suptitle(opt.title, fontsize=14, fontweight="bold", color="#12283b")
    if opt.watermark:
        fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom",
                 fontsize=8, color="#b8c6d6", alpha=0.8, style="italic")
    fig.tight_layout()
    return fig


def _groups(series):
    return [g for g in pd.unique(series.dropna())]


# ===========================================================================
# CATEGORY 1 — DISTRIBUTION
# ===========================================================================
def r_histogram(df, opt):
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    if g is not None:
        for i, grp in enumerate(_groups(g)):
            ax.hist(_num(v[g == grp]).dropna(), bins=20, alpha=0.6,
                    color=palette(opt)[i], label=str(grp), edgecolor="white")
    else:
        ax.hist(_num(v).dropna(), bins=20, color=palette(opt)[0], edgecolor="white")
    return finish(fig, ax, opt, "Value", "Frequency")

register(PlotSpec("histogram", "Histogram", "1. Distribution",
    "Frequency distribution of a numeric variable.",
    [Column("Value", "number", True, "The numeric measurements"),
     Column("Group", "text", False, "Optional group to overlay")],
    {"Value": [12, 15, 14, 18, 21, 13, 16, 19, 17, 20], "Group": ["A"]*5 + ["B"]*5},
    r_histogram))


def r_kde(df, opt):
    from scipy.stats import gaussian_kde
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    def _plot(vals, color, label=None):
        vals = _num(vals).dropna().values
        if len(vals) < 2:
            return
        xs = np.linspace(vals.min(), vals.max(), 200)
        ax.fill_between(xs, gaussian_kde(vals)(xs), alpha=0.35, color=color)
        ax.plot(xs, gaussian_kde(vals)(xs), color=color, lw=2, label=label)
    if g is not None:
        for i, grp in enumerate(_groups(g)):
            _plot(v[g == grp], palette(opt)[i], str(grp))
    else:
        _plot(v, palette(opt)[0])
    return finish(fig, ax, opt, "Value", "Density")

register(PlotSpec("kde", "Density (KDE)", "1. Distribution",
    "Smoothed probability density of a numeric variable.",
    [Column("Value", "number", True, "Numeric measurements"),
     Column("Group", "text", False, "Optional group overlay")],
    {"Value": [12, 15, 14, 18, 21, 13, 16, 19, 17, 20], "Group": ["A"]*5 + ["B"]*5},
    r_kde))


def r_box(df, opt):
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    if g is not None:
        grps = _groups(g)
        data = [_num(v[g == grp]).dropna().values for grp in grps]
        bp = ax.boxplot(data, patch_artist=True, labels=[str(x) for x in grps], widths=0.6)
        for i, box in enumerate(bp["boxes"]):
            box.set(facecolor=palette(opt)[i % 8], alpha=0.75, edgecolor="#41566b")
        for med in bp["medians"]:
            med.set(color="#12283b", linewidth=1.6)
    else:
        ax.boxplot(_num(v).dropna().values, patch_artist=True)
    return finish(fig, ax, opt, "Group", "Value", legend_ok=False)

register(PlotSpec("box", "Box plot", "1. Distribution",
    "Median, quartiles and outliers per group.",
    [Column("Group", "text", True, "Category / group label"),
     Column("Value", "number", True, "Numeric measurements")],
    {"Group": ["A"]*4 + ["B"]*4 + ["C"]*4,
     "Value": [5, 7, 6, 8, 9, 11, 10, 12, 3, 5, 4, 6]},
    r_box))


def r_violin(df, opt):
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    grps = _groups(g) if g is not None else ["All"]
    data = [_num(v[g == grp]).dropna().values if g is not None else _num(v).dropna().values
            for grp in grps]
    parts = ax.violinplot(data, showmeans=True, showextrema=False)
    for i, b in enumerate(parts["bodies"]):
        b.set_facecolor(palette(opt)[i % 8]); b.set_alpha(0.65); b.set_edgecolor("#41566b")
    ax.set_xticks(range(1, len(grps) + 1)); ax.set_xticklabels([str(x) for x in grps])
    return finish(fig, ax, opt, "Group", "Value", legend_ok=False)

register(PlotSpec("violin", "Violin plot", "1. Distribution",
    "Distribution shape (density) per group.",
    [Column("Group", "text", True, "Group label"),
     Column("Value", "number", True, "Numeric measurements")],
    {"Group": ["A"]*5 + ["B"]*5, "Value": [5, 7, 6, 8, 6, 9, 11, 10, 12, 10]},
    r_violin))


def r_raincloud(df, opt):
    from scipy.stats import gaussian_kde
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    grps = _groups(g) if g is not None else ["All"]
    for i, grp in enumerate(grps):
        vals = (_num(v[g == grp]) if g is not None else _num(v)).dropna().values
        if len(vals) < 2:
            continue
        color = palette(opt)[i % 8]
        xs = np.linspace(vals.min(), vals.max(), 100)
        dens = gaussian_kde(vals)(xs); dens = dens / dens.max() * 0.35
        ax.fill_betweenx(xs, i, i + dens, color=color, alpha=0.5)
        ax.scatter(np.full_like(vals, i - 0.12) + np.random.uniform(-0.05, 0.05, len(vals)),
                   vals, s=14, color=color, alpha=0.7, edgecolor="white", linewidth=0.4)
        ax.boxplot(vals, positions=[i - 0.28], widths=0.1, patch_artist=True,
                   boxprops=dict(facecolor=color, alpha=0.6), medianprops=dict(color="#12283b"))
    ax.set_xticks(range(len(grps))); ax.set_xticklabels([str(x) for x in grps])
    return finish(fig, ax, opt, "Group", "Value", legend_ok=False)

register(PlotSpec("raincloud", "Raincloud plot", "1. Distribution",
    "Half-violin + box + raw points — a rich distribution view.",
    [Column("Group", "text", True, "Group label"),
     Column("Value", "number", True, "Numeric measurements")],
    {"Group": ["A"]*6 + ["B"]*6,
     "Value": [5, 7, 6, 8, 6, 7, 9, 11, 10, 12, 10, 11]},
    r_raincloud))


def r_strip(df, opt):
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    grps = _groups(g) if g is not None else ["All"]
    for i, grp in enumerate(grps):
        vals = (_num(v[g == grp]) if g is not None else _num(v)).dropna().values
        ax.scatter(np.full_like(vals, i) + np.random.uniform(-0.12, 0.12, len(vals)),
                   vals, s=28, color=palette(opt)[i % 8], alpha=0.75,
                   edgecolor="white", linewidth=0.5)
    ax.set_xticks(range(len(grps))); ax.set_xticklabels([str(x) for x in grps])
    return finish(fig, ax, opt, "Group", "Value", legend_ok=False)

register(PlotSpec("strip", "Strip / jitter plot", "1. Distribution",
    "Every raw data point, jittered by group.",
    [Column("Group", "text", True, "Group label"),
     Column("Value", "number", True, "Numeric measurements")],
    {"Group": ["A"]*5 + ["B"]*5, "Value": [5, 7, 6, 8, 6, 9, 11, 10, 12, 10]},
    r_strip))


def r_ecdf(df, opt):
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    def _plot(vals, color, label=None):
        vals = np.sort(_num(vals).dropna().values)
        if len(vals) == 0:
            return
        y = np.arange(1, len(vals) + 1) / len(vals)
        ax.step(vals, y, where="post", color=color, lw=2, label=label)
    if g is not None:
        for i, grp in enumerate(_groups(g)):
            _plot(v[g == grp], palette(opt)[i], str(grp))
    else:
        _plot(v, palette(opt)[0])
    return finish(fig, ax, opt, "Value", "Cumulative proportion")

register(PlotSpec("ecdf", "ECDF", "1. Distribution",
    "Empirical cumulative distribution function.",
    [Column("Value", "number", True, "Numeric measurements"),
     Column("Group", "text", False, "Optional group overlay")],
    {"Value": [12, 15, 14, 18, 21, 13, 16, 19, 17, 20], "Group": ["A"]*5 + ["B"]*5},
    r_ecdf))


def r_qq(df, opt):
    from scipy import stats
    fig, ax = new_fig(opt)
    vals = _num(_col(df, "Value")).dropna().values
    (osm, osr), (slope, intercept, r) = stats.probplot(vals, dist="norm")
    ax.scatter(osm, osr, s=26, color=palette(opt)[0], alpha=0.8, edgecolor="white")
    ax.plot(osm, slope * osm + intercept, color="#d8572a", lw=2)
    if opt.annotate:
        ax.text(0.05, 0.92, f"R = {r:.3f}", transform=ax.transAxes,
                fontsize=10, color="#41566b")
    return finish(fig, ax, opt, "Theoretical quantiles", "Sample quantiles", legend_ok=False)

register(PlotSpec("qq", "Q–Q plot", "1. Distribution",
    "Check whether data follow a normal distribution.",
    [Column("Value", "number", True, "Numeric measurements")],
    {"Value": [12, 15, 14, 18, 21, 13, 16, 19, 17, 20, 11, 22]},
    r_qq))


def r_ridgeline(df, opt):
    from scipy.stats import gaussian_kde
    fig, ax = new_fig(opt)
    v = _col(df, "Value"); g = _col(df, "Group")
    grps = _groups(g)
    for i, grp in enumerate(reversed(grps)):
        vals = _num(v[g == grp]).dropna().values
        if len(vals) < 2:
            continue
        xs = np.linspace(vals.min(), vals.max(), 200)
        dens = gaussian_kde(vals)(xs); dens = dens / dens.max() * 1.4
        ax.fill_between(xs, i, i + dens, color=palette(opt)[i % 8], alpha=0.7, zorder=len(grps)-i)
        ax.plot(xs, i + dens, color="#12283b", lw=0.8, zorder=len(grps)-i)
    ax.set_yticks(range(len(grps))); ax.set_yticklabels([str(x) for x in reversed(grps)])
    return finish(fig, ax, opt, "Value", "Group", legend_ok=False)

register(PlotSpec("ridgeline", "Ridgeline (joy) plot", "1. Distribution",
    "Many group distributions stacked vertically.",
    [Column("Group", "text", True, "Group label"),
     Column("Value", "number", True, "Numeric measurements")],
    {"Group": ["A"]*6 + ["B"]*6 + ["C"]*6,
     "Value": [5,7,6,8,6,7, 9,11,10,12,10,11, 2,4,3,5,3,4]},
    r_ridgeline))


# ===========================================================================
# CATEGORY 2 — COMPARISON
# ===========================================================================
def r_bar(df, opt):
    fig, ax = new_fig(opt)
    cat = _col(df, "Category").astype(str); val = _num(_col(df, "Value"))
    bars = ax.bar(cat, val, color=palette(opt, len(cat)), edgecolor="white", zorder=3)
    if opt.annotate:
        for b in bars:
            ax.annotate(f"{b.get_height():g}", (b.get_x()+b.get_width()/2, b.get_height()),
                        ha="center", va="bottom", fontsize=8.5, color="#41566b", xytext=(0,2),
                        textcoords="offset points")
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    return finish(fig, ax, opt, "Category", "Value", legend_ok=False)

register(PlotSpec("bar", "Bar chart", "2. Comparison",
    "One value per category.",
    [Column("Category", "text", True, "Category label"),
     Column("Value", "number", True, "Numeric value")],
    {"Category": ["Alpha", "Beta", "Gamma", "Delta"], "Value": [23, 45, 31, 18]},
    r_bar))


def _cat_group_pivot(df):
    cat = _col(df, "Category").astype(str); grp = _col(df, "Group").astype(str)
    val = _num(_col(df, "Value"))
    p = pd.DataFrame({"Category": cat, "Group": grp, "Value": val})
    return p.pivot_table(index="Category", columns="Group", values="Value", aggfunc="sum").fillna(0)

def r_grouped_bar(df, opt):
    fig, ax = new_fig(opt)
    piv = _cat_group_pivot(df)
    cats = list(piv.index); groups = list(piv.columns)
    x = np.arange(len(cats)); w = 0.8 / max(len(groups), 1)
    for i, gname in enumerate(groups):
        ax.bar(x + i*w - 0.4 + w/2, piv[gname].values, w, label=str(gname),
               color=palette(opt)[i % 8], edgecolor="white", zorder=3)
    ax.set_xticks(x); ax.set_xticklabels(cats, rotation=30, ha="right")
    return finish(fig, ax, opt, "Category", "Value")

register(PlotSpec("grouped_bar", "Grouped bar", "2. Comparison",
    "Compare categories across sub-groups (bars side by side).",
    [Column("Category", "text", True, "Category label"),
     Column("Group", "text", True, "Sub-group"),
     Column("Value", "number", True, "Numeric value")],
    {"Category": ["Q1","Q1","Q2","Q2","Q3","Q3"], "Group": ["A","B"]*3,
     "Value": [12, 9, 15, 11, 14, 13]},
    r_grouped_bar))


def r_stacked_bar(df, opt, pct=False):
    fig, ax = new_fig(opt)
    piv = _cat_group_pivot(df)
    if pct:
        piv = piv.div(piv.sum(axis=1).replace(0, np.nan), axis=0) * 100
    cats = list(piv.index); bottom = np.zeros(len(cats))
    for i, gname in enumerate(piv.columns):
        ax.bar(cats, piv[gname].values, bottom=bottom, label=str(gname),
               color=palette(opt)[i % 8], edgecolor="white", zorder=3)
        bottom += piv[gname].values
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    return finish(fig, ax, opt, "Category", "Percent" if pct else "Value")

register(PlotSpec("stacked_bar", "Stacked bar", "2. Comparison",
    "Composition within each category (stacked).",
    [Column("Category","text",True,"Category label"), Column("Group","text",True,"Sub-group"),
     Column("Value","number",True,"Numeric value")],
    {"Category": ["Q1","Q1","Q2","Q2"], "Group": ["A","B","A","B"], "Value": [12,9,15,11]},
    r_stacked_bar))

register(PlotSpec("pct_stacked_bar", "100% stacked bar", "2. Comparison",
    "Proportional composition within each category (sums to 100%).",
    [Column("Category","text",True,"Category label"), Column("Group","text",True,"Sub-group"),
     Column("Value","number",True,"Numeric value")],
    {"Category": ["Q1","Q1","Q2","Q2"], "Group": ["A","B","A","B"], "Value": [12,9,15,11]},
    lambda df, opt: r_stacked_bar(df, opt, pct=True)))


def r_hbar(df, opt):
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"c": _col(df, "Category").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna().sort_values("v")
    ax.barh(d["c"], d["v"], color=palette(opt, len(d)), edgecolor="white", zorder=3)
    if opt.annotate:
        for y, v in enumerate(d["v"]):
            ax.annotate(f"{v:g}", (v, y), ha="left", va="center", fontsize=8.5,
                        color="#41566b", xytext=(3, 0), textcoords="offset points")
    return finish(fig, ax, opt, "Value", "Category", legend_ok=False)

register(PlotSpec("hbar", "Horizontal bar", "2. Comparison",
    "Ranked horizontal bars — ideal for long labels.",
    [Column("Category","text",True,"Category label"), Column("Value","number",True,"Numeric value")],
    {"Category": ["Long label A","Long label B","Long label C","Long label D"],
     "Value": [23, 45, 31, 18]},
    r_hbar))


def r_errorbar(df, opt):
    fig, ax = new_fig(opt)
    if _col(df, "Mean") is not None:
        grp = _col(df, "Group").astype(str); mean = _num(_col(df, "Mean")); sd = _num(_col(df, "SD"))
        ax.bar(grp, mean, yerr=sd, capsize=5, color=palette(opt, len(grp)),
               edgecolor="white", zorder=3, error_kw=dict(ecolor="#41566b", lw=1.4))
    else:
        grp = _col(df, "Group").astype(str); val = _num(_col(df, "Value"))
        d = pd.DataFrame({"g": grp, "v": val}).dropna()
        agg = d.groupby("g")["v"].agg(["mean", "std"]).reset_index()
        ax.bar(agg["g"], agg["mean"], yerr=agg["std"], capsize=5,
               color=palette(opt, len(agg)), edgecolor="white", zorder=3,
               error_kw=dict(ecolor="#41566b", lw=1.4))
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    return finish(fig, ax, opt, "Group", "Mean ± SD", legend_ok=False)

register(PlotSpec("errorbar", "Error-bar (mean ± SD)", "2. Comparison",
    "Group means with error bars. Give raw Group/Value, or precomputed Group/Mean/SD.",
    [Column("Group","text",True,"Group label"),
     Column("Value","number",False,"Raw values (if not giving Mean/SD)"),
     Column("Mean","number",False,"Group mean (optional)"),
     Column("SD","number",False,"Group SD (optional)")],
    {"Group": ["A","A","A","B","B","B"], "Value": [5,7,6,9,11,10],
     "Mean": [None]*6, "SD": [None]*6},
    r_errorbar))


def r_lollipop(df, opt):
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"c": _col(df, "Category").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna().sort_values("v")
    ax.hlines(d["c"], 0, d["v"], color="#c3d0dd", lw=2, zorder=2)
    ax.scatter(d["v"], d["c"], s=70, color=palette(opt)[0], zorder=3, edgecolor="white")
    return finish(fig, ax, opt, "Value", "Category", legend_ok=False)

register(PlotSpec("lollipop", "Lollipop chart", "2. Comparison",
    "Cleaner alternative to bars for rankings.",
    [Column("Category","text",True,"Category label"), Column("Value","number",True,"Numeric value")],
    {"Category": ["Alpha","Beta","Gamma","Delta"], "Value": [23,45,31,18]},
    r_lollipop))


def r_dumbbell(df, opt):
    fig, ax = new_fig(opt)
    cat = _col(df, "Category").astype(str)
    a = _num(_col(df, "Before")); b = _num(_col(df, "After"))
    d = pd.DataFrame({"c": cat, "a": a, "b": b}).dropna()
    y = np.arange(len(d))
    ax.hlines(y, d["a"], d["b"], color="#c3d0dd", lw=2.5, zorder=2)
    ax.scatter(d["a"], y, s=80, color=palette(opt)[0], label="Before", zorder=3, edgecolor="white")
    ax.scatter(d["b"], y, s=80, color=palette(opt)[2], label="After", zorder=3, edgecolor="white")
    ax.set_yticks(y); ax.set_yticklabels(d["c"])
    return finish(fig, ax, opt, "Value", "Category")

register(PlotSpec("dumbbell", "Dumbbell plot", "2. Comparison",
    "Two-point comparison (e.g. before vs after) per category.",
    [Column("Category","text",True,"Category label"),
     Column("Before","number",True,"First value"), Column("After","number",True,"Second value")],
    {"Category": ["Alpha","Beta","Gamma"], "Before": [10,14,8], "After": [16,15,12]},
    r_dumbbell))


def r_slope(df, opt):
    fig, ax = new_fig(opt)
    subj = _col(df, "Subject").astype(str); time = _col(df, "Time").astype(str)
    val = _num(_col(df, "Value"))
    d = pd.DataFrame({"s": subj, "t": time, "v": val}).dropna()
    times = list(pd.unique(d["t"]))
    for i, s in enumerate(pd.unique(d["s"])):
        sub = d[d["s"] == s].set_index("t").reindex(times)
        ax.plot(range(len(times)), sub["v"].values, marker="o",
                color=palette(opt)[i % 8], lw=1.8, label=str(s))
    ax.set_xticks(range(len(times))); ax.set_xticklabels(times)
    return finish(fig, ax, opt, "Time", "Value")

register(PlotSpec("slope", "Slope / before–after", "2. Comparison",
    "Per-subject change across time points.",
    [Column("Subject","text",True,"Subject / item"), Column("Time","text",True,"Time point"),
     Column("Value","number",True,"Numeric value")],
    {"Subject": ["P1","P1","P2","P2","P3","P3"], "Time": ["Pre","Post"]*3,
     "Value": [10,16,14,15,8,12]},
    r_slope))


def r_radar(df, opt):
    fig = plt.figure(figsize=opt.figsize, dpi=opt.dpi)
    ax = fig.add_subplot(111, polar=True)
    metric = _col(df, "Metric").astype(str); val = _num(_col(df, "Value"))
    ser = _col(df, "Series")
    metrics = list(pd.unique(metric))
    angles = np.linspace(0, 2*np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]
    series = _groups(ser) if ser is not None else ["Series"]
    for i, s in enumerate(series):
        sub = pd.DataFrame({"m": metric, "v": val})
        if ser is not None:
            sub = sub[ser.values == s]
        sub = sub.set_index("m").reindex(metrics)["v"].values.tolist()
        sub += sub[:1]
        ax.plot(angles, sub, color=palette(opt)[i % 8], lw=2, label=str(s))
        ax.fill(angles, sub, color=palette(opt)[i % 8], alpha=0.15)
    ax.set_xticks(angles[:-1]); ax.set_xticklabels(metrics, fontsize=9)
    if opt.title:
        ax.set_title(opt.title, fontsize=14, fontweight="bold", color="#12283b", pad=18)
    if opt.legend and ser is not None:
        ax.legend(frameon=False, fontsize=9, loc="upper right", bbox_to_anchor=(1.25, 1.1))
    return bare_finish(fig, PlotOptions(watermark=opt.watermark))

register(PlotSpec("radar", "Radar / spider chart", "2. Comparison",
    "Multi-metric profile across one or more series.",
    [Column("Metric","text",True,"Axis / metric name"), Column("Value","number",True,"Value"),
     Column("Series","text",False,"Optional series to overlay")],
    {"Metric": ["Speed","Power","Range","Cost","Safety"]*2,
     "Value": [8,7,6,5,9, 6,8,7,7,6],
     "Series": ["Model A"]*5 + ["Model B"]*5},
    r_radar))


def r_grouped_box(df, opt):
    import seaborn as sns
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"Group": _col(df, "Group").astype(str),
                      "Subgroup": _col(df, "Subgroup").astype(str),
                      "Value": _num(_col(df, "Value"))}).dropna()
    sns.boxplot(data=d, x="Group", y="Value", hue="Subgroup", ax=ax,
                palette=palette(opt, d["Subgroup"].nunique()))
    return finish(fig, ax, opt, "Group", "Value")

register(PlotSpec("grouped_box", "Grouped box plot", "2. Comparison",
    "Box plots split by group and sub-group.",
    [Column("Group","text",True,"Primary group"), Column("Subgroup","text",True,"Sub-group"),
     Column("Value","number",True,"Numeric value")],
    {"Group": ["A","A","A","A","B","B","B","B"], "Subgroup": ["X","Y"]*4,
     "Value": [5,7,6,8,9,11,10,12]},
    r_grouped_box))


# ===========================================================================
# CATEGORY 3 — RELATIONSHIP / CORRELATION
# ===========================================================================
def r_scatter(df, opt):
    fig, ax = new_fig(opt)
    x = _num(_col(df, "X")); y = _num(_col(df, "Y")); g = _col(df, "Group")
    if g is not None:
        for i, grp in enumerate(_groups(g)):
            m = g == grp
            ax.scatter(x[m], y[m], s=40, color=palette(opt)[i % 8], alpha=0.75,
                       edgecolor="white", linewidth=0.5, label=str(grp))
    else:
        ax.scatter(x, y, s=40, color=palette(opt)[0], alpha=0.75,
                   edgecolor="white", linewidth=0.5)
    return finish(fig, ax, opt, "X", "Y")

register(PlotSpec("scatter", "Scatter plot", "3. Relationship",
    "Relationship between two numeric variables.",
    [Column("X","number",True,"X value"), Column("Y","number",True,"Y value"),
     Column("Group","text",False,"Optional group colour")],
    {"X": [1,2,3,4,5,6,7,8], "Y": [2,4,5,4,6,7,8,9], "Group": ["A"]*4+["B"]*4},
    r_scatter))


def r_scatter_reg(df, opt):
    from scipy import stats
    fig, ax = new_fig(opt)
    x = _num(_col(df, "X")); y = _num(_col(df, "Y"))
    d = pd.DataFrame({"x": x, "y": y}).dropna()
    ax.scatter(d["x"], d["y"], s=40, color=palette(opt)[0], alpha=0.75,
               edgecolor="white", linewidth=0.5)
    if len(d) >= 2:
        sl, ic, r, p, se = stats.linregress(d["x"], d["y"])
        xs = np.linspace(d["x"].min(), d["x"].max(), 100)
        ax.plot(xs, sl*xs + ic, color="#d8572a", lw=2)
        if opt.annotate:
            ax.text(0.05, 0.92, f"r = {r:.3f}\np = {p:.3g}", transform=ax.transAxes,
                    fontsize=10, color="#41566b", va="top")
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("scatter_reg", "Scatter + regression", "3. Relationship",
    "Scatter with fitted trend line and correlation (r, p).",
    [Column("X","number",True,"X value"), Column("Y","number",True,"Y value")],
    {"X": [1,2,3,4,5,6,7,8], "Y": [2,4,5,4,6,7,8,9]},
    r_scatter_reg))


def r_bubble(df, opt):
    fig, ax = new_fig(opt)
    x = _num(_col(df, "X")); y = _num(_col(df, "Y")); s = _num(_col(df, "Size"))
    lab = _col(df, "Label")
    sizes = (s - s.min()) / (s.max() - s.min() + 1e-9) * 900 + 60
    ax.scatter(x, y, s=sizes, color=palette(opt)[3], alpha=0.55, edgecolor="#41566b", linewidth=0.6)
    if lab is not None and opt.annotate:
        for xi, yi, li in zip(x, y, lab.astype(str)):
            ax.annotate(li, (xi, yi), fontsize=8, color="#41566b", ha="center", va="center")
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("bubble", "Bubble chart", "3. Relationship",
    "Scatter with a third variable encoded as bubble size.",
    [Column("X","number",True,"X value"), Column("Y","number",True,"Y value"),
     Column("Size","number",True,"Bubble size variable"), Column("Label","text",False,"Optional point label")],
    {"X": [1,3,5,7], "Y": [2,6,4,8], "Size": [10,40,25,60], "Label": ["A","B","C","D"]},
    r_bubble))


def r_corr_heatmap(df, opt):
    import seaborn as sns
    fig, ax = new_fig(opt)
    if _col(df, "Row") is not None and _col(df, "Column") is not None:
        d = pd.DataFrame({"r": _col(df, "Row").astype(str), "c": _col(df, "Column").astype(str),
                          "v": _num(_col(df, "Value"))})
        mat = d.pivot_table(index="r", columns="c", values="v")
    else:
        mat = df.apply(_num).dropna(axis=1, how="all").corr()
    sns.heatmap(mat, annot=opt.annotate, fmt=".2f", cmap="RdBu_r", center=0,
                ax=ax, linewidths=0.5, linecolor="white",
                cbar_kws={"shrink": 0.8}, vmin=-1 if mat.values.max() <= 1 else None,
                vmax=1 if mat.values.max() <= 1 else None)
    return bare_finish(fig, opt, ax)

register(PlotSpec("corr_heatmap", "Correlation heatmap", "3. Relationship",
    "Pairwise correlation matrix. Give a wide numeric table (one column per variable), OR long Row/Column/Value.",
    [Column("Var1","number",False,"Numeric variable (add as many columns as you like)"),
     Column("Var2","number",False,"Numeric variable"), Column("Var3","number",False,"Numeric variable")],
    {"Var1": [1,2,3,4,5], "Var2": [2,4,5,4,6], "Var3": [5,3,2,4,1]},
    r_corr_heatmap))


def r_pairplot(df, opt):
    import seaborn as sns
    d = df.copy()
    hue = None
    if _col(df, "Group") is not None:
        hue = _col(df, "Group").name
        num = d.drop(columns=[hue]).apply(_num)
        num[hue] = d[hue].astype(str)
        d = num
    else:
        d = d.apply(_num).dropna(axis=1, how="all")
    g = sns.pairplot(d.dropna(), hue=hue, palette=palette(opt, 8), corner=True,
                     plot_kws=dict(s=30, edgecolor="white", alpha=0.75))
    fig = g.figure
    if opt.watermark:
        fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom",
                 fontsize=8, color="#b8c6d6", alpha=0.8, style="italic")
    return fig

register(PlotSpec("pairplot", "Pair plot (scatter matrix)", "3. Relationship",
    "All pairwise scatterplots for several numeric variables at once.",
    [Column("Var1","number",True,"Numeric variable"), Column("Var2","number",True,"Numeric variable"),
     Column("Var3","number",False,"Numeric variable"), Column("Group","text",False,"Optional group colour")],
    {"Var1": [1,2,3,4,5,6], "Var2": [2,4,5,4,6,7], "Var3": [5,3,2,4,1,3],
     "Group": ["A","A","A","B","B","B"]},
    r_pairplot))


def r_density2d(df, opt):
    from scipy.stats import gaussian_kde
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"x": _num(_col(df, "X")), "y": _num(_col(df, "Y"))}).dropna()
    xy = np.vstack([d["x"], d["y"]]); kde = gaussian_kde(xy)
    xi, yi = np.mgrid[d["x"].min():d["x"].max():120j, d["y"].min():d["y"].max():120j]
    zi = kde(np.vstack([xi.ravel(), yi.ravel()])).reshape(xi.shape)
    ax.contourf(xi, yi, zi, levels=12, cmap="mako" if False else "viridis", alpha=0.9)
    ax.scatter(d["x"], d["y"], s=8, color="white", alpha=0.5)
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("density2d", "2D density / contour", "3. Relationship",
    "Density contours for overplotted scatter clouds.",
    [Column("X","number",True,"X value"), Column("Y","number",True,"Y value")],
    {"X": list(np.round(np.random.RandomState(1).normal(0,1,60),2)),
     "Y": list(np.round(np.random.RandomState(2).normal(0,1,60),2))},
    r_density2d))


def r_hexbin(df, opt):
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"x": _num(_col(df, "X")), "y": _num(_col(df, "Y"))}).dropna()
    hb = ax.hexbin(d["x"], d["y"], gridsize=25, cmap="Blues", mincnt=1)
    fig.colorbar(hb, ax=ax, shrink=0.8, label="count")
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("hexbin", "Hexbin plot", "3. Relationship",
    "Density-binned scatter for very large datasets.",
    [Column("X","number",True,"X value"), Column("Y","number",True,"Y value")],
    {"X": list(np.round(np.random.RandomState(1).normal(0,1,200),2)),
     "Y": list(np.round(np.random.RandomState(2).normal(0,1,200),2))},
    r_hexbin))


def r_connected_scatter(df, opt):
    fig, ax = new_fig(opt)
    d = pd.DataFrame({"o": _num(_col(df, "Order")), "x": _num(_col(df, "X")),
                      "y": _num(_col(df, "Y"))}).dropna().sort_values("o")
    ax.plot(d["x"], d["y"], color="#c3d0dd", lw=1.5, zorder=2)
    ax.scatter(d["x"], d["y"], s=45, color=palette(opt)[0], zorder=3, edgecolor="white")
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("connected_scatter", "Connected scatter", "3. Relationship",
    "Scatter points joined in a defined order (e.g. a trajectory).",
    [Column("Order","number",True,"Point order"), Column("X","number",True,"X value"),
     Column("Y","number",True,"Y value")],
    {"Order": [1,2,3,4,5], "X": [1,2,4,3,5], "Y": [2,5,4,7,6]},
    r_connected_scatter))


# ===========================================================================
# CATEGORY 4 — TRENDS OVER TIME
# ===========================================================================
def r_line(df, opt):
    fig, ax = new_fig(opt)
    x = _col(df, "X"); y = _num(_col(df, "Y")); s = _col(df, "Series")
    if s is not None:
        for i, ser in enumerate(_groups(s)):
            m = s == ser
            ax.plot(x[m], y[m], marker="o", ms=4, lw=2, color=palette(opt)[i % 8], label=str(ser))
    else:
        ax.plot(x, y, marker="o", ms=4, lw=2, color=palette(opt)[0])
    plt.setp(ax.get_xticklabels(), rotation=25, ha="right")
    return finish(fig, ax, opt, "X", "Y")

register(PlotSpec("line", "Line chart", "4. Trends",
    "A value over an ordered axis (e.g. time).",
    [Column("X","text",True,"Time / ordered point"), Column("Y","number",True,"Value"),
     Column("Series","text",False,"Optional series overlay")],
    {"X": [2019,2020,2021,2022,2023]*2, "Y": [10,14,13,18,22, 5,8,9,7,11],
     "Series": ["A"]*5 + ["B"]*5},
    r_line))

register(PlotSpec("multiline", "Multi-series line", "4. Trends",
    "Several series over the same axis.",
    [Column("X","text",True,"Time / ordered point"), Column("Series","text",True,"Series name"),
     Column("Y","number",True,"Value")],
    {"X": [2020,2021,2022]*2, "Series": ["A","A","A","B","B","B"], "Y": [10,14,13,5,8,9]},
    lambda df, opt: r_line(df.rename(columns={}), opt)))


def r_area(df, opt):
    fig, ax = new_fig(opt)
    x = _col(df, "X"); y = _num(_col(df, "Y"))
    ax.fill_between(range(len(x)), y, color=palette(opt)[0], alpha=0.35)
    ax.plot(range(len(x)), y, color=palette(opt)[0], lw=2, marker="o", ms=4)
    ax.set_xticks(range(len(x))); ax.set_xticklabels(x.astype(str), rotation=25, ha="right")
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("area", "Area chart", "4. Trends",
    "Filled line to emphasise volume over time.",
    [Column("X","text",True,"Time / ordered point"), Column("Y","number",True,"Value")],
    {"X": [2019,2020,2021,2022,2023], "Y": [10,14,13,18,22]},
    r_area))


def r_stacked_area(df, opt):
    fig, ax = new_fig(opt)
    x = _col(df, "X").astype(str); ser = _col(df, "Series").astype(str); val = _num(_col(df, "Value"))
    piv = pd.DataFrame({"x": x, "s": ser, "v": val}).pivot_table(
        index="x", columns="s", values="v", aggfunc="sum").fillna(0)
    ax.stackplot(range(len(piv.index)), *[piv[c].values for c in piv.columns],
                 labels=[str(c) for c in piv.columns], colors=palette(opt, len(piv.columns)), alpha=0.85)
    ax.set_xticks(range(len(piv.index))); ax.set_xticklabels(piv.index, rotation=25, ha="right")
    return finish(fig, ax, opt, "X", "Value")

register(PlotSpec("stacked_area", "Stacked area", "4. Trends",
    "Composition of a total over time.",
    [Column("X","text",True,"Time point"), Column("Series","text",True,"Series"),
     Column("Value","number",True,"Value")],
    {"X": [2020,2020,2021,2021,2022,2022], "Series": ["A","B"]*3, "Value": [5,3,7,4,9,6]},
    r_stacked_area))


def r_step(df, opt):
    fig, ax = new_fig(opt)
    x = _num(_col(df, "X")); y = _num(_col(df, "Y"))
    ax.step(x, y, where="post", color=palette(opt)[0], lw=2, marker="o", ms=4)
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("step", "Step plot", "4. Trends",
    "Discrete jumps between values.",
    [Column("X","number",True,"Ordered X"), Column("Y","number",True,"Value")],
    {"X": [1,2,3,4,5], "Y": [1,1,3,3,2]},
    r_step))


def r_line_ci(df, opt):
    fig, ax = new_fig(opt)
    x = _num(_col(df, "X")); y = _num(_col(df, "Y"))
    lo = _num(_col(df, "Lower")); hi = _num(_col(df, "Upper"))
    order = np.argsort(x.values)
    xv, yv, lov, hiv = x.values[order], y.values[order], lo.values[order], hi.values[order]
    ax.fill_between(xv, lov, hiv, color=palette(opt)[0], alpha=0.2)
    ax.plot(xv, yv, color=palette(opt)[0], lw=2, marker="o", ms=4)
    return finish(fig, ax, opt, "X", "Y", legend_ok=False)

register(PlotSpec("line_ci", "Line + confidence band", "4. Trends",
    "Trend line with a shaded confidence/uncertainty ribbon.",
    [Column("X","number",True,"Ordered X"), Column("Y","number",True,"Value"),
     Column("Lower","number",True,"Lower bound"), Column("Upper","number",True,"Upper bound")],
    {"X": [1,2,3,4,5], "Y": [2,4,5,4,6], "Lower": [1,3,4,3,5], "Upper": [3,5,6,5,7]},
    r_line_ci))


# ===========================================================================
# CATEGORY 5 — COMPOSITION / PART-TO-WHOLE
# ===========================================================================
def _pie(df, opt, hole=0.0):
    fig, ax = new_fig(opt)
    lab = _col(df, "Label").astype(str); val = _num(_col(df, "Value"))
    d = pd.DataFrame({"l": lab, "v": val}).dropna()
    wedges, _t, _a = ax.pie(d["v"], labels=d["l"], autopct="%1.1f%%", startangle=90,
                            colors=palette(opt, len(d)),
                            wedgeprops=dict(width=1-hole if hole else None, edgecolor="white"),
                            textprops=dict(fontsize=9, color="#12283b"))
    ax.axis("equal")
    return bare_finish(fig, opt, ax)

register(PlotSpec("pie", "Pie chart", "5. Composition",
    "Shares of a whole.",
    [Column("Label","text",True,"Slice label"), Column("Value","number",True,"Value / share")],
    {"Label": ["Alpha","Beta","Gamma","Delta"], "Value": [40,25,20,15]},
    lambda df, opt: _pie(df, opt, hole=0.0)))

register(PlotSpec("donut", "Donut chart", "5. Composition",
    "Shares of a whole with a hollow centre.",
    [Column("Label","text",True,"Slice label"), Column("Value","number",True,"Value / share")],
    {"Label": ["Alpha","Beta","Gamma","Delta"], "Value": [40,25,20,15]},
    lambda df, opt: _pie(df, opt, hole=0.45)))


def r_waffle(df, opt):
    fig, ax = new_fig(opt)
    lab = _col(df, "Label").astype(str); val = _num(_col(df, "Value"))
    d = pd.DataFrame({"l": lab, "v": val}).dropna()
    total = d["v"].sum(); cells = 100
    counts = (d["v"] / total * cells).round().astype(int)
    seq = []
    for i, c in enumerate(counts):
        seq += [i] * c
    seq = (seq + [len(d)] * (cells - len(seq)))[:cells]
    cols = palette(opt, len(d)) + ["#e6edf5"]
    for idx, cat in enumerate(seq):
        r, c = divmod(idx, 10)
        ax.add_patch(plt.Rectangle((c, 9 - r), 0.9, 0.9, color=cols[cat]))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
    handles = [plt.Rectangle((0, 0), 1, 1, color=cols[i]) for i in range(len(d))]
    if opt.legend:
        ax.legend(handles, d["l"], frameon=False, fontsize=9, loc="center left",
                  bbox_to_anchor=(1.02, 0.5))
    return bare_finish(fig, opt, ax)

register(PlotSpec("waffle", "Waffle / pictogram", "5. Composition",
    "Proportions shown as a 10×10 grid of squares.",
    [Column("Label","text",True,"Category"), Column("Value","number",True,"Value / share")],
    {"Label": ["Alpha","Beta","Gamma"], "Value": [50,30,20]},
    r_waffle))


def r_treemap(df, opt):
    import squarify
    fig, ax = new_fig(opt)
    lab = _col(df, "Label").astype(str); val = _num(_col(df, "Value"))
    d = pd.DataFrame({"l": lab, "v": val}).dropna().sort_values("v", ascending=False)
    squarify.plot(sizes=d["v"], label=[f"{l}\n{v:g}" for l, v in zip(d["l"], d["v"])],
                  color=palette(opt, len(d)), ax=ax, pad=True,
                  text_kwargs=dict(fontsize=9, color="white"))
    ax.axis("off")
    return bare_finish(fig, opt, ax)

register(PlotSpec("treemap", "Treemap", "5. Composition",
    "Nested rectangles sized by value.",
    [Column("Label","text",True,"Category"), Column("Value","number",True,"Value")],
    {"Label": ["Alpha","Beta","Gamma","Delta","Epsilon"], "Value": [40,25,20,10,5]},
    r_treemap))


def r_sunburst(df, opt):
    fig, ax = new_fig(opt)
    parent = _col(df, "Parent").astype(str); lab = _col(df, "Label").astype(str)
    val = _num(_col(df, "Value"))
    d = pd.DataFrame({"p": parent, "l": lab, "v": val}).dropna()
    parents = list(pd.unique(d["p"]))
    p_tot = d.groupby("p")["v"].sum().reindex(parents)
    # inner ring = parents
    ax.pie(p_tot.values, radius=0.7, labels=parents, labeldistance=0.3,
           colors=palette(opt, len(parents)), startangle=90,
           wedgeprops=dict(width=0.3, edgecolor="white"), textprops=dict(fontsize=8, color="white"))
    # outer ring = children ordered by parent
    child_vals, child_colors, child_labels = [], [], []
    for i, p in enumerate(parents):
        sub = d[d["p"] == p]
        base = palette(opt, len(parents))[i]
        for j, (_, row) in enumerate(sub.iterrows()):
            child_vals.append(row["v"]); child_labels.append(row["l"])
            child_colors.append(base)
    ax.pie(child_vals, radius=1.0, labels=child_labels, labeldistance=1.05,
           colors=child_colors, startangle=90,
           wedgeprops=dict(width=0.3, edgecolor="white", alpha=0.7), textprops=dict(fontsize=8))
    ax.set(aspect="equal")
    return bare_finish(fig, opt, ax)

register(PlotSpec("sunburst", "Sunburst (2-level)", "5. Composition",
    "Hierarchical composition: inner ring = parent, outer ring = children.",
    [Column("Parent","text",True,"Parent category"), Column("Label","text",True,"Child category"),
     Column("Value","number",True,"Value")],
    {"Parent": ["North","North","South","South"], "Label": ["A","B","C","D"], "Value": [10,15,8,12]},
    r_sunburst))


def r_sankey(df, opt):
    from matplotlib.path import Path
    from matplotlib.patches import PathPatch
    d = pd.DataFrame({"s": _col(df, "Source").astype(str), "t": _col(df, "Target").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna()
    sources = list(pd.unique(d["s"])); targets = list(pd.unique(d["t"]))
    fig, ax = new_fig(opt); ax.axis("off")
    gap = 0.06 * d["v"].sum()
    s_tot = d.groupby("s")["v"].sum().reindex(sources)
    t_tot = d.groupby("t")["v"].sum().reindex(targets)
    def layout(tot):
        pos = {}; y = 0.0
        for name, v in tot.items():
            pos[name] = [y, y + v]; y += v + gap
        return pos, y
    spos, sh = layout(s_tot); tpos, th = layout(t_tot)
    H = max(sh, th); x0, x1, mid = 0.12, 0.88, 0.5
    for i, name in enumerate(sources):
        y0, y1 = spos[name]
        ax.add_patch(plt.Rectangle((x0 - 0.03, H - y1), 0.03, y1 - y0, color=palette(opt)[i % 8]))
        ax.text(x0 - 0.05, H - (y0 + y1) / 2, name, ha="right", va="center", fontsize=9)
    for i, name in enumerate(targets):
        y0, y1 = tpos[name]
        ax.add_patch(plt.Rectangle((x1, H - y1), 0.03, y1 - y0, color=palette(opt)[(i + 3) % 8]))
        ax.text(x1 + 0.05, H - (y0 + y1) / 2, name, ha="left", va="center", fontsize=9)
    s_off = {k: v[0] for k, v in spos.items()}; t_off = {k: v[0] for k, v in tpos.items()}
    for _, row in d.iterrows():
        s, t, v = row["s"], row["t"], row["v"]
        sy0 = s_off[s]; s_off[s] += v; ty0 = t_off[t]; t_off[t] += v
        SY0, SY1 = H - sy0, H - (sy0 + v); TY0, TY1 = H - ty0, H - (ty0 + v)
        verts = [(x0, SY0), (mid, SY0), (mid, TY0), (x1, TY0),
                 (x1, TY1), (mid, TY1), (mid, SY1), (x0, SY1), (x0, SY0)]
        codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
                 Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CLOSEPOLY]
        ax.add_patch(PathPatch(Path(verts, codes),
                     facecolor=palette(opt)[sources.index(s) % 8], alpha=0.4, edgecolor="none"))
    ax.set_xlim(0, 1); ax.set_ylim(-0.05 * H, H * 1.05)
    return bare_finish(fig, opt, None)

register(PlotSpec("sankey", "Sankey / flow", "5. Composition",
    "Flows between source and target categories (band width = value).",
    [Column("Source","text",True,"Origin category"), Column("Target","text",True,"Destination"),
     Column("Value","number",True,"Flow magnitude")],
    {"Source": ["A","A","B","B"], "Target": ["X","Y","X","Y"], "Value": [8,5,3,9]},
    r_sankey))


def r_mosaic(df, opt):
    from statsmodels.graphics.mosaicplot import mosaic
    d = pd.DataFrame({"a": _col(df, "CatA").astype(str), "b": _col(df, "CatB").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna()
    data = {(r["a"], r["b"]): r["v"] for _, r in d.iterrows()}
    fig, ax = new_fig(opt)
    mosaic(data, ax=ax, gap=0.02, title="")
    return bare_finish(fig, opt, ax)

register(PlotSpec("mosaic", "Mosaic / Marimekko", "5. Composition",
    "Two-way categorical proportions as tiled rectangles.",
    [Column("CatA","text",True,"First category"), Column("CatB","text",True,"Second category"),
     Column("Value","number",True,"Count / value")],
    {"CatA": ["M","M","F","F"], "CatB": ["Yes","No","Yes","No"], "Value": [30,10,20,25]},
    r_mosaic))


# ===========================================================================
# CATEGORY 6 — STATISTICAL / BIOMEDICAL / OMICS
# ===========================================================================
def _forest_like(df, opt, null=0.0, xlabel="Effect size (95% CI)"):
    fig, ax = new_fig(opt)
    study = _col(df, "Study")
    if study is None:
        study = _col(df, "Term")
    study = study.astype(str)
    est = _num(_col(df, "Estimate")); lo = _num(_col(df, "LowerCI")); hi = _num(_col(df, "UpperCI"))
    w = _col(df, "Weight")
    d = pd.DataFrame({"s": study, "e": est, "lo": lo, "hi": hi})
    d["w"] = _num(w) if w is not None else 1.0
    d = d.dropna(subset=["e", "lo", "hi"]).reset_index(drop=True)
    y = np.arange(len(d))[::-1]
    sizes = 60 + (d["w"] / d["w"].max() * 240 if d["w"].max() else 60)
    ax.hlines(y, d["lo"], d["hi"], color="#41566b", lw=1.6, zorder=2)
    ax.scatter(d["e"], y, s=sizes, color=palette(opt)[0], zorder=3, edgecolor="white", marker="s")
    ax.axvline(null, color="#d8572a", lw=1.4, ls="--", zorder=1)
    ax.set_yticks(y); ax.set_yticklabels(d["s"])
    if opt.annotate:
        for yi, e, l, h in zip(y, d["e"], d["lo"], d["hi"]):
            ax.text(ax.get_xlim()[1], yi, f"  {e:.2f} [{l:.2f}, {h:.2f}]",
                    va="center", fontsize=8, color="#41566b")
    return finish(fig, ax, opt, opt.xlabel or xlabel, "", legend_ok=False)

register(PlotSpec("forest", "Forest plot", "6. Statistical / biomedical",
    "Meta-analysis effect sizes with 95% CI (box size ∝ weight).",
    [Column("Study","text",True,"Study name"), Column("Estimate","number",True,"Effect estimate"),
     Column("LowerCI","number",True,"Lower 95% CI"), Column("UpperCI","number",True,"Upper 95% CI"),
     Column("Weight","number",False,"Study weight (optional)")],
    {"Study": ["Study 1","Study 2","Study 3","Pooled"], "Estimate": [0.4,0.7,0.2,0.45],
     "LowerCI": [0.1,0.3,-0.1,0.25], "UpperCI": [0.7,1.1,0.5,0.65], "Weight": [20,35,15,100]},
    _forest_like))

register(PlotSpec("coef_plot", "Coefficient / effect plot", "6. Statistical / biomedical",
    "Regression coefficients with confidence intervals.",
    [Column("Term","text",True,"Predictor name"), Column("Estimate","number",True,"Coefficient"),
     Column("LowerCI","number",True,"Lower CI"), Column("UpperCI","number",True,"Upper CI")],
    {"Term": ["Age","Sex","BMI","Smoking"], "Estimate": [0.3,-0.2,0.5,0.8],
     "LowerCI": [0.1,-0.5,0.2,0.4], "UpperCI": [0.5,0.1,0.8,1.2]},
    lambda df, opt: _forest_like(df, opt, null=0.0, xlabel="Coefficient (95% CI)")))


def r_funnel(df, opt):
    fig, ax = new_fig(opt)
    est = _num(_col(df, "Estimate")); se = _num(_col(df, "StdError"))
    d = pd.DataFrame({"e": est, "se": se}).dropna()
    mean = np.average(d["e"], weights=1/d["se"]**2) if (d["se"] > 0).all() else d["e"].mean()
    ax.scatter(d["e"], d["se"], s=45, color=palette(opt)[0], alpha=0.8, edgecolor="white", zorder=3)
    se_range = np.linspace(d["se"].min()*0.5 if d["se"].min() else 0, d["se"].max()*1.1, 50)
    ax.plot(mean + 1.96*se_range, se_range, color="#c3d0dd", ls="--")
    ax.plot(mean - 1.96*se_range, se_range, color="#c3d0dd", ls="--")
    ax.axvline(mean, color="#d8572a", lw=1.4)
    ax.invert_yaxis()
    return finish(fig, ax, opt, "Effect estimate", "Standard error", legend_ok=False)

register(PlotSpec("funnel", "Funnel plot", "6. Statistical / biomedical",
    "Publication-bias check (effect vs standard error).",
    [Column("Estimate","number",True,"Study effect"), Column("StdError","number",True,"Standard error")],
    {"Estimate": [0.4,0.5,0.45,0.6,0.35,0.55], "StdError": [0.05,0.1,0.15,0.2,0.08,0.12]},
    r_funnel))


def r_kaplan_meier(df, opt, cumulative=False):
    from lifelines import KaplanMeierFitter
    fig, ax = new_fig(opt)
    t = _num(_col(df, "Time")); e = _num(_col(df, "Event")); g = _col(df, "Group")
    kmf = KaplanMeierFitter()
    groups = _groups(g) if g is not None else ["All"]
    for i, grp in enumerate(groups):
        m = (g == grp) if g is not None else pd.Series(True, index=t.index)
        d = pd.DataFrame({"t": t[m], "e": e[m]}).dropna()
        kmf.fit(d["t"], event_observed=d["e"], label=str(grp))
        surv = kmf.survival_function_
        y = (1 - surv.iloc[:, 0]) if cumulative else surv.iloc[:, 0]
        ax.step(surv.index, y, where="post", color=palette(opt)[i % 8], lw=2, label=str(grp))
    return finish(fig, ax, opt, "Time", "Cumulative incidence" if cumulative else "Survival probability")

register(PlotSpec("kaplan_meier", "Kaplan–Meier survival", "6. Statistical / biomedical",
    "Time-to-event survival curves by group.",
    [Column("Time","number",True,"Follow-up time"), Column("Event","int",True,"1 = event, 0 = censored"),
     Column("Group","text",False,"Optional group")],
    {"Time": [5,6,6,2,4,8,3,7,9,10], "Event": [1,0,1,1,1,0,1,0,1,0],
     "Group": ["A"]*5 + ["B"]*5},
    r_kaplan_meier))

register(PlotSpec("cuminc", "Cumulative incidence", "6. Statistical / biomedical",
    "Cumulative event incidence over time by group.",
    [Column("Time","number",True,"Follow-up time"), Column("Event","int",True,"1 = event, 0 = censored"),
     Column("Group","text",False,"Optional group")],
    {"Time": [5,6,6,2,4,8,3,7,9,10], "Event": [1,0,1,1,1,0,1,0,1,0],
     "Group": ["A"]*5 + ["B"]*5},
    lambda df, opt: r_kaplan_meier(df, opt, cumulative=True)))


def r_roc(df, opt):
    from sklearn.metrics import roc_curve, auc
    fig, ax = new_fig(opt)
    y = _num(_col(df, "TrueLabel")); s = _num(_col(df, "Score"))
    d = pd.DataFrame({"y": y, "s": s}).dropna()
    fpr, tpr, _ = roc_curve(d["y"], d["s"])
    ax.plot(fpr, tpr, color=palette(opt)[0], lw=2.2, label=f"AUC = {auc(fpr, tpr):.3f}")
    ax.plot([0, 1], [0, 1], color="#c3d0dd", ls="--")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.02)
    return finish(fig, ax, opt, "False positive rate", "True positive rate")

register(PlotSpec("roc", "ROC curve", "6. Statistical / biomedical",
    "Classifier performance with AUC.",
    [Column("TrueLabel","int",True,"Actual class (0/1)"), Column("Score","number",True,"Predicted score/probability")],
    {"TrueLabel": [0,0,0,1,1,1,0,1,1,0], "Score": [.1,.3,.4,.6,.8,.9,.2,.7,.85,.35]},
    r_roc))


def r_pr(df, opt):
    from sklearn.metrics import precision_recall_curve, average_precision_score
    fig, ax = new_fig(opt)
    y = _num(_col(df, "TrueLabel")); s = _num(_col(df, "Score"))
    d = pd.DataFrame({"y": y, "s": s}).dropna()
    pr, rc, _ = precision_recall_curve(d["y"], d["s"])
    ap = average_precision_score(d["y"], d["s"])
    ax.plot(rc, pr, color=palette(opt)[2], lw=2.2, label=f"AP = {ap:.3f}")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1.02)
    return finish(fig, ax, opt, "Recall", "Precision")

register(PlotSpec("pr_curve", "Precision–recall curve", "6. Statistical / biomedical",
    "Classifier performance for imbalanced data.",
    [Column("TrueLabel","int",True,"Actual class (0/1)"), Column("Score","number",True,"Predicted score")],
    {"TrueLabel": [0,0,0,1,1,1,0,1,1,0], "Score": [.1,.3,.4,.6,.8,.9,.2,.7,.85,.35]},
    r_pr))


def r_confusion(df, opt):
    fig, ax = new_fig(opt)
    a = _col(df, "Actual").astype(str); p = _col(df, "Predicted").astype(str)
    ct = pd.crosstab(a, p)
    im = ax.imshow(ct.values, cmap="Blues")
    ax.set_xticks(range(len(ct.columns))); ax.set_xticklabels(ct.columns)
    ax.set_yticks(range(len(ct.index))); ax.set_yticklabels(ct.index)
    for i in range(ct.shape[0]):
        for j in range(ct.shape[1]):
            v = ct.values[i, j]
            ax.text(j, i, str(v), ha="center", va="center",
                    color="white" if v > ct.values.max()/2 else "#12283b", fontsize=11)
    fig.colorbar(im, ax=ax, shrink=0.8)
    ax.set_xlabel("Predicted"); ax.set_ylabel("Actual")
    return bare_finish(fig, opt, ax)

register(PlotSpec("confusion", "Confusion matrix", "6. Statistical / biomedical",
    "Classification results (actual vs predicted).",
    [Column("Actual","text",True,"True class"), Column("Predicted","text",True,"Predicted class")],
    {"Actual": ["Pos","Pos","Neg","Neg","Pos","Neg","Pos","Neg"],
     "Predicted": ["Pos","Neg","Neg","Neg","Pos","Pos","Pos","Neg"]},
    r_confusion))


def r_calibration(df, opt):
    from sklearn.calibration import calibration_curve
    fig, ax = new_fig(opt)
    obs = _num(_col(df, "Observed")); pred = _num(_col(df, "Predicted"))
    d = pd.DataFrame({"o": obs, "p": pred}).dropna()
    frac_pos, mean_pred = calibration_curve(d["o"], d["p"], n_bins=min(10, max(2, len(d)//2)))
    ax.plot(mean_pred, frac_pos, marker="o", color=palette(opt)[0], lw=2, label="Model")
    ax.plot([0, 1], [0, 1], color="#c3d0dd", ls="--", label="Perfect")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    return finish(fig, ax, opt, "Mean predicted probability", "Observed fraction")

register(PlotSpec("calibration", "Calibration plot", "6. Statistical / biomedical",
    "Predicted probability vs observed frequency.",
    [Column("Observed","int",True,"Observed outcome (0/1)"), Column("Predicted","number",True,"Predicted probability")],
    {"Observed": [0,0,1,0,1,1,0,1,1,1], "Predicted": [.1,.2,.6,.3,.7,.8,.25,.65,.9,.75]},
    r_calibration))


def r_residual(df, opt):
    fig, ax = new_fig(opt)
    f = _num(_col(df, "Fitted")); r = _num(_col(df, "Residual"))
    ax.scatter(f, r, s=36, color=palette(opt)[0], alpha=0.8, edgecolor="white")
    ax.axhline(0, color="#d8572a", lw=1.4, ls="--")
    return finish(fig, ax, opt, "Fitted values", "Residuals", legend_ok=False)

register(PlotSpec("residual", "Residual plot", "6. Statistical / biomedical",
    "Regression residuals vs fitted values.",
    [Column("Fitted","number",True,"Fitted value"), Column("Residual","number",True,"Residual")],
    {"Fitted": [2,3,4,5,6,7], "Residual": [.2,-.1,.3,-.2,.1,-.3]},
    r_residual))


def r_volcano(df, opt):
    fig, ax = new_fig(opt)
    fc = _num(_col(df, "log2FC")); p = _num(_col(df, "pValue")); feat = _col(df, "Feature")
    d = pd.DataFrame({"fc": fc, "p": p, "f": feat.astype(str) if feat is not None else ""}).dropna(subset=["fc", "p"])
    d["nl"] = -np.log10(d["p"].clip(lower=1e-300))
    up = (d["fc"] >= 1) & (d["p"] < 0.05); dn = (d["fc"] <= -1) & (d["p"] < 0.05)
    ns = ~(up | dn)
    ax.scatter(d["fc"][ns], d["nl"][ns], s=18, color="#c3d0dd", alpha=0.6)
    ax.scatter(d["fc"][up], d["nl"][up], s=26, color="#d8572a", alpha=0.85, label="Up")
    ax.scatter(d["fc"][dn], d["nl"][dn], s=26, color="#2563eb", alpha=0.85, label="Down")
    ax.axhline(-np.log10(0.05), color="#8aa0b6", ls="--", lw=1)
    ax.axvline(1, color="#8aa0b6", ls="--", lw=1); ax.axvline(-1, color="#8aa0b6", ls="--", lw=1)
    return finish(fig, ax, opt, "log2 fold change", "-log10(p-value)")

register(PlotSpec("volcano", "Volcano plot", "6. Statistical / biomedical",
    "Differential expression: fold change vs significance.",
    [Column("Feature","text",False,"Gene/feature name"), Column("log2FC","number",True,"log2 fold change"),
     Column("pValue","number",True,"p-value")],
    {"Feature": ["G1","G2","G3","G4","G5","G6"], "log2FC": [2.1,-1.8,0.3,1.5,-2.2,0.1],
     "pValue": [.001,.002,.4,.02,.0005,.6]},
    r_volcano))


def r_ma(df, opt):
    fig, ax = new_fig(opt)
    mean = _num(_col(df, "Mean")); fc = _num(_col(df, "log2FC")); feat = _col(df, "Feature")
    d = pd.DataFrame({"m": mean, "fc": fc}).dropna()
    sig = d["fc"].abs() >= 1
    ax.scatter(d["m"][~sig], d["fc"][~sig], s=16, color="#c3d0dd", alpha=0.6)
    ax.scatter(d["m"][sig], d["fc"][sig], s=24, color="#d8572a", alpha=0.85)
    ax.axhline(0, color="#41566b", lw=1)
    ax.set_xscale("log")
    return finish(fig, ax, opt, "Mean expression (log)", "log2 fold change", legend_ok=False)

register(PlotSpec("ma_plot", "MA plot", "6. Statistical / biomedical",
    "Fold change vs mean expression.",
    [Column("Feature","text",False,"Gene/feature"), Column("Mean","number",True,"Mean expression"),
     Column("log2FC","number",True,"log2 fold change")],
    {"Feature": ["G1","G2","G3","G4","G5"], "Mean": [10,100,50,200,5],
     "log2FC": [2.1,-1.8,0.3,1.5,-2.2]},
    r_ma))


def r_manhattan(df, opt):
    fig, ax = new_fig(opt)
    ch = _col(df, "Chr").astype(str); pos = _num(_col(df, "Position")); p = _num(_col(df, "pValue"))
    d = pd.DataFrame({"ch": ch, "pos": pos, "p": p}).dropna(subset=["pos", "p"])
    d["nl"] = -np.log10(d["p"].clip(lower=1e-300))
    chroms = list(pd.unique(d["ch"])); offset = 0; xticks = []
    for i, c in enumerate(chroms):
        sub = d[d["ch"] == c].sort_values("pos")
        x = offset + sub["pos"].values
        ax.scatter(x, sub["nl"], s=12, color=palette(opt)[i % 8], alpha=0.8)
        xticks.append(offset + sub["pos"].mean()); offset = x.max() + sub["pos"].max()*0.1 if len(x) else offset
    ax.axhline(-np.log10(5e-8), color="#d8572a", ls="--", lw=1)
    ax.set_xticks(xticks); ax.set_xticklabels(chroms)
    return finish(fig, ax, opt, "Chromosome", "-log10(p-value)", legend_ok=False)

register(PlotSpec("manhattan", "Manhattan plot", "6. Statistical / biomedical",
    "GWAS-style significance across genomic positions.",
    [Column("Chr","text",True,"Chromosome"), Column("Position","number",True,"Position"),
     Column("pValue","number",True,"p-value")],
    {"Chr": ["1","1","1","2","2","2","3","3"], "Position": [10,50,90,20,60,100,30,80],
     "pValue": [.01,.0001,.2,.00005,.3,.02,.000001,.1]},
    r_manhattan))


def r_clustered_heatmap(df, opt):
    import seaborn as sns
    idx = _col(df, "Label")
    mat = df.copy()
    if idx is not None:
        mat = mat.set_index(idx.name)
    mat = mat.apply(_num).dropna(axis=1, how="all").dropna()
    g = sns.clustermap(mat, cmap="viridis", figsize=opt.figsize,
                       annot=opt.annotate, fmt=".1f", linewidths=0.4)
    fig = g.figure
    if opt.watermark:
        fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom",
                 fontsize=8, color="#b8c6d6", alpha=0.8, style="italic")
    return fig

register(PlotSpec("clustered_heatmap", "Clustered heatmap", "6. Statistical / biomedical",
    "Heatmap with hierarchical clustering (rows + columns).",
    [Column("Label","text",True,"Row label (e.g. gene/sample)"),
     Column("S1","number",True,"Numeric column"), Column("S2","number",True,"Numeric column"),
     Column("S3","number",False,"Numeric column")],
    {"Label": ["G1","G2","G3","G4"], "S1": [1,5,2,8], "S2": [2,4,3,7], "S3": [5,1,6,2]},
    r_clustered_heatmap))


def r_pca(df, opt):
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    fig, ax = new_fig(opt)
    g = _col(df, "Group")
    X = df.drop(columns=[g.name]) if g is not None else df.copy()
    X = X.apply(_num).dropna(axis=1, how="all")
    keep = X.dropna().index
    Xs = StandardScaler().fit_transform(X.loc[keep])
    pc = PCA(n_components=2).fit(Xs); comp = pc.transform(Xs)
    if g is not None:
        gv = g.loc[keep].astype(str)
        for i, grp in enumerate(pd.unique(gv)):
            m = gv == grp
            ax.scatter(comp[m.values, 0], comp[m.values, 1], s=45, color=palette(opt)[i % 8],
                       alpha=0.8, edgecolor="white", label=str(grp))
    else:
        ax.scatter(comp[:, 0], comp[:, 1], s=45, color=palette(opt)[0], alpha=0.8, edgecolor="white")
    ev = pc.explained_variance_ratio_ * 100
    return finish(fig, ax, opt, f"PC1 ({ev[0]:.1f}%)", f"PC2 ({ev[1]:.1f}%)")

register(PlotSpec("pca", "PCA scatter", "6. Statistical / biomedical",
    "2-component PCA of a numeric table, coloured by group.",
    [Column("Var1","number",True,"Numeric variable"), Column("Var2","number",True,"Numeric variable"),
     Column("Var3","number",False,"Numeric variable"), Column("Group","text",False,"Optional group")],
    {"Var1": [1,2,3,8,9,10], "Var2": [2,1,3,9,8,10], "Var3": [1,3,2,10,9,8],
     "Group": ["A","A","A","B","B","B"]},
    r_pca))


def r_dose_response(df, opt):
    from scipy.optimize import curve_fit
    fig, ax = new_fig(opt)
    def ll4(x, bottom, top, ec50, hill):
        return bottom + (top - bottom) / (1 + (x / ec50) ** (-hill))
    dose = _num(_col(df, "Dose")); resp = _num(_col(df, "Response")); g = _col(df, "Group")
    groups = _groups(g) if g is not None else ["All"]
    for i, grp in enumerate(groups):
        m = (g == grp) if g is not None else pd.Series(True, index=dose.index)
        d = pd.DataFrame({"x": dose[m], "y": resp[m]}).dropna().sort_values("x")
        ax.scatter(d["x"], d["y"], s=40, color=palette(opt)[i % 8], edgecolor="white", label=str(grp))
        try:
            p0 = [d["y"].min(), d["y"].max(), d["x"].median(), 1.0]
            popt, _ = curve_fit(ll4, d["x"], d["y"], p0=p0, maxfev=10000)
            xs = np.logspace(np.log10(d["x"].min()), np.log10(d["x"].max()), 100)
            ax.plot(xs, ll4(xs, *popt), color=palette(opt)[i % 8], lw=2)
        except Exception:
            pass
    ax.set_xscale("log")
    return finish(fig, ax, opt, "Dose (log)", "Response")

register(PlotSpec("dose_response", "Dose–response curve", "6. Statistical / biomedical",
    "4-parameter logistic fit (EC50) for pharmacology.",
    [Column("Dose","number",True,"Dose / concentration"), Column("Response","number",True,"Response"),
     Column("Group","text",False,"Optional compound/group")],
    {"Dose": [0.1,1,10,100,1000,0.1,1,10,100,1000],
     "Response": [5,10,45,80,95, 3,8,30,60,88], "Group": ["A"]*5 + ["B"]*5},
    r_dose_response))


def r_bland_altman(df, opt):
    fig, ax = new_fig(opt)
    a = _num(_col(df, "MethodA")); b = _num(_col(df, "MethodB"))
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    mean = (d["a"] + d["b"]) / 2; diff = d["a"] - d["b"]
    md = diff.mean(); sd = diff.std()
    ax.scatter(mean, diff, s=40, color=palette(opt)[0], alpha=0.8, edgecolor="white")
    ax.axhline(md, color="#d8572a", lw=1.6, label=f"Mean diff = {md:.2f}")
    ax.axhline(md + 1.96*sd, color="#8aa0b6", ls="--", lw=1.2, label="±1.96 SD")
    ax.axhline(md - 1.96*sd, color="#8aa0b6", ls="--", lw=1.2)
    return finish(fig, ax, opt, "Mean of two methods", "Difference (A − B)")

register(PlotSpec("bland_altman", "Bland–Altman", "6. Statistical / biomedical",
    "Agreement between two measurement methods.",
    [Column("MethodA","number",True,"Method A value"), Column("MethodB","number",True,"Method B value")],
    {"MethodA": [10,12,14,16,18,20], "MethodB": [10.5,11.5,14.2,15.5,18.3,19.6]},
    r_bland_altman))


def r_waterfall(df, opt):
    fig, ax = new_fig(opt)
    subj = _col(df, "Subject").astype(str); pct = _num(_col(df, "PctChange"))
    d = pd.DataFrame({"s": subj, "p": pct}).dropna().sort_values("p", ascending=False).reset_index(drop=True)
    colors = ["#1d9e75" if v < 0 else "#d8572a" for v in d["p"]]
    ax.bar(range(len(d)), d["p"], color=colors, edgecolor="white")
    ax.axhline(0, color="#41566b", lw=1)
    ax.set_xticks([])
    return finish(fig, ax, opt, "Patients (ranked)", "% change from baseline", legend_ok=False)

register(PlotSpec("waterfall", "Waterfall (response)", "6. Statistical / biomedical",
    "Per-patient % change from baseline (oncology response).",
    [Column("Subject","text",True,"Patient ID"), Column("PctChange","number",True,"% change from baseline")],
    {"Subject": ["P1","P2","P3","P4","P5","P6"], "PctChange": [30,-45,-20,10,-60,-5]},
    r_waterfall))


# ===========================================================================
# CATEGORY 7 — STUDY-FLOW / METHODOLOGICAL DIAGRAMS
# ===========================================================================
def _flow_diagram(df, opt, accent="#2563eb"):
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
    stage = _col(df, "Stage").astype(str); count = _col(df, "Count")
    excl = _col(df, "Excluded"); reason = _col(df, "ExcludedReason")
    n = len(stage)
    fig, ax = new_fig(opt); ax.axis("off")
    ax.set_xlim(0, 10); ax.set_ylim(0, n * 2 + 1)
    box_w, box_h, xc = 4.2, 1.3, 3.0
    ys = [n * 2 - 1 - i * 2 for i in range(n)]
    for i in range(n):
        y = ys[i]
        label = f"{stage.iloc[i]}"
        if count is not None and pd.notna(count.iloc[i]):
            label += f"\n(n = {count.iloc[i]:g})" if str(count.iloc[i]).replace('.','',1).isdigit() else f"\n(n = {count.iloc[i]})"
        ax.add_patch(FancyBboxPatch((xc - box_w/2, y - box_h/2), box_w, box_h,
                     boxstyle="round,pad=0.06,rounding_size=0.12", fc="#eef4fb", ec=accent, lw=1.8))
        ax.text(xc, y, label, ha="center", va="center", fontsize=9.5, color="#12283b")
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((xc, y - box_h/2), (xc, ys[i+1] + box_h/2),
                         arrowstyle="-|>", mutation_scale=18, lw=2, color="#8aa0b6"))
        if excl is not None and pd.notna(excl.iloc[i]) and str(excl.iloc[i]).strip() not in ("", "0"):
            ex_label = f"Excluded (n = {excl.iloc[i]:g})" if str(excl.iloc[i]).replace('.','',1).isdigit() else f"Excluded: {excl.iloc[i]}"
            if reason is not None and pd.notna(reason.iloc[i]):
                ex_label += f"\n{reason.iloc[i]}"
            ax.add_patch(FancyBboxPatch((6.2, y - box_h/2), 3.4, box_h,
                         boxstyle="round,pad=0.06,rounding_size=0.12", fc="#fdf0e6", ec="#d8572a", lw=1.4))
            ax.text(7.9, y, ex_label, ha="center", va="center", fontsize=8.5, color="#41566b")
            ax.add_patch(FancyArrowPatch((xc + box_w/2, y), (6.2, y),
                         arrowstyle="-|>", mutation_scale=14, lw=1.5, color="#c3a0a0"))
    return bare_finish(fig, opt, None)

_PRISMA_ALIAS = {
    "databases": "databases", "registers": "registers",
    "duplicates removed": "dup_removed", "duplicate records removed": "dup_removed", "duplicates": "dup_removed",
    "automation ineligible": "auto_ineligible", "automation-ineligible": "auto_ineligible",
    "records marked as ineligible by automation tools": "auto_ineligible",
    "other removed": "other_removed", "records removed for other reasons": "other_removed", "other reasons": "other_removed",
    "records screened": "screened", "screened": "screened",
    "records excluded": "records_excluded", "records excluded after screening": "records_excluded",
    "reports sought": "sought", "reports sought for retrieval": "sought",
    "reports not retrieved": "not_retrieved", "not retrieved": "not_retrieved",
    "reports assessed": "assessed", "reports assessed for eligibility": "assessed",
    "studies included": "studies_included", "studies included in review": "studies_included",
    "reports included": "reports_included", "reports of included studies": "reports_included",
}

def r_prisma2020(df, opt):
    """PRISMA 2020 flow (databases & registers) from a Field / Count table.
    'Source: <db>' / 'Register: <name>' rows list each named database in the
    identification box; 'Reason: <text>' rows fill the 'Reports excluded' box."""
    from . import prisma as _PR
    F = _col(df, "Field").astype(str); C = _col(df, "Count")
    d, reasons, sources = {}, [], []
    for f, c in zip(F, C):
        fl = str(f).strip().lower()
        try:
            cv = int(float(c))
        except Exception:
            cv = 0
        if fl.startswith(("source:", "database:", "register:")):
            sources.append((str(f).split(":", 1)[1].strip(), cv))
        elif fl.startswith("reason") or fl.startswith("excluded:"):
            lbl = str(f).split(":", 1)[1].strip() if ":" in str(f) else str(f)
            reasons.append((lbl, cv))
        elif fl in _PRISMA_ALIAS:
            d[_PRISMA_ALIAS[fl]] = cv
    return _PR.flow_png(d, reasons=reasons or None, sources=sources or None,
                        title=opt.title or "PRISMA 2020 flow diagram", return_fig=True)

register(PlotSpec("prisma", "PRISMA 2020 flow", "7. Study-flow diagrams",
    "PRISMA 2020 study-selection flow (databases & registers). One row per box as Field + Count. "
    "Use 'Source: <database>' rows to list each database searched, and 'Reason: <text>' rows for the "
    "'Reports excluded' box. (The two-stream version and a form-based builder live in the Meta-Analysis module.)",
    [Column("Field","text",True,"PRISMA box, or 'Source: <db>' / 'Reason: <text>'"),
     Column("Count","number",True,"Count for that box")],
    {"Field": ["Source: PubMed","Source: Scopus","Source: Embase","Register: ClinicalTrials.gov",
               "Duplicates removed","Automation ineligible","Other removed",
               "Records screened","Records excluded","Reports sought","Reports not retrieved","Reports assessed",
               "Reason: Wrong population","Reason: Wrong outcome","Reason: No extractable data",
               "Studies included","Reports included"],
     "Count": [620,400,180,25,290,0,10,925,780,145,5,140,40,30,10,45,50]},
    r_prisma2020))

register(PlotSpec("consort", "CONSORT flow", "7. Study-flow diagrams",
    "RCT participant flow (enrollment → allocation → follow-up → analysis).",
    [Column("Stage","text",True,"Stage name"), Column("Count","number",True,"Participants"),
     Column("Excluded","text",False,"Excluded/lost (optional)"),
     Column("ExcludedReason","text",False,"Reason (optional)")],
    {"Stage": ["Assessed for eligibility","Randomised","Allocated to intervention","Analysed"],
     "Count": [300, 200, 100, 95],
     "Excluded": [100, None, None, 5],
     "ExcludedReason": ["not eligible", None, None, "lost to follow-up"]},
    lambda df, opt: _flow_diagram(df, opt, accent="#1d9e75")))


_ROB_GREEN, _ROB_YELLOW, _ROB_RED, _ROB_GREY = "#4cae4f", "#f5c518", "#e63329", "#d7dee6"

def _rob_colour(v):
    if v is None:
        return _ROB_GREY
    vl = str(v).strip().lower()
    if vl in ("", "nan", "none", "na"):
        return _ROB_GREY
    if "low" in vl:
        return _ROB_GREEN
    if "high" in vl or "serious" in vl or "critical" in vl:
        return _ROB_RED
    return _ROB_YELLOW           # some concerns / unclear / moderate / unknown


def r_rob(df, opt):
    """Publication-ready risk-of-bias traffic-light plot (robvis / QUADAS-2 style):
    bordered cells, vertical domain headers, colour-coded circles and a legend.
    An optional 'Panel' column splits domains into side-by-side panels
    (e.g. QUADAS-2 'Risk of bias' + 'Applicability concerns')."""
    import matplotlib.patches as mpatches
    study = _col(df, "Study").astype(str)
    domain = _col(df, "Domain").astype(str)
    judge = _col(df, "Judgement").astype(str)
    pcol = _col(df, "Panel")
    panel = pcol.astype(str) if pcol is not None else pd.Series(["Risk of bias"] * len(study))
    d = pd.DataFrame({"s": study.values, "d": domain.values, "j": judge.values, "p": panel.values})
    studies = list(dict.fromkeys(d["s"]))
    panels = list(dict.fromkeys(d["p"]))
    pan_domains = {p: list(dict.fromkeys(d[d.p == p]["d"])) for p in panels}
    lut = {(r.s, r.p, r.d): r.j for r in d.itertuples()}
    n = len(studies)

    GAP = 1.6
    xpos, spans, x = {}, {}, 0.0
    for p in panels:
        start = x
        for dm in pan_domains[p]:
            xpos[(p, dm)] = x; x += 1
        spans[p] = (start, x - 1); x += GAP
    total_w = x - GAP

    maxlab = max((len(s) for s in studies), default=6)
    left = -(0.9 + 0.135 * maxlab)
    right = total_w + 3.8
    top = n - 0.5 + 5.6
    xspan, yspan = right - left, top - (-0.9)
    fig, ax = plt.subplots(figsize=(min(22, 0.46 * xspan + 2), min(24, 0.46 * yspan + 1)), dpi=opt.dpi)
    R = 0.40

    for p in panels:
        for dm in pan_domains[p]:
            xj = xpos[(p, dm)]
            for i, s in enumerate(studies):
                y = n - 1 - i
                ax.add_patch(mpatches.Rectangle((xj - 0.5, y - 0.5), 1, 1, fill=False,
                                                edgecolor="black", lw=1.0, zorder=2))
                ax.add_patch(plt.Circle((xj, y), R, facecolor=_rob_colour(lut.get((s, p, dm))),
                                        edgecolor="black", lw=0.7, zorder=3))
            ax.text(xpos[(p, dm)], n - 0.5 + 0.28, dm, rotation=90, ha="center", va="bottom",
                    fontsize=11, color="#222")
        a, b = spans[p]
        ax.add_patch(mpatches.Rectangle((a - 0.5, -0.5), (b - a) + 1, n, fill=False,
                                        edgecolor="black", lw=1.8, zorder=4))
        ax.text((a + b) / 2, n - 0.5 + 4.9, p, ha="center", va="bottom",
                fontsize=13.5, color="#12283b")

    for i, s in enumerate(studies):
        ax.text(-0.72, n - 1 - i, s, ha="right", va="center", fontsize=11, color="#222")

    # legend (right)
    lx = total_w + 1.1
    ly = n - 1.2
    for lab, c in [("Low", _ROB_GREEN), ("Unclear", _ROB_YELLOW), ("High", _ROB_RED)]:
        ax.add_patch(plt.Circle((lx, ly), R, facecolor=c, edgecolor="black", lw=0.7, zorder=3))
        ax.text(lx + 0.65, ly, lab, ha="left", va="center", fontsize=11.5, color="#222")
        ly -= 1.25

    ax.set_xlim(left, right); ax.set_ylim(-0.9, top)
    ax.set_aspect("equal"); ax.axis("off")
    return bare_finish(fig, opt, ax)

register(PlotSpec("rob_traffic", "Risk-of-bias traffic light", "7. Study-flow diagrams",
    "robvis / QUADAS-2 style quality-assessment grid (Low / Unclear / High per domain). "
    "Add an optional 'Panel' column to split into side-by-side panels (e.g. QUADAS-2 "
    "'Risk of bias' + 'Applicability concerns').",
    [Column("Study","text",True,"Study name"), Column("Domain","text",True,"Bias domain"),
     Column("Judgement","text",True,"Low / Unclear (Some concerns) / High"),
     Column("Panel","text",False,"Optional panel, e.g. 'Risk of bias' or 'Applicability concerns'")],
    {"Study": (["Combaret 2002"]*7 + ["Chicard 2018"]*7 + ["Yagyu 2016"]*7),
     "Panel": (["Risk of bias"]*4 + ["Applicability concerns"]*3)*3,
     "Domain": (["Patient selection","Index test","Reference standard","Flow and timing",
                 "Patient selection","Index test","Reference standard"])*3,
     "Judgement": ["High","Unclear","Low","Low","High","Low","Low",
                   "High","Unclear","Unclear","High","Low","Low","Low",
                   "Unclear","Low","Low","Low","Low","Low","Low"]},
    r_rob))


def r_gantt(df, opt):
    fig, ax = new_fig(opt)
    task = _col(df, "Task").astype(str); start = _col(df, "Start"); end = _col(df, "End")
    try:
        s = pd.to_datetime(start); e = pd.to_datetime(end); numeric = False
    except Exception:
        s = _num(start); e = _num(end); numeric = True
    d = pd.DataFrame({"t": task, "s": s, "e": e}).dropna()
    y = np.arange(len(d))[::-1]
    for i, (_, row) in enumerate(d.iterrows()):
        width = (row["e"] - row["s"])
        ax.barh(y[i], width, left=row["s"], height=0.55,
                color=palette(opt)[i % 8], edgecolor="white", zorder=3)
    ax.set_yticks(y); ax.set_yticklabels(d["t"])
    if not numeric:
        fig.autofmt_xdate()
    return finish(fig, ax, opt, "Time", "Task", legend_ok=False)

register(PlotSpec("gantt", "Gantt / timeline", "7. Study-flow diagrams",
    "Project or trial schedule (task start → end).",
    [Column("Task","text",True,"Task name"), Column("Start","text",True,"Start (date or number)"),
     Column("End","text",True,"End (date or number)")],
    {"Task": ["Design","Recruit","Analyse","Write-up"],
     "Start": ["2026-01-01","2026-02-01","2026-05-01","2026-07-01"],
     "End": ["2026-02-01","2026-05-01","2026-07-01","2026-09-01"]},
    r_gantt))


# ===========================================================================
# CATEGORY 8 — META-ANALYSIS (reuses the polished bibliometric_pipeline.meta_analysis renderers)
# ===========================================================================
_MZ = 1.959963985

def _meta_ec(df):
    """Study-level effect + 95% CI (or SE) -> labels, yi, vi on the analysis scale."""
    lab = _col(df, "Study").astype(str).tolist()
    yi = _num(_col(df, "Effect")).values.astype(float)
    se_c = _col(df, "SE")
    if se_c is not None and _num(se_c).notna().any():
        vi = _num(se_c).values.astype(float) ** 2
    else:
        lo = _num(_col(df, "LowerCI")).values.astype(float)
        hi = _num(_col(df, "UpperCI")).values.astype(float)
        vi = ((hi - lo) / (2 * _MZ)) ** 2
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0)
    return [l for l, o in zip(lab, ok) if o], yi[ok], vi[ok]

_META_EC_COLS = [Column("Study", "text", True, "Study label"),
                 Column("Effect", "number", True, "Effect on the analysis scale (use log OR/RR/HR for ratios)"),
                 Column("LowerCI", "number", False, "Lower 95% CI (or give SE)"),
                 Column("UpperCI", "number", False, "Upper 95% CI (or give SE)"),
                 Column("SE", "number", False, "Standard error (alternative to CI)")]
_META_EC_EX = {"Study": [f"Study {i}" for i in range(1, 9)],
               "Effect": [0.20, 0.50, 0.10, 0.80, 0.40, 0.60, 0.30, 0.55],
               "LowerCI": [-0.19, 0.06, -0.24, 0.32, 0.01, 0.16, -0.04, 0.11],
               "UpperCI": [0.59, 0.94, 0.44, 1.28, 0.79, 1.04, 0.64, 0.99],
               "SE": [None] * 8}

def rm_forest(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); r = MA.pool(yi, vi, "random")
    return MA.forest_plot(lab, yi, vi, r, "raw", "Effect", title=(opt.title or ""))

def rm_funnel(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); r = MA.pool(yi, vi, "random")
    return MA.funnel_plot(yi, vi, r, "raw", "Effect")

def rm_radial(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); return MA.radial_plot(yi, vi)

def rm_baujat(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); return MA.baujat_plot(lab, yi, vi)

def rm_loo(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); r = MA.pool(yi, vi, "random")
    return MA._loo_forest(lab, MA.leave_one_out(yi, vi, "random"), r, "raw")

def rm_cumulative(df, opt):
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df)
    yr = _num(_col(df, "Year")).values
    rows, idx = MA.cumulative(yi, vi, yr, "random")
    return MA._cumulative_forest(lab, rows, idx, "raw")

def rm_labbe(df, opt):
    from . import meta_analysis as MA
    return MA.labbe_plot(df)

def rm_sroc(df, opt):
    from . import meta_analysis as MA
    return MA.run_dta(df).figures["Summary ROC (SROC)"]

def rm_deeks(df, opt):
    from . import meta_analysis as MA
    return MA.run_dta(df).figures["Deeks' funnel plot"]

_LABBE_COLS = [Column("Study", "text", True, "Study"), Column("Events1", "int", True, "Events, group 1"),
               Column("N1", "int", True, "N, group 1"), Column("Events2", "int", True, "Events, group 2"),
               Column("N2", "int", True, "N, group 2")]
_LABBE_EX = {"Study": [f"Trial {i}" for i in range(1, 7)], "Events1": [12, 20, 8, 15, 25, 10],
             "N1": [100, 110, 90, 120, 130, 95], "Events2": [20, 28, 14, 22, 33, 16],
             "N2": [100, 108, 92, 118, 128, 96]}
_DTA_COLS = [Column("Study", "text", True, "Study"), Column("TP", "int", True, "True positives"),
             Column("FP", "int", True, "False positives"), Column("FN", "int", True, "False negatives"),
             Column("TN", "int", True, "True negatives")]
_DTA_EX = {"Study": [f"S{i}" for i in range(1, 8)], "TP": [25, 18, 30, 12, 40, 22, 33],
           "FP": [3, 5, 4, 2, 6, 3, 5], "FN": [4, 6, 3, 5, 2, 4, 3], "TN": [60, 55, 70, 40, 80, 50, 65]}

_CAT8 = "8. Meta-analysis"
register(PlotSpec("forest_meta", "Forest plot", _CAT8,
    "Publication-ready forest (meta::forest style) with pooled diamond, weights, heterogeneity and a "
    "95% prediction-interval band. Effect on the analysis scale (log for ratios).",
    _META_EC_COLS, _META_EC_EX, rm_forest))
register(PlotSpec("funnel_meta", "Funnel plot (contour-enhanced)", _CAT8,
    "Contour-enhanced funnel with significance shading + pooled pseudo-CI (publication-bias check).",
    _META_EC_COLS, _META_EC_EX, rm_funnel))
register(PlotSpec("radial_meta", "Radial (Galbraith) plot", _CAT8,
    "Radial/Galbraith plot of standardized effect vs precision.",
    _META_EC_COLS, _META_EC_EX, rm_radial))
register(PlotSpec("baujat_meta", "Baujat plot", _CAT8,
    "Which studies drive heterogeneity vs influence the pooled effect.",
    _META_EC_COLS, _META_EC_EX, rm_baujat))
register(PlotSpec("loo_meta", "Leave-one-out forest", _CAT8,
    "Sensitivity analysis: pooled effect recomputed omitting each study in turn.",
    _META_EC_COLS, _META_EC_EX, rm_loo))
register(PlotSpec("cumul_meta", "Cumulative forest", _CAT8,
    "How the evidence accrued — pooled effect after adding studies in order (needs a Year column).",
    _META_EC_COLS + [Column("Year", "number", True, "Year / order for accumulation")],
    {**_META_EC_EX, "Year": [2004, 2008, 2010, 2012, 2015, 2018, 2020, 2022]}, rm_cumulative))
register(PlotSpec("labbe_meta", "L'Abbé plot", _CAT8,
    "Binary-outcome event rates: control vs treatment arm per study.",
    _LABBE_COLS, _LABBE_EX, rm_labbe))
register(PlotSpec("sroc_meta", "SROC (diagnostic accuracy)", _CAT8,
    "Summary ROC with the Reitsma bivariate/HSROC summary point + 95% confidence ellipse (from TP/FP/FN/TN).",
    _DTA_COLS, _DTA_EX, rm_sroc))
register(PlotSpec("deeks_meta", "Deeks' funnel (DTA bias)", _CAT8,
    "Deeks' funnel-plot asymmetry test for diagnostic accuracy publication bias.",
    _DTA_COLS, _DTA_EX, rm_deeks))


def rm_bubble(df, opt):
    """Meta-regression bubble plot (effect vs a study-level moderator)."""
    from . import meta_analysis as MA
    yi = _num(_col(df, "Effect")).values.astype(float)
    se_c = _col(df, "SE")
    if se_c is not None and _num(se_c).notna().any():
        vi = _num(se_c).values.astype(float) ** 2
    else:
        lo = _num(_col(df, "LowerCI")).values.astype(float)
        hi = _num(_col(df, "UpperCI")).values.astype(float)
        vi = ((hi - lo) / (2 * _MZ)) ** 2
    x = _num(_col(df, "Moderator")).values.astype(float)
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0) & np.isfinite(x)
    yi, vi, x = yi[ok], vi[ok], x[ok]
    reg = MA.metareg(yi, vi, x, "random")
    return MA.bubble_plot(x, yi, vi, reg, "raw", opt.xlabel or "Moderator")

def rm_drapery(df, opt):
    """Drapery plot — each study's two-sided p-value (confidence) curve + pooled."""
    from scipy import stats as _st
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); se = np.sqrt(vi)
    r = MA.pool(yi, vi, "random")
    lo = float(np.min(yi - 4 * se)); hi = float(np.max(yi + 4 * se))
    th = np.linspace(lo, hi, 500)
    fig, ax = plt.subplots(figsize=(7.6, 5.3), dpi=200)
    for y, s in zip(yi, se):
        ax.plot(th, 2 * (1 - _st.norm.cdf(np.abs(th - y) / s)), color="#4682B4", lw=0.8, alpha=0.45, zorder=2)
    ax.plot(th, 2 * (1 - _st.norm.cdf(np.abs(th - r["est"]) / r["se"])), color="#E8912A", lw=2.4, zorder=3)
    ax.axhline(0.05, color="#c3423f", ls="--", lw=1)
    ax.axvline(0.0, color="#41566b", ls=":", lw=1)
    ax.set_ylim(0, 1.02); ax.set_xlim(lo, hi)
    ax.set_xlabel("Effect", fontsize=11, color="#12283b")
    ax.set_ylabel("p-value (two-sided)", fontsize=11, color="#12283b")
    ax.set_title("Drapery plot", fontsize=12.5, fontweight="bold", color="#12283b")
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); return fig

def rm_gosh(df, opt):
    """GOSH plot — pooled effect vs I^2 across many study subsets."""
    import itertools
    from . import meta_analysis as MA
    lab, yi, vi = _meta_ec(df); k = len(yi)
    rng = np.random.default_rng(0); cap = 2500
    if k <= 13:
        subs = [c for r in range(2, k + 1) for c in itertools.combinations(range(k), r)]
        if len(subs) > cap:
            subs = [subs[i] for i in rng.choice(len(subs), cap, replace=False)]
    else:
        subs = [tuple(rng.choice(k, int(rng.integers(2, k + 1)), replace=False)) for _ in range(cap)]
    est, i2 = [], []
    for c in subs:
        c = list(c); rr = MA.pool(yi[c], vi[c], "fixed")
        est.append(rr["est"]); i2.append(rr["I2"])
    fig, ax = plt.subplots(figsize=(7.2, 5.3), dpi=200)
    ax.scatter(est, i2, s=7, alpha=0.22, color="#4682B4", edgecolor="none", zorder=2)
    ax.set_xlabel("Pooled effect (subset)", fontsize=11, color="#12283b")
    ax.set_ylabel("I² (%)", fontsize=11, color="#12283b")
    ax.set_title(f"GOSH plot ({len(subs)} subsets)", fontsize=12.5, fontweight="bold", color="#12283b")
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); return fig

register(PlotSpec("bubble_meta", "Bubble plot (meta-regression)", _CAT8,
    "Meta-regression of the effect on a study-level moderator, with a fitted line and precision-scaled bubbles.",
    _META_EC_COLS + [Column("Moderator", "number", True, "Study-level covariate (e.g. year, dose, mean age)")],
    {**_META_EC_EX, "Moderator": [1, 2, 3, 4, 5, 6, 7, 8]}, rm_bubble))
register(PlotSpec("drapery_meta", "Drapery plot", _CAT8,
    "Confidence (p-value) curves for each study plus the pooled curve — an alternative to the forest.",
    _META_EC_COLS, _META_EC_EX, rm_drapery))
register(PlotSpec("gosh_meta", "GOSH plot", _CAT8,
    "Graphical display of study heterogeneity: pooled effect vs I² across many study subsets (spots outliers/clusters).",
    _META_EC_COLS, _META_EC_EX, rm_gosh))
