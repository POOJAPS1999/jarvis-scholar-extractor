"""
charts.py
=========
Publication-quality static charts for the Scientometrics module — the
Biblioshiny look (clean ggplot-style bars/lines) but a bit more refined, and
every chart is exportable as a crisp PNG.

Pure matplotlib; returns Figure objects + PNG bytes. A tiny Streamlit helper
(render_chart) renders the figure and a PNG download button in one call.
"""
from __future__ import annotations

import io
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")  # headless / server-side
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np

# Jarvis Scholar palette
_CYAN = "#0e7f9c"
_CYAN_LT = "#7fd3e6"
_INDIGO = "#4f46e5"
_INK = "#12283b"
_SUB = "#4a627a"
_GRID = "#e6eef7"

# sequential gradient light-cyan -> deep teal/indigo, for value-ranked bars
_SEQ = LinearSegmentedColormap.from_list("js_seq", ["#9fe0ef", _CYAN, "#123f78"])


def _style(ax, title=None, xlabel=None, ylabel=None):
    ax.set_facecolor("white")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#c7d6e6")
    ax.tick_params(colors=_SUB, labelsize=9, length=0)
    if title:
        ax.set_title(title, color=_INK, fontsize=13, fontweight="bold", loc="left", pad=12)
    if xlabel:
        ax.set_xlabel(xlabel, color=_SUB, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, color=_SUB, fontsize=10)


def _watermark(fig):
    fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom",
             fontsize=8, color="#b8c6d8", style="italic")


def _colors(values):
    v = np.asarray(values, dtype=float)
    if v.max() == v.min():
        return [_CYAN] * len(v)
    norm = (v - v.min()) / (v.max() - v.min())
    return [_SEQ(0.15 + 0.8 * x) for x in norm]


def hbar(labels: List[str], values: List[float], title: str = "", xlabel: str = "",
         value_fmt: str = "{:,.0f}") -> plt.Figure:
    """Horizontal bars, highest at top, value labels at bar ends, gradient fill."""
    n = len(labels)
    fig, ax = plt.subplots(figsize=(8.4, max(2.4, 0.42 * n + 1.1)), dpi=150)
    y = np.arange(n)[::-1]  # first item on top
    bars = ax.barh(y, values, color=_colors(values), edgecolor="white", height=0.72, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels([str(l) for l in labels], fontsize=9, color=_INK)
    ax.xaxis.grid(True, color=_GRID, zorder=0)
    ax.set_axisbelow(True)
    vmax = max(values) if len(values) and max(values) else 1
    for b, v in zip(bars, values):
        ax.text(b.get_width() + vmax * 0.012, b.get_y() + b.get_height() / 2,
                value_fmt.format(v), va="center", ha="left", fontsize=8.5,
                color=_INK, fontweight="bold")
    ax.set_xlim(0, vmax * 1.14)
    _style(ax, title, xlabel, None)
    _watermark(fig)
    fig.tight_layout()
    return fig


def vbar(x: List, y: List[float], title: str = "", xlabel: str = "", ylabel: str = "",
         value_fmt: str = "{:,.0f}") -> plt.Figure:
    """Vertical bars with value labels on top."""
    n = len(x)
    fig, ax = plt.subplots(figsize=(8.4, 4.2), dpi=150)
    xs = np.arange(n)
    bars = ax.bar(xs, y, color=_colors(y), edgecolor="white", width=0.66, zorder=3)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(v) for v in x], fontsize=9, color=_INK)
    ax.yaxis.grid(True, color=_GRID, zorder=0)
    ax.set_axisbelow(True)
    ymax = max(y) if len(y) and max(y) else 1
    for b, v in zip(bars, y):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + ymax * 0.02,
                value_fmt.format(v), ha="center", va="bottom", fontsize=8.5,
                color=_INK, fontweight="bold")
    ax.set_ylim(0, ymax * 1.14)
    _style(ax, title, xlabel, ylabel)
    _watermark(fig)
    fig.tight_layout()
    return fig


