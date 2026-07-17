"""
meta_analysis.py
================
Jarvis Scholar — no-setup meta-analysis. The user fills an Excel template of
study-level data, uploads it, and gets a pooled effect + heterogeneity +
forest/funnel plots + publication-bias tests + leave-one-out/cumulative/
subgroup analyses + an APA paragraph + a metafor R script.

Standard closed-form estimators (implemented directly, no heavy deps):
fixed-effect inverse-variance, DerSimonian-Laird random effects (+ optional
Knapp-Hartung), Cochran Q / I2 / tau2 / H2 / prediction interval, Egger &
Begg tests, Duval-Tweedie trim-and-fill, Rosenthal fail-safe N, leave-one-out,
cumulative, subgroup (Q-between), and moderator meta-regression.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional, Callable

import numpy as np
import pandas as pd
from scipy import stats

from .plot_studio import _col, _num

Z = 1.959963985

# ---------------------------------------------------------------------------
# scale helpers (modelling scale -> display scale)
# ---------------------------------------------------------------------------
def disp(scale: str, x):
    x = np.asarray(x, float)
    if scale == "log":   return np.exp(x)
    if scale == "z":     return np.tanh(x)
    if scale == "logit": return 1/(1+np.exp(-x))
    return x

def null_value(scale: str):
    return 1.0 if scale == "log" else 0.0  # ratios null=1, else 0 (prop has no null line)

def scale_label(scale: str, measure_name: str) -> str:
    return {"log": measure_name + " (log scale)", "z": "Correlation", "logit": "Proportion"}.get(scale, measure_name)


# ---------------------------------------------------------------------------
# effect-size computation  (df -> labels, yi, vi, extra)  on the MODEL scale
# ---------------------------------------------------------------------------
def _labels(df):
    s = _col(df, "Study")
    return [str(x) for x in s] if s is not None else [f"Study {i+1}" for i in range(len(df))]

def _cc(a, b, c, d):
    """0.5 continuity correction for any study with a zero cell (binary)."""
    a, b, c, d = map(lambda v: np.asarray(v, float), (a, b, c, d))
    zero = (a == 0) | (b == 0) | (c == 0) | (d == 0)
    a = a + 0.5*zero; b = b + 0.5*zero; c = c + 0.5*zero; d = d + 0.5*zero
    return a, b, c, d

def es_md(df):
    n1,m1,s1 = _num(_col(df,"N1")),_num(_col(df,"Mean1")),_num(_col(df,"SD1"))
    n2,m2,s2 = _num(_col(df,"N2")),_num(_col(df,"Mean2")),_num(_col(df,"SD2"))
    yi = m1-m2; vi = s1**2/n1 + s2**2/n2
    return _labels(df), yi.values, vi.values, {}

def es_smd(df):
    n1,m1,s1 = _num(_col(df,"N1")),_num(_col(df,"Mean1")),_num(_col(df,"SD1"))
    n2,m2,s2 = _num(_col(df,"N2")),_num(_col(df,"Mean2")),_num(_col(df,"SD2"))
    sp = np.sqrt(((n1-1)*s1**2+(n2-1)*s2**2)/(n1+n2-2))
    d = (m1-m2)/sp
    J = 1 - 3/(4*(n1+n2-2)-1)
    g = J*d; vi = (n1+n2)/(n1*n2) + g**2/(2*(n1+n2))
    return _labels(df), g.values, vi.values, {}

def _binary(df):
    e1,n1,e2,n2 = _num(_col(df,"Events1")),_num(_col(df,"N1")),_num(_col(df,"Events2")),_num(_col(df,"N2"))
    a,b,c,d = _cc(e1, n1-e1, e2, n2-e2)
    return a,b,c,d,e1.values,n1.values,e2.values,n2.values

def es_or(df):
    a,b,c,d,*_ = _binary(df)
    yi = np.log((a*d)/(b*c)); vi = 1/a+1/b+1/c+1/d
    return _labels(df), yi, vi, {}

def es_rr(df):
    a,b,c,d,e1,n1,e2,n2 = _binary(df)
    yi = np.log((a/(a+b))/(c/(c+d))); vi = 1/a - 1/(a+b) + 1/c - 1/(c+d)
    return _labels(df), yi, vi, {"a":a,"n1":n1,"c":c,"n2":n2}

def es_rd(df):
    a,b,c,d,e1,n1,e2,n2 = _binary(df)
    p1=a/(a+b); p2=c/(c+d)
    yi = p1-p2; vi = p1*(1-p1)/(a+b) + p2*(1-p2)/(c+d)
    return _labels(df), yi, vi, {}

def es_irr(df):
    e1,t1,e2,t2 = _num(_col(df,"Events1")),_num(_col(df,"Time1")),_num(_col(df,"Events2")),_num(_col(df,"Time2"))
    e1=e1+0.5*(e1==0); e2=e2+0.5*(e2==0)
    yi = np.log((e1/t1)/(e2/t2)); vi = 1/e1 + 1/e2
    return _labels(df), yi.values, vi.values, {}

def es_cor(df):
    r = _num(_col(df,"r")).clip(-0.999,0.999); n = _num(_col(df,"N"))
    yi = np.arctanh(r); vi = 1/(n-3)
    return _labels(df), yi.values, vi.values, {}

def es_prop(df):
    e = _num(_col(df,"Events")); n = _num(_col(df,"N"))
    e = e.clip(0.5, n-0.5)  # keep logit finite
    p = e/n
    yi = np.log(p/(1-p)); vi = 1/(n*p*(1-p))
    return _labels(df), yi.values, vi.values, {}

def es_prepost(df):
    n=_num(_col(df,"N")); mpre=_num(_col(df,"MeanPre")); spre=_num(_col(df,"SDpre"))
    mpost=_num(_col(df,"MeanPost")); r=_num(_col(df,"r"))
    yi = (mpost-mpre)/spre
    vi = 2*(1-r)/n + yi**2/(2*n)
    return _labels(df), yi.values, vi.values, {}

def es_generic(df):
    eff=_num(_col(df,"Effect")); lo=_num(_col(df,"LowerCI")); hi=_num(_col(df,"UpperCI"))
    vi = ((hi-lo)/(2*Z))**2
    return _labels(df), eff.values, vi.values, {}

def es_hr(df):
    hr=_num(_col(df,"HR")); lo=_num(_col(df,"LowerCI")); hi=_num(_col(df,"UpperCI"))
    yi = np.log(hr); vi = ((np.log(hi)-np.log(lo))/(2*Z))**2
    return _labels(df), yi.values, vi.values, {}


@dataclass
class Measure:
    id: str; name: str; scale: str
    columns: list; example: dict; compute: Callable; escalc: str  # escalc measure code for metafor
    binary: bool = False

MEASURES = {}
def _reg(m): MEASURES[m.id] = m; return m

_reg(Measure("md","Mean difference (MD)","raw",
    [("Study","Study label"),("N1","Group 1 n"),("Mean1","Group 1 mean"),("SD1","Group 1 SD"),
     ("N2","Group 2 n"),("Mean2","Group 2 mean"),("SD2","Group 2 SD")],
    {"Study":["A","B","C","D"],"N1":[30,25,40,35],"Mean1":[5.1,4.8,5.5,5.0],"SD1":[1.1,1.2,1.0,1.3],
     "N2":[30,25,40,35],"Mean2":[4.2,4.5,4.6,4.1],"SD2":[1.0,1.1,1.2,1.2]}, es_md, "MD"))
_reg(Measure("smd","Standardized MD (Hedges g)","raw",
    [("Study","Study label"),("N1","Group 1 n"),("Mean1","Group 1 mean"),("SD1","Group 1 SD"),
     ("N2","Group 2 n"),("Mean2","Group 2 mean"),("SD2","Group 2 SD")],
    {"Study":["A","B","C","D"],"N1":[30,25,40,35],"Mean1":[5.1,4.8,5.5,5.0],"SD1":[1.1,1.2,1.0,1.3],
     "N2":[30,25,40,35],"Mean2":[4.2,4.5,4.6,4.1],"SD2":[1.0,1.1,1.2,1.2]}, es_smd, "SMD"))
_reg(Measure("or","Odds ratio (OR)","log",
    [("Study","Study label"),("Events1","Group 1 events"),("N1","Group 1 n"),
     ("Events2","Group 2 events"),("N2","Group 2 n")],
    {"Study":["A","B","C","D"],"Events1":[12,8,20,15],"N1":[60,50,80,70],
     "Events2":[20,15,30,25],"N2":[60,50,80,70]}, es_or, "OR", binary=True))
_reg(Measure("rr","Risk ratio (RR)","log",
    [("Study","Study label"),("Events1","Group 1 events"),("N1","Group 1 n"),
     ("Events2","Group 2 events"),("N2","Group 2 n")],
    {"Study":["A","B","C","D"],"Events1":[12,8,20,15],"N1":[60,50,80,70],
     "Events2":[20,15,30,25],"N2":[60,50,80,70]}, es_rr, "RR", binary=True))
_reg(Measure("rd","Risk difference (RD)","raw",
    [("Study","Study label"),("Events1","Group 1 events"),("N1","Group 1 n"),
     ("Events2","Group 2 events"),("N2","Group 2 n")],
    {"Study":["A","B","C","D"],"Events1":[12,8,20,15],"N1":[60,50,80,70],
     "Events2":[20,15,30,25],"N2":[60,50,80,70]}, es_rd, "RD", binary=True))
_reg(Measure("irr","Incidence rate ratio (IRR)","log",
    [("Study","Study label"),("Events1","Group 1 events"),("Time1","Group 1 person-time"),
     ("Events2","Group 2 events"),("Time2","Group 2 person-time")],
    {"Study":["A","B","C"],"Events1":[15,20,10],"Time1":[500,600,400],
     "Events2":[25,30,18],"Time2":[520,610,410]}, es_irr, "IRR"))
_reg(Measure("cor","Correlation (r)","z",
    [("Study","Study label"),("r","Pearson correlation"),("N","Sample size")],
    {"Study":["A","B","C","D"],"r":[0.42,0.35,0.51,0.28],"N":[80,120,60,150]}, es_cor, "COR"))
_reg(Measure("prop","Single proportion / prevalence","logit",
    [("Study","Study label"),("Events","Events / cases"),("N","Sample size")],
    {"Study":["A","B","C","D"],"Events":[24,40,15,60],"N":[120,200,90,300]}, es_prop, "PLO"))
_reg(Measure("prepost","Pre-post (paired) SMD","raw",
    [("Study","Study label"),("N","Sample size"),("MeanPre","Pre mean"),("SDpre","Pre SD"),
     ("MeanPost","Post mean"),("r","Pre-post correlation")],
    {"Study":["A","B","C"],"N":[30,40,25],"MeanPre":[5.0,4.8,5.2],"SDpre":[1.1,1.0,1.2],
     "MeanPost":[6.1,5.6,6.0],"r":[0.6,0.5,0.7]}, es_prepost, "SMCC"))
_reg(Measure("hr","Hazard ratio (HR)","log",
    [("Study","Study label"),("HR","Hazard ratio"),("LowerCI","Lower 95% CI"),("UpperCI","Upper 95% CI")],
    {"Study":["A","B","C","D"],"HR":[0.72,0.85,0.65,0.90],"LowerCI":[0.55,0.66,0.48,0.71],
     "UpperCI":[0.94,1.10,0.88,1.14]}, es_hr, "GEN"))
_reg(Measure("generic","Generic (effect + 95% CI)","raw",
    [("Study","Study label"),("Effect","Effect estimate (model scale)"),
     ("LowerCI","Lower 95% CI"),("UpperCI","Upper 95% CI")],
    {"Study":["A","B","C","D"],"Effect":[0.40,0.55,0.30,0.62],"LowerCI":[0.10,0.25,-0.05,0.30],
     "UpperCI":[0.70,0.85,0.65,0.94]}, es_generic, "GEN"))


# ---------------------------------------------------------------------------
# pooling + heterogeneity
# ---------------------------------------------------------------------------
def pool(yi, vi, model="random", hksj=False):
    yi = np.asarray(yi, float); vi = np.asarray(vi, float)
    k = len(yi)
    wf = 1/vi
    ybar_f = np.sum(wf*yi)/np.sum(wf)
    Q = float(np.sum(wf*(yi-ybar_f)**2))
    df = k-1
    C = np.sum(wf) - np.sum(wf**2)/np.sum(wf)
    tau2 = max(0.0, (Q-df)/C) if C > 0 else 0.0
    I2 = max(0.0, (Q-df)/Q)*100 if Q > 0 else 0.0
    H2 = Q/df if df > 0 else np.nan
    if model == "fixed":
        w = wf; tau2_used = 0.0
    else:
        w = 1/(vi+tau2); tau2_used = tau2
    est = float(np.sum(w*yi)/np.sum(w))
    var = 1/np.sum(w); se = float(np.sqrt(var))
    if hksj and model != "fixed" and k > 1:
        se = float(np.sqrt(np.sum(w*(yi-est)**2)/((k-1)*np.sum(w))))
        crit = stats.t.ppf(0.975, k-1); pval = 2*(1-stats.t.cdf(abs(est/se), k-1))
    else:
        crit = Z; pval = 2*(1-stats.norm.cdf(abs(est/se)))
    ci = (est-crit*se, est+crit*se)
    Qp = 1-stats.chi2.cdf(Q, df) if df > 0 else np.nan
    # 95% prediction interval (random effects, k>2)
    if k > 2 and model != "fixed":
        tcrit = stats.t.ppf(0.975, k-2); pise = np.sqrt(tau2+var)
        pi = (est-tcrit*pise, est+tcrit*pise)
    else:
        pi = (np.nan, np.nan)
    return {"k":k,"est":est,"se":se,"ci":ci,"z":est/se,"p":pval,"Q":Q,"df":df,"Qp":Qp,
            "I2":I2,"tau2":tau2,"H2":H2,"pi":pi,"weights":100*w/np.sum(w),"model":model,"hksj":hksj}


def egger(yi, vi):
    sei = np.sqrt(vi); snd = yi/sei; prec = 1/sei
    X = np.column_stack([np.ones_like(prec), prec])
    beta, *_ = np.linalg.lstsq(X, snd, rcond=None)
    resid = snd - X@beta; s2 = np.sum(resid**2)/(len(snd)-2)
    covb = s2*np.linalg.inv(X.T@X); se0 = np.sqrt(covb[0,0])
    t = beta[0]/se0; p = 2*(1-stats.t.cdf(abs(t), len(snd)-2))
    return {"intercept":float(beta[0]),"t":float(t),"p":float(p)}

def begg(yi, vi):
    est = np.sum((1/vi)*yi)/np.sum(1/vi)
    vstar = vi - 1/np.sum(1/vi)
    star = (yi-est)/np.sqrt(np.clip(vstar,1e-12,None))
    tau, p = stats.kendalltau(star, vi)
    return {"tau":float(tau),"p":float(p)}

def failsafe_n(yi, vi, alpha=0.05):
    zi = yi/np.sqrt(vi); k = len(zi)
    zsum = np.sum(zi); 
    if zsum == 0: return 0
    za = stats.norm.ppf(1-alpha/2)
    return int(max(0, round((zsum/za)**2 - k)))

def trim_and_fill(yi, vi, model="random"):
    yi = np.asarray(yi,float); vi = np.asarray(vi,float)
    est = pool(yi, vi, model)["est"]
    y = yi.copy(); v = vi.copy(); L0_prev = -1
    for _ in range(30):
        c = pool(y, v, model)["est"]
        d = yi - c
        order = np.argsort(np.abs(d))
        ranks = np.empty(len(d)); ranks[order] = np.arange(1,len(d)+1)
        signed = np.sign(d)*ranks
        Tn = np.sum(signed[signed>0])
        n = len(yi)
        L0 = int(round((4*Tn - n*(n+1))/(2*n-1)))
        L0 = max(0, min(L0, n-1))
        if L0 == L0_prev: break
        L0_prev = L0
        # impute L0 most extreme positive-side studies mirrored about c
        idx = np.argsort(yi)  # ascending
        take = idx[-L0:] if L0>0 else []
        y = np.concatenate([yi, 2*c - yi[take]]) if L0>0 else yi.copy()
        v = np.concatenate([vi, vi[take]]) if L0>0 else vi.copy()
    filled = pool(y, v, model)
    return {"n_imputed":len(y)-len(yi),"adjusted_est":filled["est"],"adjusted_ci":filled["ci"],
            "y":y,"v":v,"orig_k":len(yi)}

def leave_one_out(yi, vi, model="random", hksj=False):
    rows=[]
    for i in range(len(yi)):
        m = np.ones(len(yi),bool); m[i]=False
        r = pool(yi[m], vi[m], model, hksj)
        rows.append((i, r["est"], r["ci"][0], r["ci"][1], r["I2"]))
    return rows

def cumulative(yi, vi, order, model="random", hksj=False):
    idx = np.argsort(order)
    rows=[]
    for j in range(1, len(idx)+1):
        sel = idx[:j]
        r = pool(yi[sel], vi[sel], model, hksj)
        rows.append((idx[j-1], r["est"], r["ci"][0], r["ci"][1]))
    return rows, idx

def subgroups(yi, vi, groups, model="random", hksj=False):
    res={}; Qw=0.0
    for g in pd.unique(groups):
        m = groups==g
        r = pool(yi[m], vi[m], model, hksj); res[str(g)] = r; Qw += r["Q"]
    total = pool(yi, vi, model, hksj)
    Qbet = max(0.0, total["Q"] - Qw); dfb = len(res)-1
    pbet = 1-stats.chi2.cdf(Qbet, dfb) if dfb>0 else np.nan
    return res, {"Q_between":Qbet,"df":dfb,"p":pbet}

def metareg(yi, vi, x, model="random"):
    tau2 = pool(yi, vi, model)["tau2"] if model!="fixed" else 0.0
    w = 1/(vi+tau2); X = np.column_stack([np.ones_like(x), x])
    W = np.diag(w)
    XtWX = X.T@W@X; beta = np.linalg.solve(XtWX, X.T@W@yi)
    cov = np.linalg.inv(XtWX); se = np.sqrt(np.diag(cov))
    t = beta/se; p = 2*(1-stats.norm.cdf(np.abs(t)))
    return {"beta":beta,"se":se,"p":p,"tau2":tau2}


# ---------------------------------------------------------------------------
# plots
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from .plot_studio import fig_to_png

BLUE, INK, SUB, RED, GREY = "#2563eb", "#12283b", "#41566b", "#d8572a", "#c3d0dd"

def _wm(fig):
    fig.text(0.995, 0.005, "Jarvis Scholar", ha="right", va="bottom", fontsize=8,
             color="#b8c6d6", alpha=0.8, style="italic")

def forest_plot(labels, yi, vi, res, scale, mname, title="", pooled_label="Pooled"):
    k = len(yi); ylev = np.arange(k)[::-1].astype(float)
    sei = np.sqrt(vi)
    ed, lo, hi = disp(scale, yi), disp(scale, yi-Z*sei), disp(scale, yi+Z*sei)
    w = res.get("weights")
    if w is None or len(w) != k:
        w = 100*(1/vi)/np.sum(1/vi)
    sizes = 40 + (w/w.max())*300 if w.max() > 0 else 60
    fig, ax = plt.subplots(figsize=(8.2, 0.52*k + 2.6), dpi=200)
    logx = scale == "log"
    ax.hlines(ylev, lo, hi, color=SUB, lw=1.5, zorder=2)
    ax.scatter(ed, ylev, s=sizes, marker="s", color=BLUE, zorder=3, edgecolor="white")
    if scale in ("log", "raw"):
        ax.axvline(1.0 if scale == "log" else 0.0, color=RED, ls="--", lw=1)
    pe, pl, ph = disp(scale, res["est"]), disp(scale, res["ci"][0]), disp(scale, res["ci"][1])
    yd = -1.5
    ax.add_patch(Polygon([(pl, yd), (pe, yd+0.32), (ph, yd), (pe, yd-0.32)], closed=True,
                         facecolor=BLUE, edgecolor=INK, zorder=4))
    ax.set_yticks(list(ylev) + [yd]); ax.set_yticklabels(list(labels) + [pooled_label], fontsize=9)
    if logx:
        ax.set_xscale("log")
    ax.set_xlabel(scale_label(scale, mname), fontsize=10, color=SUB)
    ax.set_ylim(yd-1, k-0.3)
    het = (f"Heterogeneity: I² = {res['I2']:.0f}%, τ² = {res['tau2']:.3f}, "
           f"Q({res['df']}) = {res['Q']:.1f}, p = {res['Qp']:.3f}")
    ax.text(0.0, 1.02, title or f"{pooled_label} (k = {k})", transform=ax.transAxes,
            fontsize=12, fontweight="bold", color=INK)
    ax.text(0.0, -0.14/(0.52*k+2.6)*10 - 0.02, het, transform=ax.transAxes, fontsize=8.5, color=SUB)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(left=False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def funnel_plot(yi, vi, res, scale, mname):
    sei = np.sqrt(vi); est = res["est"]
    fig, ax = plt.subplots(figsize=(7, 5), dpi=200)
    se_max = sei.max()*1.05
    ys = np.linspace(0, se_max, 50)
    ax.plot(est + Z*ys, ys, color=GREY, ls="--"); ax.plot(est - Z*ys, ys, color=GREY, ls="--")
    ax.axvline(est, color=RED, lw=1.3)
    ax.scatter(yi, sei, s=45, color=BLUE, alpha=0.8, edgecolor="white", zorder=3)
    ax.invert_yaxis(); ax.set_xlabel(scale_label(scale, mname), fontsize=10, color=SUB)
    ax.set_ylabel("Standard error", fontsize=10, color=SUB)
    ax.set_title("Funnel plot", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def radial_plot(yi, vi):
    sei = np.sqrt(vi); x = 1/sei; y = yi/sei
    b = np.sum(x*y)/np.sum(x*x)
    fig, ax = plt.subplots(figsize=(7, 5), dpi=200)
    ax.scatter(x, y, s=45, color=BLUE, alpha=0.8, edgecolor="white", zorder=3)
    xs = np.linspace(0, x.max()*1.05, 20)
    ax.plot(xs, b*xs, color=RED); ax.plot(xs, b*xs+2, color=GREY, ls="--"); ax.plot(xs, b*xs-2, color=GREY, ls="--")
    ax.set_xlabel("Precision (1/SE)", fontsize=10, color=SUB); ax.set_ylabel("Std. effect (z)", fontsize=10, color=SUB)
    ax.set_title("Radial (Galbraith) plot", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def baujat_plot(labels, yi, vi):
    wf = 1/vi; ybar = np.sum(wf*yi)/np.sum(wf)
    contrib = wf*(yi-ybar)**2
    full = pool(yi, vi, "fixed"); infl = []
    for i in range(len(yi)):
        m = np.ones(len(yi), bool); m[i] = False
        infl.append((full["est"]-pool(yi[m], vi[m], "fixed")["est"])**2/full["se"]**2)
    infl = np.array(infl)
    fig, ax = plt.subplots(figsize=(7, 5), dpi=200)
    ax.scatter(contrib, infl, s=45, color=BLUE, alpha=0.85, edgecolor="white")
    for xi, yi2, lab in zip(contrib, infl, labels):
        ax.annotate(str(lab), (xi, yi2), fontsize=8, color=SUB, xytext=(3, 2), textcoords="offset points")
    ax.set_xlabel("Contribution to heterogeneity", fontsize=10, color=SUB)
    ax.set_ylabel("Influence on pooled result", fontsize=10, color=SUB)
    ax.set_title("Baujat plot", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def labbe_plot(df):
    a, b, c, d, e1, n1, e2, n2 = _binary(df)
    xt = e2/n2; yt = e1/n1; sizes = 20 + (n1+n2)/(n1+n2).max()*260
    fig, ax = plt.subplots(figsize=(6, 6), dpi=200)
    ax.plot([0, 1], [0, 1], color=GREY, ls="--")
    ax.scatter(xt, yt, s=sizes, color=BLUE, alpha=0.7, edgecolor="white")
    ax.set_xlabel("Control group event rate", fontsize=10, color=SUB)
    ax.set_ylabel("Treatment group event rate", fontsize=10, color=SUB)
    ax.set_title("L'Abbé plot", fontsize=12, fontweight="bold", color=INK); ax.set_aspect("equal")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def _loo_forest(labels, rows, res, scale):
    k = len(rows); ylev = np.arange(k)[::-1].astype(float)
    ed = disp(scale, np.array([r[1] for r in rows]))
    lo = disp(scale, np.array([r[2] for r in rows])); hi = disp(scale, np.array([r[3] for r in rows]))
    fig, ax = plt.subplots(figsize=(8, 0.5*k+2), dpi=200)
    ax.hlines(ylev, lo, hi, color=SUB, lw=1.5); ax.scatter(ed, ylev, s=55, color=BLUE, zorder=3, edgecolor="white")
    if scale in ("log", "raw"): ax.axvline(1.0 if scale == "log" else 0.0, color=RED, ls="--", lw=1)
    if scale == "log": ax.set_xscale("log")
    ax.axvline(disp(scale, res["est"]), color="#1d9e75", ls=":", lw=1.2)
    ax.set_yticks(ylev); ax.set_yticklabels([f"omitting {labels[r[0]]}" for r in rows], fontsize=9)
    ax.set_title("Leave-one-out analysis", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.tick_params(left=False); fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def _cumulative_forest(labels, rows, order_idx, scale):
    k = len(rows); ylev = np.arange(k)[::-1].astype(float)
    ed = disp(scale, np.array([r[1] for r in rows]))
    lo = disp(scale, np.array([r[2] for r in rows])); hi = disp(scale, np.array([r[3] for r in rows]))
    fig, ax = plt.subplots(figsize=(8, 0.5*k+2), dpi=200)
    ax.hlines(ylev, lo, hi, color=SUB, lw=1.5); ax.scatter(ed, ylev, s=55, color=BLUE, zorder=3, edgecolor="white")
    if scale in ("log", "raw"): ax.axvline(1.0 if scale == "log" else 0.0, color=RED, ls="--", lw=1)
    if scale == "log": ax.set_xscale("log")
    ax.set_yticks(ylev); ax.set_yticklabels([f"+ {labels[i]}" for i in order_idx], fontsize=9)
    ax.set_title("Cumulative meta-analysis", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right", "left"): ax.spines[s].set_visible(False)
    ax.tick_params(left=False); fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def bubble_plot(x, yi, vi, reg, scale, xlabel):
    sizes = 30 + (1/vi)/(1/vi).max()*300
    fig, ax = plt.subplots(figsize=(7.5, 5), dpi=200)
    ax.scatter(x, disp(scale, yi), s=sizes, color=BLUE, alpha=0.55, edgecolor=SUB)
    xs = np.linspace(x.min(), x.max(), 50)
    ax.plot(xs, disp(scale, reg["beta"][0] + reg["beta"][1]*xs), color=RED, lw=2)
    ax.set_xlabel(xlabel, fontsize=10, color=SUB); ax.set_ylabel(scale_label(scale, "Effect"), fontsize=10, color=SUB)
    ax.set_title("Meta-regression", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------
@dataclass
class MetaResult:
    headline: str
    pooled: dict
    table: pd.DataFrame
    interpretation: str
    figures: dict = field(default_factory=dict)   # name -> png bytes
    extras: dict = field(default_factory=dict)     # egger/begg/etc as text lines
    caveats: List[str] = field(default_factory=list)

    def report_text(self) -> str:
        lines = [self.headline, "", "Interpretation:", self.interpretation, ""]
        if not self.table.empty:
            lines += [self.table.to_string(index=False), ""]
        for k, v in self.extras.items():
            lines.append(f"{k}: {v}")
        lines += ["", "Generated with Jarvis Scholar — verify against your protocol."]
        return "\n".join(lines)


def _fmt(scale, x):
    return f"{disp(scale, x):.3f}"

def run(measure_id, df, model="random", hksj=False):
    meas = MEASURES[measure_id]
    labels, yi, vi, extra = meas.compute(df)
    labels = list(labels); yi = np.asarray(yi, float); vi = np.asarray(vi, float)
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0)
    labels = [l for l, o in zip(labels, ok) if o]; yi, vi = yi[ok], vi[ok]
    df = df.loc[ok].reset_index(drop=True)
    r = pool(yi, vi, model, hksj)
    sc = meas.scale
    est_s, lo_s, hi_s = _fmt(sc, r["est"]), _fmt(sc, r["ci"][0]), _fmt(sc, r["ci"][1])
    mlab = "random-effects (DL" + (", HKSJ" if hksj else "") + ")" if model != "fixed" else "fixed-effect"
    head = f"{meas.name}: pooled {est_s} [{lo_s}, {hi_s}], {mlab}, k = {r['k']}, I² = {r['I2']:.0f}%"
    # per-study table
    sei = np.sqrt(vi)
    tab = pd.DataFrame({"Study": labels,
                        "Effect": [f"{disp(sc,y):.3f}" for y in yi],
                        "95% CI": [f"[{disp(sc,y-Z*s):.3f}, {disp(sc,y+Z*s):.3f}]" for y, s in zip(yi, sei)],
                        "Weight %": [f"{w:.1f}" for w in r["weights"]]})
    pi = ""
    if np.isfinite(r["pi"][0]):
        pi = f" 95% prediction interval [{disp(sc, r['pi'][0]):.3f}, {disp(sc, r['pi'][1]):.3f}]."
    interp = (f"The pooled {meas.name.split('(')[0].strip().lower()} is {est_s} "
              f"(95% CI {lo_s} to {hi_s}, p = {r['p']:.3f}). Heterogeneity: I² = {r['I2']:.0f}% "
              f"(τ² = {r['tau2']:.3f}, Q p = {r['Qp']:.3f}).{pi}")

    figs = {"Forest plot": forest_plot(labels, yi, vi, r, sc, meas.name, pooled_label="Pooled ("+("RE" if model!="fixed" else "FE")+")")}
    if r["k"] >= 3:
        figs["Funnel plot"] = funnel_plot(yi, vi, r, sc, meas.name)
        figs["Radial plot"] = radial_plot(yi, vi)
        figs["Baujat plot"] = baujat_plot(labels, yi, vi)
    if meas.binary:
        figs["L'Abbé plot"] = labbe_plot(df)

    extras = {}
    caveats = []
    if r["k"] >= 3:
        eg = egger(yi, vi); bg = begg(yi, vi); tf = trim_and_fill(yi, vi, model); fsn = failsafe_n(yi, vi)
        extras["Egger's test"] = f"intercept = {eg['intercept']:.2f}, p = {eg['p']:.3f}"
        extras["Begg's test"] = f"Kendall τ = {bg['tau']:.2f}, p = {bg['p']:.3f}"
        extras["Trim-and-fill"] = (f"{tf['n_imputed']} studies imputed; adjusted {disp(sc,tf['adjusted_est']):.3f} "
                                   f"[{disp(sc,tf['adjusted_ci'][0]):.3f}, {disp(sc,tf['adjusted_ci'][1]):.3f}]")
        extras["Fail-safe N"] = str(fsn)
        loo = leave_one_out(yi, vi, model, hksj); figs["Leave-one-out"] = _loo_forest(labels, loo, r, sc)
    if r["k"] < 10:
        caveats.append("With few studies, heterogeneity and bias tests have low power — interpret cautiously.")

    # subgroup
    g = _col(df, "Subgroup")
    if g is not None and g.notna().any() and g.nunique() >= 2:
        sub, qb = subgroups(yi, vi, g.astype(str).values, model, hksj)
        rows = [{"Subgroup": k2, "Pooled": _fmt(sc, v["est"]),
                 "95% CI": f"[{_fmt(sc,v['ci'][0])}, {_fmt(sc,v['ci'][1])}]",
                 "k": v["k"], "I²": f"{v['I2']:.0f}%"} for k2, v in sub.items()]
        extras["Subgroup difference"] = f"Q_between({qb['df']}) = {qb['Q_between']:.2f}, p = {qb['p']:.3f}"
        figs["Subgroup forest"] = forest_plot(
            [f"{k2} (k={v['k']})" for k2, v in sub.items()],
            np.array([v["est"] for v in sub.values()]),
            np.array([v["se"]**2 for v in sub.values()]), r, sc, meas.name, pooled_label="Overall")

    # cumulative (needs Year/Order)
    oc = _col(df, "Year") if _col(df, "Year") is not None else _col(df, "Order")
    if oc is not None and _num(oc).notna().all():
        crows, oidx = cumulative(yi, vi, _num(oc).values, model, hksj)
        figs["Cumulative"] = _cumulative_forest(labels, crows, oidx, sc)

    # meta-regression (needs Moderator)
    mod = _col(df, "Moderator")
    if mod is not None and _num(mod).notna().all() and r["k"] >= 4:
        reg = metareg(yi, vi, _num(mod).values, model)
        extras["Meta-regression slope"] = f"β = {reg['beta'][1]:.3f} (SE {reg['se'][1]:.3f}, p = {reg['p'][1]:.3f})"
        figs["Meta-regression"] = bubble_plot(_num(mod).values, yi, vi, reg, sc, "Moderator")

    return MetaResult(head, r, tab, interp, figs, extras, caveats)


# ---------------------------------------------------------------------------
# metafor R export  (embed yi/vi -> rma; authoritative + matches our numbers)
# ---------------------------------------------------------------------------
def r_script(measure_id, df, model="random", hksj=False):
    from .r_export import df_to_r, _header
    meas = MEASURES[measure_id]
    labels, yi, vi, extra = meas.compute(df)
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0)
    dat = pd.DataFrame({"study": [str(l) for l, o in zip(labels, ok) if o],
                        "yi": np.round(np.asarray(yi)[ok], 6), "vi": np.round(np.asarray(vi)[ok], 8)})
    sub = _col(df, "Subgroup"); mod = _col(df, "Moderator"); yr = _col(df, "Year")
    if sub is not None: dat["subgroup"] = [str(x) for x, o in zip(sub, ok) if o]
    if mod is not None: dat["moderator"] = [x for x, o in zip(_num(mod), ok) if o]
    if yr is not None: dat["year"] = [x for x, o in zip(_num(yr), ok) if o]
    atr = {"log": "exp", "z": "transf.ztor", "logit": "transf.ilogit"}.get(meas.scale, "")
    atr_arg = f", atransf={atr}" if atr else ""
    method = "FE" if model == "fixed" else "DL"
    test = ', test="knha"' if (hksj and model != "fixed") else ""
    lines = [_header(f"Meta-analysis — {meas.name}", ["metafor"]), df_to_r(dat, "dat"), "",
        f'res <- rma(yi, vi, data = dat, method = "{method}"{test})',
        "print(summary(res))",
        "confint(res)   # tau^2, I^2 with CIs",
        f'forest(res, slab = dat$study{atr_arg}, header = TRUE)',
        "funnel(res)",
        'regtest(res)          # Egger test',
        'ranktest(res)         # Begg test',
        "tf <- trimfill(res); print(tf); funnel(tf)",
        "print(leave1out(res))",
        "baujat(res)",
        "radial(res)"]
    if meas.binary:
        lines.append('# labbe(res)  # needs an rma from escalc(ai,bi,ci,di) — see metafor::labbe')
    if sub is not None:
        lines.append('rma(yi, vi, mods = ~ factor(subgroup), data = dat, method = "%s")  # subgroup / moderator' % method)
    if mod is not None:
        lines.append('reg <- rma(yi, vi, mods = ~ moderator, data = dat, method = "%s"); print(reg); regplot(reg)' % method)
    if yr is not None:
        lines.append("print(cumul(rma(yi, vi, data = dat[order(dat$year), ], method = \"%s\")))" % method)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Excel template + validation
# ---------------------------------------------------------------------------
def template_bytes(meas: Measure) -> bytes:
    data = pd.DataFrame(meas.example)
    rows = [(c, "Required", h) for c, h in meas.columns]
    rows += [("Subgroup", "Optional", "Add to run subgroup analysis + subgroup forest"),
             ("Year", "Optional", "Add (numeric) to run a cumulative meta-analysis"),
             ("Moderator", "Optional", "Add (numeric) to run meta-regression + bubble plot")]
    info = pd.DataFrame(rows, columns=["Column", "Required", "What to enter"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        data.to_excel(xl, sheet_name="Data", index=False)
        info.to_excel(xl, sheet_name="Instructions", index=False)
    return buf.getvalue()


def validate(meas: Measure, df: pd.DataFrame) -> "list[str]":
    have = {c.strip().lower() for c in df.columns}
    miss = [c for c, _ in meas.columns if c.strip().lower() not in have]
    problems = []
    if miss:
        problems.append("Missing required columns: " + ", ".join(miss))
    if df.dropna(how="all").empty:
        problems.append("The Data sheet is empty.")
    if len(df.dropna(how="all")) < 2:
        problems.append("Meta-analysis needs at least 2 studies.")
    return problems
