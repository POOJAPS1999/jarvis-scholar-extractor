"""
network_meta.py
===============
Frequentist network meta-analysis (netmeta-style graph-theoretical / GLS
estimation) from contrast-level data.

Input template (one row per pairwise comparison within a study):
    Study, Treatment1, Treatment2, TE, seTE
where TE is the effect of Treatment1 vs Treatment2 on the analysis scale
(log OR/RR/HR, or MD). Produces: pooled relative effects vs a reference,
a league table (all pairwise), P-score rankings, heterogeneity (Q, I2, tau2),
a network graph, a forest plot vs reference and a ranking bar chart, plus a
netmeta R script.
"""
from __future__ import annotations

import io
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .plot_studio import _col, _num, fig_to_png
from . import meta_analysis as MA

Z = 1.959963985
STEEL, ORANGE, INK, SUB, GREY, RED = "#4682B4", "#E8912A", "#12283b", "#41566b", "#c3d0dd", "#d8572a"

EXAMPLE = {"Study": ["S1","S2","S3","S4","S5","S6","S7","S8"],
           "Treatment1": ["B","C","C","D","D","B","D","C"],
           "Treatment2": ["A","A","B","B","C","A","A","A"],
           "TE": [-0.30,-0.55,-0.20,-0.45,-0.15,-0.35,-0.60,-0.50],
           "seTE": [0.20,0.25,0.22,0.30,0.28,0.24,0.26,0.30]}

COLUMNS = [("Study", "Study label"), ("Treatment1", "First treatment"),
           ("Treatment2", "Second (comparator) treatment"),
           ("TE", "Effect of Treatment1 vs Treatment2 (log OR/RR/HR or MD)"),
           ("seTE", "Standard error of TE")]


