"""
network_viz.py
==============
Interactive network rendering for the Scientometrics maps (Phase 2), using
networkx for layout + Plotly for an interactive figure (zoom / pan / hover,
and Plotly's built-in "download as PNG"). Also a VOSviewer-style density
overlay for the keyword map.

Input is the (items, edges, extra) structure from networks.py. Large
networks are reduced to the top-N nodes by weight for a readable map.
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

# Jarvis Scholar cluster palette (colour-blind-friendly-ish, distinct hues)
_PALETTE = ["#0e7f9c", "#4f46e5", "#d8572a", "#1d9e75", "#c0392b",
            "#b8860b", "#7d3c98", "#2c7fb8", "#d81b60", "#5f6a6a"]
_BG = "#ffffff"


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
    # drop isolates so the layout isn't dominated by floating dots
    G.remove_nodes_from([n for n in list(G.nodes) if G.degree(n) == 0])
    return G


def _layout(G, seed=42):
    import networkx as nx
    if G.number_of_nodes() == 0:
        return {}
    k = 1.8 / np.sqrt(max(1, G.number_of_nodes()))
    return nx.spring_layout(G, weight="weight", k=k, seed=seed, iterations=120)


def _communities(G):
    import networkx as nx
    if G.number_of_edges() == 0:
        return {n: 0 for n in G.nodes}
    try:
        comms = nx.algorithms.community.greedy_modularity_communities(G, weight="weight")
        return {n: ci for ci, c in enumerate(comms) for n in c}
    except Exception:
        return {n: 0 for n in G.nodes}


def network_figure(items: Dict[str, str], edges: Dict[Tuple[str, str], int],
                   extra: Dict[str, dict], title: str = "", top_n: int = 60,
                   label_top: int = 30, weight_name: str = "Documents"):
    """Interactive Plotly network of the top-N nodes by weight, coloured by
    detected community, sized by weight. Returns a plotly Figure."""
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
    weights = np.array([G.nodes[n]["weight"] for n in G.nodes], dtype=float)
    wmin, wmax = weights.min(), weights.max()
    sizes = 12 + 34 * ((weights - wmin) / (wmax - wmin) if wmax > wmin else np.zeros_like(weights))

    # edges
    emax = max((d["weight"] for *_e, d in G.edges(data=True)), default=1)
    edge_traces = []
    for a, b, d in G.edges(data=True):
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None], mode="lines",
            line=dict(width=0.4 + 3.0 * d["weight"] / emax, color="rgba(120,140,165,0.35)"),
            hoverinfo="skip", showlegend=False))

    # rank nodes by weight to decide which get text labels
    order = sorted(G.nodes, key=lambda n: G.nodes[n]["weight"], reverse=True)
    label_set = set(order[:label_top])
    nx_, ny, ntext, nhover, ncolor, nlabel = [], [], [], [], [], []
    for n in G.nodes:
        x, y = pos[n]
        nx_.append(x)
        ny.append(y)
        lbl = str(G.nodes[n]["label"])
        nlabel.append(lbl if n in label_set else "")
        ntext.append(lbl if n in label_set else "")
        nhover.append(f"<b>{lbl}</b><br>{weight_name}: {int(G.nodes[n]['weight'])}"
                      f"<br>Citations: {G.nodes[n]['score']:.0f}<br>Links: {G.degree(n)}")
        ncolor.append(_PALETTE[comm.get(n, 0) % len(_PALETTE)])

    node_trace = go.Scatter(
        x=nx_, y=ny, mode="markers+text", text=ntext, textposition="top center",
        textfont=dict(size=10, color="#12283b"),
        hovertext=nhover, hoverinfo="text",
        marker=dict(size=sizes, color=ncolor, line=dict(width=1.2, color="white"), opacity=0.92),
        showlegend=False)

    fig = go.Figure(edge_traces + [node_trace])
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color="#12283b")),
        height=560, paper_bgcolor=_BG, plot_bgcolor=_BG, margin=dict(l=10, r=10, t=44, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False), hovermode="closest",
        annotations=[dict(text="Jarvis Scholar", x=1, y=0, xref="paper", yref="paper",
                          showarrow=False, font=dict(size=10, color="#b8c6d8"),
                          xanchor="right", yanchor="bottom")],
    )
    return fig


def network_png(items, edges, extra, title="", top_n: int = 60, label_top: int = 30,
                weight_name: str = "Documents") -> bytes:
    """Static matplotlib render of the same top-N network, for an explicit
    'Download PNG' button (same layout/colours as the interactive figure)."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    G = _top_subgraph(items, edges, extra, top_n)
    fig, ax = plt.subplots(figsize=(10, 8), dpi=150)
    if G.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "Not enough connected nodes at these settings.",
                ha="center", va="center", color="#4a627a")
        ax.axis("off")
    else:
        pos = _layout(G)
        comm = _communities(G)
        weights = np.array([G.nodes[n]["weight"] for n in G.nodes], dtype=float)
        wmin, wmax = weights.min(), weights.max()
        sizes = 120 + 900 * ((weights - wmin) / (wmax - wmin) if wmax > wmin else np.zeros_like(weights))
        emax = max((d["weight"] for *_e, d in G.edges(data=True)), default=1)
        for a, b, d in G.edges(data=True):
            x0, y0 = pos[a]
            x1, y1 = pos[b]
            ax.plot([x0, x1], [y0, y1], color="#8a9cb5", alpha=0.28,
                    linewidth=0.3 + 2.4 * d["weight"] / emax, zorder=1)
        colors = [_PALETTE[comm.get(n, 0) % len(_PALETTE)] for n in G.nodes]
        ax.scatter([pos[n][0] for n in G.nodes], [pos[n][1] for n in G.nodes],
                   s=sizes, c=colors, edgecolors="white", linewidths=1.1, zorder=3, alpha=0.92)
        order = sorted(G.nodes, key=lambda n: G.nodes[n]["weight"], reverse=True)[:label_top]
        for n in order:
            ax.text(pos[n][0], pos[n][1], str(G.nodes[n]["label"]), fontsize=8,
                    ha="center", va="center", color="#12283b", zorder=4,
                    fontweight="bold")
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