def line(x: List, y: List[float], title: str = "", xlabel: str = "", ylabel: str = "",
         color: str = _INDIGO, fill: bool = True) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.4, 4.2), dpi=150)
    xs = np.arange(len(x))
    ax.plot(xs, y, color=color, linewidth=2.4, marker="o", markersize=6,
            markerfacecolor="white", markeredgecolor=color, markeredgewidth=2, zorder=3)
    if fill:
        ax.fill_between(xs, y, color=color, alpha=0.10, zorder=1)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(v) for v in x], fontsize=9, color=_INK)
    ax.yaxis.grid(True, color=_GRID, zorder=0)
    ax.set_axisbelow(True)
    for xi, yi in zip(xs, y):
        ax.text(xi, yi + (max(y) if y else 1) * 0.03, f"{yi:,.0f}", ha="center",
                va="bottom", fontsize=8.5, color=_INK, fontweight="bold")
    _style(ax, title, xlabel, ylabel)
    _watermark(fig)
    fig.tight_layout()
    return fig


def bradford_curve(rank: List[int], cumulative: List[int], zones: Optional[List[str]] = None,
                   title: str = "Bradford's law of scattering") -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8.4, 4.2), dpi=150)
    ax.plot(rank, cumulative, color=_CYAN, linewidth=2.4, zorder=3)
    ax.fill_between(rank, cumulative, color=_CYAN, alpha=0.10, zorder=1)
    # shade the core (Zone 1) region if we know where it ends
    if zones:
        core = [r for r, z in zip(rank, zones) if z == "Zone 1"]
        if core:
            ax.axvspan(min(core), max(core), color=_CYAN_LT, alpha=0.18, zorder=0)
            ax.text(max(core), max(cumulative) * 0.06, "  core zone", color=_CYAN,
                    fontsize=9, va="bottom", ha="left", fontweight="bold")
    ax.yaxis.grid(True, color=_GRID, zorder=0)
    ax.set_axisbelow(True)
    _style(ax, title, "Source rank", "Cumulative documents")
    _watermark(fig)
    fig.tight_layout()
    return fig


_QUAD_COLORS = {
    "Motor themes": "#0e7f9c", "Niche themes": "#7d3c98",
    "Basic & transversal": "#d8572a", "Emerging or declining": "#5f6a6a",
}


def thematic_map(themes, x="Centrality", y="Density", size="Occurrences",
                 label="Theme", quad="Quadrant", title="Strategic thematic map") -> plt.Figure:
    """Biblioshiny-style strategic diagram: bubbles positioned by Callon
    centrality (x) and density (y), split into four quadrants by the median."""
    import numpy as np
    fig, ax = plt.subplots(figsize=(9, 7.2), dpi=150)
    xs = themes[x].astype(float).values
    ys = themes[y].astype(float).values
    sz = themes[size].astype(float).values
    mx, my = float(np.median(xs)), float(np.median(ys))
    smax = sz.max() if len(sz) and sz.max() else 1
    sizes = 260 + 2400 * (sz / smax)
    colors = [_QUAD_COLORS.get(q, _CYAN) for q in themes[quad]]
    ax.axvline(mx, color="#c7d6e6", linestyle="--", linewidth=1, zorder=1)
    ax.axhline(my, color="#c7d6e6", linestyle="--", linewidth=1, zorder=1)
    ax.scatter(xs, ys, s=sizes, c=colors, alpha=0.55, edgecolors="white", linewidths=1.3, zorder=3)
    for _, r in themes.iterrows():
        ax.text(float(r[x]), float(r[y]), str(r[label]), ha="center", va="center",
                fontsize=8.5, color=_INK, fontweight="bold", zorder=4)
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    corners = [("Motor themes", x1, y1, "right", "top"),
               ("Niche themes", x0, y1, "left", "top"),
               ("Basic & transversal", x1, y0, "right", "bottom"),
               ("Emerging / declining", x0, y0, "left", "bottom")]
    for text, cx, cy, ha, va in corners:
        ax.text(cx, cy, text, ha=ha, va=va, fontsize=9.5, color="#8aa0b8",
                style="italic", zorder=2)
    _style(ax, title, "Relevance (centrality) →", "Development (density) →")
    _watermark(fig)
    fig.tight_layout()
    return fig


def fig_to_png(fig: plt.Figure, dpi: int = 200) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    return buf.getvalue()


def render_chart(fig, filename: str, key: str):
    """Streamlit: show the figure + a 'Download PNG' button, then free it."""
    import streamlit as st
    st.pyplot(fig, use_container_width=True)
    st.download_button("⬇ Download PNG", data=fig_to_png(fig),
                       file_name=f"{filename}.png", mime="image/png", key=f"png_{key}")
    plt.close(fig)
