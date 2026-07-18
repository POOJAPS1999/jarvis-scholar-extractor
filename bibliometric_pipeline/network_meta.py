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


def _node_split(t1, t2, TE, se, treats, ref, tau2, model):
    """Side-/node-splitting: for every directly-compared pair, contrast the
    DIRECT estimate against the INDIRECT estimate from the rest of the network."""
    from collections import defaultdict
    tadd = tau2 if model != "fixed" else 0.0
    pairs = defaultdict(list)
    for r, (a, b) in enumerate(zip(t1, t2)):
        pairs[tuple(sorted((a, b)))].append(r)
    out = []
    for (A, B), ridx in pairs.items():
        ridx = np.array(ridx)
        sign = np.array([1.0 if t1[r] == A else -1.0 for r in ridx])
        te_d = TE[ridx]*sign; wd = 1/(se[ridx]**2 + tadd)
        dir_e = float(np.sum(wd*te_d)/np.sum(wd)); dir_se = float(np.sqrt(1/np.sum(wd)))
        mask = np.ones(len(TE), bool); mask[ridx] = False
        t1b, t2b, TEb, seb = t1[mask], t2[mask], TE[mask], se[mask]
        treatsb = sorted(set(t1b) | set(t2b))
        if len(TEb) < 1 or A not in treatsb or B not in treatsb:
            out.append((A, B, dir_e, dir_se, None, None, None, None)); continue
        try:
            refb = ref if ref in treatsb else treatsb[0]
            d2, cov2, basics2, X2, Q2 = _estimate(t1b, t2b, TEb, seb, treatsb, refb, tadd)
            pos2 = {t: i for i, t in enumerate(basics2)}
            ea = 0.0 if A == refb else d2[pos2[A]]
            eb = 0.0 if B == refb else d2[pos2[B]]
            va = 0.0 if A == refb else cov2[pos2[A], pos2[A]]
            vb = 0.0 if B == refb else cov2[pos2[B], pos2[B]]
            cab = 0.0 if (A == refb or B == refb) else cov2[pos2[A], pos2[B]]
            ind_v = va + vb - 2*cab
            if ind_v <= 0:
                out.append((A, B, dir_e, dir_se, None, None, None, None)); continue
            ind_e = float(ea - eb); ind_se = float(np.sqrt(ind_v))
            diff = dir_e - ind_e; dse = np.sqrt(dir_se**2 + ind_se**2)
            p = float(2*(1 - stats.norm.cdf(abs(diff/dse))))
            out.append((A, B, dir_e, dir_se, ind_e, ind_se, diff, p))
        except Exception:
            out.append((A, B, dir_e, dir_se, None, None, None, None))
    return out


def _nodesplit_plot(ns, scale, disp):
    rows = [(A, B, de, dse, ie, ise) for (A, B, de, dse, ie, ise, diff, p) in ns]
    n = len(rows)
    fig, ax = plt.subplots(figsize=(7.8, 1.3 + 0.62*n), dpi=200)
    ys = np.arange(n)[::-1]
    first = True
    for y, (A, B, de, dse, ie, ise) in zip(ys, rows):
        ax.plot([disp(de-Z*dse), disp(de+Z*dse)], [y+0.14, y+0.14], color="black", lw=1, zorder=2)
        ax.scatter([disp(de)], [y+0.14], marker="s", s=72, color=STEEL, edgecolor="black", lw=0.5,
                   zorder=3, label="Direct" if first else None)
        if ie is not None:
            ax.plot([disp(ie-Z*ise), disp(ie+Z*ise)], [y-0.14, y-0.14], color="black", lw=1, zorder=2)
            ax.scatter([disp(ie)], [y-0.14], marker="o", s=72, color=ORANGE, edgecolor="black", lw=0.5,
                       zorder=3, label="Indirect" if first else None)
        first = False
    refx = 1.0 if scale == "log" else 0.0
    ax.axvline(refx, color="black", ls=":", lw=1)
    if scale == "log": ax.set_xscale("log")
    ax.set_yticks(ys); ax.set_yticklabels([f"{A} vs {B}" for (A, B, *_) in rows], fontsize=10)
    ax.set_xlabel("Relative effect", fontsize=11, color=INK)
    ax.set_title("Node-splitting: direct vs indirect", fontsize=12.5, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    ax.legend(loc="best", fontsize=8, frameon=False)
    fig.tight_layout(); return fig_to_png(fig, dpi=200)


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

    # node-splitting (direct vs indirect inconsistency)
    ns = _node_split(t1, t2, TE, se, treats, ref, tau2, model)
    ns_rows = []; worst = None
    for A, B, de, dse, ie, ise, diff, p in ns:
        if ie is None:
            ns_rows.append({"Comparison": f"{A} vs {B}",
                            "Direct": f"{disp(de):.2f} [{disp(de-Z*dse):.2f}, {disp(de+Z*dse):.2f}]",
                            "Indirect": "—", "Difference": "—", "p": "—"})
        else:
            worst = p if worst is None else min(worst, p)
            ns_rows.append({"Comparison": f"{A} vs {B}",
                            "Direct": f"{disp(de):.2f} [{disp(de-Z*dse):.2f}, {disp(de+Z*dse):.2f}]",
                            "Indirect": f"{disp(ie):.2f} [{disp(ie-Z*ise):.2f}, {disp(ie+Z*ise):.2f}]",
                            "Difference": f"{disp(diff):.2f}", "p": f"{p:.3f}"})
    if ns_rows:
        figs["Node-split (direct vs indirect)"] = _nodesplit_plot(ns, scale, disp)
    if worst is not None:
        extras["Inconsistency (node-splitting)"] = (
            f"smallest direct-vs-indirect p = {worst:.3f} across "
            f"{sum(1 for r in ns if r[4] is not None)} closed loops; p < 0.05 flags disagreement.")

    caveats = ["Frequentist NMA assumes a connected network. Consistency is now checked in-app by "
               "node-splitting (direct vs indirect per comparison); the R export (netmeta) adds the "
               "global design-by-treatment interaction test.",
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