def density_figure(items, edges, extra, title="", top_n: int = 120, label_top: int = 40):
    """VOSviewer-style density overlay: a smooth heat field where terms
    cluster densely, with the top labels on top."""
    import plotly.graph_objects as go

    G = _top_subgraph(items, edges, extra, top_n)
    if G.number_of_nodes() == 0:
        fig = go.Figure()
        fig.add_annotation(text="Not enough connected nodes for a density map.",
                           showarrow=False, font=dict(size=13, color="#4a627a"))
        fig.update_layout(height=420)
        return fig
    pos = _layout(G)
    xs = np.array([pos[n][0] for n in G.nodes])
    ys = np.array([pos[n][1] for n in G.nodes])
    ws = np.array([G.nodes[n]["weight"] for n in G.nodes], dtype=float)

    # gaussian density field on a grid
    gx = np.linspace(xs.min() - 0.1, xs.max() + 0.1, 120)
    gy = np.linspace(ys.min() - 0.1, ys.max() + 0.1, 120)
    GX, GY = np.meshgrid(gx, gy)
    span = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-3)
    bw = 0.06 * span
    Z = np.zeros_like(GX)
    for x, y, w in zip(xs, ys, ws):
        Z += w * np.exp(-((GX - x) ** 2 + (GY - y) ** 2) / (2 * bw ** 2))

    heat = go.Heatmap(x=gx, y=gy, z=Z, colorscale="YlGnBu", reversescale=False,
                      showscale=False, zsmooth="best", opacity=0.9)
    order = sorted(G.nodes, key=lambda n: G.nodes[n]["weight"], reverse=True)[:label_top]
    lab = go.Scatter(x=[pos[n][0] for n in order], y=[pos[n][1] for n in order],
                     mode="text", text=[str(G.nodes[n]["label"]) for n in order],
                     textfont=dict(size=10, color="#0b3b52"), hoverinfo="text",
                     hovertext=[f"{G.nodes[n]['label']} ({int(G.nodes[n]['weight'])})" for n in order],
                     showlegend=False)
    fig = go.Figure([heat, lab])
    fig.update_layout(
        title=dict(text=title, x=0.01, xanchor="left", font=dict(size=15, color="#12283b")),
        height=560, paper_bgcolor=_BG, plot_bgcolor=_BG, margin=dict(l=10, r=10, t=44, b=10),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        annotations=[dict(text="Jarvis Scholar", x=1, y=0, xref="paper", yref="paper",
                          showarrow=False, font=dict(size=10, color="#7f97ae"),
                          xanchor="right", yanchor="bottom")],
    )
    return fig