def template_bytes() -> bytes:
    data = pd.DataFrame(EXAMPLE)
    info = pd.DataFrame([(c, "Required", h) for c, h in COLUMNS],
                        columns=["Column", "Required", "What to enter"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        data.to_excel(xl, sheet_name="Data", index=False)
        info.to_excel(xl, sheet_name="Instructions", index=False)
    return buf.getvalue()


def validate(df) -> "list[str]":
    have = {c.strip().lower() for c in df.columns}
    miss = [c for c, _ in COLUMNS if c.strip().lower() not in have]
    p = []
    if miss: p.append("Missing required columns: " + ", ".join(miss))
    if len(df.dropna(how="all")) < 2: p.append("Need at least two comparisons.")
    return p


def _estimate(t1, t2, TE, se, treats, ref, tau2=0.0):
    basics = [t for t in treats if t != ref]
    idx = {t: i for i, t in enumerate(basics)}
    m = len(TE); p = len(basics)
    X = np.zeros((m, p))
    for r in range(m):
        if t1[r] in idx: X[r, idx[t1[r]]] += 1.0
        if t2[r] in idx: X[r, idx[t2[r]]] -= 1.0
    w = 1.0/(se**2 + tau2)
    XtWX = X.T @ (w[:, None]*X)
    d = np.linalg.solve(XtWX, X.T @ (w*TE))
    cov = np.linalg.inv(XtWX)
    resid = TE - X@d
    Q = float(np.sum((1/se**2)*(TE - X@np.linalg.solve(X.T@((1/se**2)[:, None]*X), X.T@((1/se**2)*TE)))**2))
    return d, cov, basics, X, Q


def run_nma(df, scale="log", model="random", reference=None, higher_better=False):
    t1 = _col(df, "Treatment1").astype(str).values
    t2 = _col(df, "Treatment2").astype(str).values
    TE = _num(_col(df, "TE")).values.astype(float)
    se = _num(_col(df, "seTE")).values.astype(float)
    ok = np.isfinite(TE) & np.isfinite(se) & (se > 0)
    t1, t2, TE, se = t1[ok], t2[ok], TE[ok], se[ok]
    studies = _col(df, "Study").astype(str).values[ok] if _col(df, "Study") is not None else None
    treats = sorted(set(t1) | set(t2))
    ref = reference if reference in treats else treats[0]

    d, cov, basics, X, Q = _estimate(t1, t2, TE, se, treats, ref)
    dfree = max(1, len(TE) - len(basics))
    tau2 = 0.0
    if model != "fixed":
        w = 1/se**2
        C = np.sum(w) - np.sum(w**2)/np.sum(w)
        tau2 = max(0.0, (Q - dfree)/C) if C > 0 else 0.0
        d, cov, basics, X, Q = _estimate(t1, t2, TE, se, treats, ref, tau2)
    I2 = max(0.0, (Q - dfree)/Q)*100 if Q > 0 else 0.0

    # full effect vector + covariance (reference = 0)
    order = treats; n = len(order); pos = {t: i for i, t in enumerate(order)}
    dfull = np.zeros(n); C = np.zeros((n, n))
    for a, t in enumerate(basics):
        dfull[pos[t]] = d[a]
        for b, s in enumerate(basics):
            C[pos[t], pos[s]] = cov[a, b]

    def eff(i, j):  # i vs j
        e = dfull[i] - dfull[j]
        v = C[i, i] + C[j, j] - 2*C[i, j]
        s = np.sqrt(max(v, 0))
        return e, (e-Z*s, e+Z*s), s

    disp = lambda x: MA.disp(scale, x)
    # league table (row vs col)
    league = pd.DataFrame(index=order, columns=order, dtype=object)
    for i, ti in enumerate(order):
        for j, tj in enumerate(order):
            if i == j:
                league.iloc[i, j] = ti
            else:
                e, ci, s = eff(i, j)
                league.iloc[i, j] = f"{disp(e):.2f} [{disp(ci[0]):.2f}, {disp(ci[1]):.2f}]"

    # forest vs reference
    rows = []
    for t in order:
        if t == ref: continue
        e, ci, s = eff(pos[t], pos[ref])
        rows.append({"label": t, "e": disp(e), "lo": disp(ci[0]), "hi": disp(ci[1]), "w": None})
    refx = 1.0 if scale == "log" else 0.0
    col = {"log": "Effect", "raw": "MD"}.get(scale, "Effect")
    forest_png = MA._forest(rows, scale, f"vs {ref}", col, title=f"Relative effect vs {ref}",
                            pooled=None, refx=refx, weight_col=False)

    # P-scores
    pscore = {}
    for i, ti in enumerate(order):
        acc = []
        for j, tj in enumerate(order):
            if i == j: continue
            e, ci, s = eff(i, j)  # ti vs tj
            if s == 0: continue
            better = stats.norm.cdf((e)/s) if higher_better else stats.norm.cdf((-e)/s)
            acc.append(better)
        pscore[ti] = float(np.mean(acc)) if acc else np.nan
    ranking = sorted(pscore.items(), key=lambda kv: kv[1], reverse=True)

    # counts per edge / node
    from collections import Counter
    edge_n = Counter(tuple(sorted((a, b))) for a, b in zip(t1, t2))
    node_n = Counter(); [node_n.update([a, b]) for a, b in zip(t1, t2)]

    net_png = _network_graph(order, edge_n, node_n)
    rank_png = _rank_bar(ranking)

    # tables
    league_out = league.reset_index().rename(columns={"index": ""})
    rank_tab = pd.DataFrame({"Treatment": [k for k, _ in ranking],
                             "P-score": [f"{v:.3f}" for _, v in ranking],
                             "Rank": range(1, len(ranking)+1)})
    figs = {"Network graph": net_png, f"Forest (vs {ref})": forest_png, "Ranking (P-scores)": rank_png}
    head = (f"Network meta-analysis: {n} treatments, {len(TE)} comparisons, "
            f"{len(set(studies)) if studies is not None else '?'} studies; reference = {ref}; "
            f"I² = {I2:.0f}%")
    best = ranking[0][0]
    interp = (f"{n} treatments were compared in a connected network. Ranked best to worst by P-score, "
              f"{best} ranked highest (P-score {pscore[best]:.2f}). Global heterogeneity I² = {I2:.0f}% "
              f"(τ² = {tau2:.3f}). The league table gives every pairwise relative effect.")
    extras = {"Heterogeneity": f"Q = {Q:.2f} (df = {dfree}), I² = {I2:.0f}%, τ² = {tau2:.3f}",
              "Reference treatment": ref,
              "Best-ranked (P-score)": f"{best} ({pscore[best]:.2f})"}
    caveats = ["Frequentist NMA assumes a connected, consistent network; the R export (netmeta) also "
               "reports inconsistency (design-by-treatment / net-splitting).",
               "Enter multi-arm studies as their set of pairwise contrasts (exact multi-arm correlation "
               "is handled by netmeta in the R export)."]
    return MA.MetaResult(head, {"I2": I2, "tau2": tau2, "Q": Q, "df": dfree},
                         league_out, interp, figs, extras, caveats), rank_tab, ref


def _network_graph(treats, edge_n, node_n):
    n = len(treats); ang = np.linspace(0, 2*np.pi, n, endpoint=False) + np.pi/2
    pos = {t: (np.cos(a), np.sin(a)) for t, a in zip(treats, ang)}
    fig, ax = plt.subplots(figsize=(6.6, 6.6), dpi=200); ax.axis("off")
    maxe = max(edge_n.values()) if edge_n else 1
    for (a, b), c in edge_n.items():
        (x1, y1), (x2, y2) = pos[a], pos[b]
        ax.plot([x1, x2], [y1, y2], color=STEEL, lw=1.5 + 4.5*c/maxe, alpha=0.55, zorder=1, solid_capstyle="round")
    maxn = max(node_n.values()) if node_n else 1
    for t, (x, y) in pos.items():
        ax.scatter([x], [y], s=500 + 1400*node_n.get(t, 1)/maxn, color=ORANGE, edgecolor="black", lw=1, zorder=3)
        ax.text(x, y, t, ha="center", va="center", fontsize=12, fontweight="bold", color="white", zorder=4)
    ax.set_xlim(-1.4, 1.4); ax.set_ylim(-1.4, 1.4); ax.set_aspect("equal")
    ax.set_title("Network of treatments", fontsize=13, fontweight="bold", color=INK)
    fig.text(0.5, 0.02, "Node size ∝ studies · edge width ∝ direct comparisons", ha="center",
             fontsize=9, color=SUB)
    fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom", fontsize=8, color="#b8c6d6",
             alpha=0.8, style="italic")
    fig.tight_layout(); return fig_to_png(fig, dpi=200)


def _rank_bar(ranking):
    names = [k for k, _ in ranking][::-1]; vals = [v for _, v in ranking][::-1]
    fig, ax = plt.subplots(figsize=(7, 0.6*len(names)+1.6), dpi=200)
    ax.barh(range(len(names)), vals, color=STEEL, edgecolor="black", lw=0.5)
    for i, v in enumerate(vals):
        ax.text(v+0.01, i, f"{v:.2f}", va="center", fontsize=10, color=INK)
    ax.set_yticks(range(len(names))); ax.set_yticklabels(names, fontsize=11)
    ax.set_xlim(0, 1.08); ax.set_xlabel("P-score (probability of being best)", fontsize=11, color=INK)
    ax.set_title("Treatment ranking", fontsize=12.5, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom", fontsize=8, color="#b8c6d6",
             alpha=0.8, style="italic")
    return fig_to_png(fig, dpi=200)


def r_script_nma(df, scale="log", reference=None, model="random"):
    from .r_export import df_to_r, _header
    t1 = _col(df, "Treatment1").astype(str); t2 = _col(df, "Treatment2").astype(str)
    TE = _num(_col(df, "TE")); se = _num(_col(df, "seTE"))
    st = _col(df, "Study").astype(str) if _col(df, "Study") is not None else pd.Series([f"S{i+1}" for i in range(len(df))])
    ok = TE.notna() & se.notna() & (se > 0)
    dat = pd.DataFrame({"studlab": st[ok].values, "treat1": t1[ok].values, "treat2": t2[ok].values,
                        "TE": np.round(TE[ok].values, 6), "seTE": np.round(se[ok].values, 6)})
    sm = {"log": "OR", "raw": "MD"}.get(scale, "OR")
    ref = reference or sorted(set(dat.treat1) | set(dat.treat2))[0]
    common = "TRUE" if model == "fixed" else "FALSE"
    random = "FALSE" if model == "fixed" else "TRUE"
    return "\n".join([
        _header("Network meta-analysis (netmeta)", ["netmeta"]),
        df_to_r(dat, "d"), "",
        f'net <- netmeta(TE, seTE, treat1, treat2, studlab, data = d,',
        f'               sm = "{sm}", reference.group = "{ref}", common = {common}, random = {random})',
        "print(summary(net))",
        "netgraph(net)                 # network geometry",
        "forest(net)                   # relative effects vs reference",
        "netleague(net, digits = 2)    # league table",
        "netrank(net)                  # P-scores / ranking",
        "print(decomp.design(net))     # heterogeneity / inconsistency (design-by-treatment)",
        "# netsplit(net)               # direct vs indirect (node-splitting)",
    ]) + "\n"
