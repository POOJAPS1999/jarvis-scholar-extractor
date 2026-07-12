"""
network_viz.py
==============
VOSviewer-style network rendering for the Scientometrics maps.

Matches the VOSviewer "network visualization" look:
  - cluster colours from a VOSviewer-like palette
  - node circles sized by weight
  - LABELS centred on nodes with font size proportional to weight (the
    signature VOSviewer trait — the biggest terms get the biggest labels)
  - faint straight edges, clean white background, equal aspect ratio

Interactive figure via Plotly (zoom/pan/hover + built-in PNG), a matching
static matplotlib PNG for explicit download, and a VOSviewer-style density
overlay. Input is the (items, edges, extra) structure from networks.py.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

# VOSviewer-like cluster palette (distinct hues, cluster 1 = red, 2 = green, …)
_PALETTE = ["#d62728", "#2ca02c", "#1f77b4", "#e6b800", "#9467bd",
            "#17becf", "#ff7f0e", "#e377c2", "#8c564b", "#7f7f7f",
            "#bcbd22", "#393b79"]
_BG = "#ffffff"
_EDGE = "rgba(150,165,185,0.30)"
_LABEL_INK = "#1a1a1a"


def _weight_of(extra_row: dict) -> float:
    for k, v in (extra_row or {}).items():
        if k.startswith("weight<"):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _score_of(extra_row: dict) -> float:
    for k, v in (extra_row or {}).items():
        if k.startswith("score<"):
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _top_subgraph(items, edges, extra, top_n):
    import networkx as nx
    weights = {i: _weight_of(extra.get(i, {})) for i in items}
    keep = set(sorted(items, key=lambda i: weights[i], reverse=True)[:top_n])
    G = nx.Graph()
    for i in keep:
        G.add_node(i, label=items[i], weight=weights[i], score=_score_of(extra.get(i, {})))
    for (a, b), w in edges.items():
        if a in keep and b in keep:
            G.add_edge(a, b, weight=float(w))
    G.remove_nodes_from([n for n in list(G.nodes) if G.degree(n) == 0])
    return G


def _layout(G, seed=42):
    import networkx as nx
    if G.number_of_nodes() == 0:
        return {}
    # Kamada-Kawai gives the smooth, spread, organic look VOSviewer has;
    # fall back to spring layout if it can't converge.
    try:
        pos = nx.kamada_kawai_layout(G, weight="weight")
    except Exception:
        k = 1.8 / np.sqrt(max(1, G.number_of_nodes()))
        pos = nx.spring_layout(G, weight="weight", k=k, seed=seed, iterations=150)
    return pos


def _communities(G):
    import networkx as nx
    if G.number_of_edges() == 0:
        return {n: 0 for n in G.nodes}
    try:
        comms = nx.algorithms.community.greedy_modularity_communities(G, weight="weight")
        return {n: ci for ci, c in enumerate(comms) for n in c}
    except Exception:
        return {n: 0 for n in G.nodes}


def _norm(weights):
    w = np.asarray(weights, dtype=float)
    if len(w) == 0 or w.max() == w.min():
        return np.zeros(len(w))
    return (w - w.min()) / (w.max() - w.min())


def network_figure(items: Dict[str, str], edges: Dict[Tuple[str, str], int],
                   extra: Dict[str, dict], title: str = "", top_n: int = 60,
                   label_top: int = 45, weight_name: str = "Documents"):
    """Interactive VOSviewer-style network (Plotly): cluster-coloured circles
    sized by weight, labels centred on nodes with weight-scaled font size."""
    import plotly.graph_objects as go

    G = _top_subgraph(items, edges, extra, top_n)
    if G.number_of_nodes() == 0:
        fig = go.Figure()
        fig.add_annotation(text="Not enough connected nodes at these settings — try a larger dataset "
                           "or lower the min-occurrence / min-shared-refs threshold.",
                           showarrow=False, font=dict(size=13, color="#4a627a"))
        fig.update_layout(height=420, paper_bgcolor=_BG, plot_bgcolor=_BG)
        return fig

    pos = _layout(G)
    comm = _communities(G)
    nodes = list(G.nodes)
    wn = _norm([G.nodes[n]["weight"] for n in nodes])
    wn_by = {n: wn[i] for i, n in enumerate(nodes)}
    sizes = 10 + 52 * wn          # circle diameter (px)

    # faint edges (single trace)
    ex, ey = [], []
    for a, b in G.edges():
        ex += [pos[a][0], pos[b][0], None]
        ey += [pos[a][1], pos[b][1], None]
    edge_trace = go.Scatter(x=ex, y=ey, mode="lines",
                            line=dict(width=0.7, color=_EDGE), hoverinfo="skip", showlegend=False)

    # node circles (no text on the marker — labels are annotations)
    nx_, ny, colors, hover = [], [], [], []
    for n in nodes:
        nx_.append(pos[n][0])
        ny.append(pos[n][1])
        colors.append(_PALETTE[comm.get(n, 0) % len(_PALETTE)])
        hover.append(f"<b>{G.nodes[n]['label']}</b><br>{weight_name}: {int(G.nodes[n]['weight'])}"
                     f"<br>Cluster: {comm.get(n, 0) + 1}<br>Links: {G.degree(n)}")
    node_trace = go.Scatter(
        x=nx_, y=ny, mode="markers", hovertext=hover, hoverinfo="text",
        marker=dict(size=sizes, color=colors, opacity=0.72, line=dict(width=1, color="white")),
        showlegend=False)

    # labels as annotations — font size ∝ weight, centred on the node
    order = sorted(nodes, key=lambda n: G.nodes[n]["weight"], reverse=True)[:label_top]
    ann = []
    for n in order:
        fs = 9 + 20 * wn_by[n]     # 9 → 29 px
        ann.append(dict(x=pos[n][0], y=pos[n][1], text=str(G.nodes[n]["label"]),
                        showarrow=False, xanchor="center", yanchor="middle",
                        font=dict(size=fs, color=_LABEL_INK, family="Arial")))
    ann.append(dict(text="Jarvis Scholar", x=1, y=0, xref="paper", yref="paper",
                    showarrow=False, xanchor="right", yanchor="bottom",
                    font=dict(size=10, color="#b8c6d8")))

    fig = go.Figure([edge_trace, node_trace])
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color="#12283b")),
        height=640, paper_bgcolor=_BG, plot_bgcolor=_BG, margin=dict(l=6, r=6, t=44, b=6),
        hovermode="closest", annotations=ann,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),  # equal aspect → round circles
    )
    return fig


def network_png(items, edges, extra, title="", top_n: int = 60, label_top: int = 45,
                weight_name: str = "Documents") -> bytes:
    """Static VOSviewer-style PNG (matplotlib) — same look as the interactive
    figure, for an explicit download button."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    G = _top_subgraph(items, edges, extra, top_n)
    fig, ax = plt.subplots(figsize=(11, 9), dpi=150)
    if G.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "Not enough connected nodes at these settings.",
                ha="center", va="center", color="#4a627a")
        ax.axis("off")
    else:
        pos = _layout(G)
        comm = _communities(G)
        nodes = list(G.nodes)
        wn = _norm([G.nodes[n]["weight"] for n in nodes])
        wn_by = {n: wn[i] for i, n in enumerate(nodes)}

        # edges
        for a, b in G.edges():
            ax.plot([pos[a][0], pos[b][0]], [pos[a][1], pos[b][1]],
                    color="#96a5b9", alpha=0.30, linewidth=0.7, zorder=1)
        # circles (data-coordinate radii so they scale with the layout)
        xs = np.array([pos[n][0] for n in nodes])
        ys = np.array([pos[n][1] for n in nodes])
        span = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-6)
        for n in nodes:
            r = (0.010 + 0.055 * wn_by[n]) * span
            ax.add_patch(Circle(pos[n], r, facecolor=_PALETTE[comm.get(n, 0) % len(_PALETTE)],
                                edgecolor="white", linewidth=1.0, alpha=0.72, zorder=3))
        # labels — font size ∝ weight, centred
        order = sorted(nodes, key=lambda n: G.nodes[n]["weight"], reverse=True)[:label_top]
        for n in order:
            ax.text(pos[n][0], pos[n][1], str(G.nodes[n]["label"]),
                    fontsize=6.5 + 12 * wn_by[n], ha="center", va="center",
                    color=_LABEL_INK, zorder=4)
        ax.set_xlim(xs.min() - 0.12 * span, xs.max() + 0.12 * span)
        ax.set_ylim(ys.min() - 0.12 * span, ys.max() + 0.12 * span)
        ax.set_aspect("equal")
        ax.axis("off")
    if title:
        ax.set_title(title, color="#12283b", fontsize=14, fontweight="bold", loc="left")
    fig.text(0.99, 0.01, "Jarvis Scholar", ha="right", va="bottom", fontsize=8,
             color="#b8c6d8", style="italic")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def density_figure(items, edges, extra, title="", top_n: int = 120, label_top: int = 45):
    """VOSviewer-style density overlay: a smooth heat field where terms
    cluster densely, with the top labels on top (weight-scaled)."""
    import plotly.graph_objects as go

    G = _top_subgraph(items, edges, extra, top_n)
    if G.number_of_nodes() == 0:
        fig = go.Figure()
        fig.add_annotation(text="Not enough connected nodes at these settings — try a larger dataset "
                           "or lower the threshold.", showarrow=False, font=dict(size=13, color="#4a627a"))
        fig.update_layout(height=420)
        return fig
    pos = _layout(G)
    nodes = list(G.nodes)
    xs = np.array([pos[n][0] for n in nodes])
    ys = np.array([pos[n][1] for n in nodes])
    ws = np.array([G.nodes[n]["weight"] for n in nodes], dtype=float)
    wn = _norm(ws)

    gx = np.linspace(xs.min() - 0.1, xs.max() + 0.1, 130)
    gy = np.linspace(ys.min() - 0.1, ys.max() + 0.1, 130)
    GX, GY = np.meshgrid(gx, gy)
    span = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-3)
    bw = 0.06 * span
    Z = np.zeros_like(GX)
    for x, y, w in zip(xs, ys, ws):
        Z += w * np.exp(-((GX - x) ** 2 + (GY - y) ** 2) / (2 * bw ** 2))

    # VOSviewer density colours: blue (low) → green → yellow → red (high)
    scale = [[0.0, "#2b4b8f"], [0.35, "#2ca02c"], [0.7, "#e6d800"], [1.0, "#d62728"]]
    heat = go.Heatmap(x=gx, y=gy, z=Z, colorscale=scale, showscale=False, zsmooth="best")
    order = sorted(range(len(nodes)), key=lambda i: ws[i], reverse=True)[:label_top]
    lab = go.Scatter(
        x=[xs[i] for i in order], y=[ys[i] for i in order], mode="text",
        text=[str(G.nodes[nodes[i]]["label"]) for i in order],
        textfont=dict(size=[9 + 16 * wn[i] for i in order], color="#111111"),
        hoverinfo="text", hovertext=[f"{G.nodes[nodes[i]]['label']} ({int(ws[i])})" for i in order],
        showlegend=False)
    fig = go.Figure([heat, lab])
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color="#12283b")),
        height=640, paper_bgcolor=_BG, plot_bgcolor=_BG, margin=dict(l=6, r=6, t=44, b=6),
        xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor="x", scaleratio=1),
        annotations=[dict(text="Jarvis Scholar", x=1, y=0, xref="paper", yref="paper",
                          showarrow=False, xanchor="right", yanchor="bottom",
                          font=dict(size=10, color="#7f97ae"))],
    )
    return fig
