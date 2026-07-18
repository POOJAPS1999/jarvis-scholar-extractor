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
def _tau2(yi, vi, method="DL"):
    """Between-study variance by DerSimonian–Laird, Paule–Mandel, or REML."""
    yi = np.asarray(yi, float); vi = np.asarray(vi, float); k = len(yi)
    wf = 1/vi; ybar = np.sum(wf*yi)/np.sum(wf)
    Q = float(np.sum(wf*(yi-ybar)**2)); df = k-1
    C = np.sum(wf) - np.sum(wf**2)/np.sum(wf)
    dl = max(0.0, (Q-df)/C) if C > 0 else 0.0
    if method == "DL" or k < 3:
        return dl
    if method == "PM":  # Paule–Mandel: weighted Q(tau2) == df
        def Qt(t):
            w = 1/(vi+t); mu = np.sum(w*yi)/np.sum(w); return float(np.sum(w*(yi-mu)**2)) - df
        if Qt(0.0) <= 0: return 0.0
        lo, hi = 0.0, max(dl*4, 1.0)
        while Qt(hi) > 0 and hi < 1e7: hi *= 2
        for _ in range(200):
            mid = 0.5*(lo+hi)
            if Qt(mid) > 0: lo = mid
            else: hi = mid
        return 0.5*(lo+hi)
    if method == "REML":  # Viechtbauer fixed-point iteration
        t = dl
        for _ in range(400):
            w = 1/(vi+t); s1 = np.sum(w); mu = np.sum(w*yi)/s1
            tn = max(0.0, float(np.sum(w**2*((yi-mu)**2 - vi))/np.sum(w**2) + 1.0/s1))
            if abs(tn-t) < 1e-9: t = tn; break
            t = tn
        return t
    return dl


def pool(yi, vi, model="random", hksj=False, tau_method="DL"):
    yi = np.asarray(yi, float); vi = np.asarray(vi, float)
    k = len(yi)
    wf = 1/vi
    ybar_f = np.sum(wf*yi)/np.sum(wf)
    Q = float(np.sum(wf*(yi-ybar_f)**2))
    df = k-1
    tau2 = _tau2(yi, vi, tau_method)
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

def subgroups(yi, vi, groups, model="random", hksj=False, tau_method="DL"):
    res={}; Qw=0.0
    for g in pd.unique(groups):
        m = groups==g
        r = pool(yi[m], vi[m], model, hksj, tau_method); res[str(g)] = r; Qw += r["Q"]
    total = pool(yi, vi, model, hksj, tau_method)
    Qbet = max(0.0, total["Q"] - Qw); dfb = len(res)-1
    pbet = 1-stats.chi2.cdf(Qbet, dfb) if dfb>0 else np.nan
    return res, {"Q_between":Qbet,"df":dfb,"p":pbet}

def metareg(yi, vi, X, model="random", tau_method="DL"):
    """Meta-regression on one or more moderators (X: n or n×p). DL residual
    heterogeneity, per-coefficient tests, omnibus QM test, and R²_analog."""
    yi = np.asarray(yi, float); vi = np.asarray(vi, float); X = np.asarray(X, float)
    if X.ndim == 1: X = X[:, None]
    if X.shape[0] != len(yi): X = X.T
    k, p = len(yi), X.shape[1]
    Xd = np.column_stack([np.ones(k), X])
    wf = 1/vi
    XtWX = Xd.T @ (wf[:, None]*Xd); XtWXi = np.linalg.inv(XtWX)
    P = np.diag(wf) - (wf[:, None]*Xd) @ XtWXi @ (Xd.T * wf)
    QE = float(yi @ P @ yi)
    tr = np.sum(wf) - np.trace(XtWXi @ (Xd.T @ ((wf**2)[:, None]*Xd)))
    tau2_r = max(0.0, (QE-(k-p-1))/tr) if (model != "fixed" and tr > 0) else 0.0
    w = 1/(vi+tau2_r)
    XtWX2 = Xd.T @ (w[:, None]*Xd); cov = np.linalg.inv(XtWX2)
    beta = cov @ (Xd.T @ (w*yi)); se = np.sqrt(np.diag(cov)); t = beta/se
    pv = 2*(1-stats.norm.cdf(np.abs(t)))
    bm, cm = beta[1:], cov[1:, 1:]
    QM = float(bm @ np.linalg.solve(cm, bm)); QMp = 1-stats.chi2.cdf(QM, p)
    tau0 = _tau2(yi, vi, tau_method)
    R2 = max(0.0, (tau0-tau2_r)/tau0)*100 if tau0 > 0 else 0.0
    return {"beta": beta, "se": se, "p": pv, "tau2_resid": tau2_r, "QM": QM, "QMp": QMp,
            "R2": R2, "p_mod": p}


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
    """Contour-enhanced funnel: significance contours around the null (grey bands)
    plus the pooled 95% pseudo-CI funnel — helps tell publication bias from
    heterogeneity (matches metafor::funnel with shaded contours)."""
    from matplotlib.patches import Patch
    sei = np.sqrt(vi); est = res["est"]; null = 0.0
    fig, ax = plt.subplots(figsize=(7.2, 5.4), dpi=200)
    ys = np.linspace(1e-6, sei.max()*1.15, 90)
    def X(z):
        return disp(scale, null - z*ys), disp(scale, null + z*ys)
    l1, r1 = X(1.645); l2, r2 = X(1.96); l3, r3 = X(2.576)
    for a, b in [(l2, l1), (r1, r2)]:  # 0.05 < p < 0.10
        ax.fill_betweenx(ys, a, b, color="#c9d3dd", zorder=0)
    for a, b in [(l3, l2), (r2, r3)]:  # 0.01 < p < 0.05
        ax.fill_betweenx(ys, a, b, color="#e6ecf2", zorder=0)
    ax.axvline(disp(scale, null), color=GREY, ls="--", lw=1, zorder=1)          # null
    ax.axvline(disp(scale, est), color=SUB, lw=1.3, zorder=1)                   # pooled
    ax.plot(disp(scale, est-Z*ys), ys, color=SUB, ls=":", lw=1, zorder=1)
    ax.plot(disp(scale, est+Z*ys), ys, color=SUB, ls=":", lw=1, zorder=1)
    ax.scatter(disp(scale, yi), sei, s=62, facecolor=STEEL, edgecolor="black", lw=0.6, zorder=3)
    if scale == "log": ax.set_xscale("log")
    ax.invert_yaxis()
    ax.set_xlabel(_short(scale, mname), fontsize=11, color=INK)
    ax.set_ylabel("Standard error", fontsize=11, color=INK)
    ax.set_title("Contour-enhanced funnel plot", fontsize=12.5, fontweight="bold", color=INK)
    ax.legend(handles=[Patch(facecolor="#c9d3dd", label="0.05 < p < 0.10"),
                       Patch(facecolor="#e6ecf2", label="0.01 < p < 0.05")],
              loc="lower right", fontsize=8, frameon=False)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def radial_plot(yi, vi):
    sei = np.sqrt(vi); x = 1/sei; y = yi/sei
    b = np.sum(x*y)/np.sum(x*x)
    fig, ax = plt.subplots(figsize=(7, 5.3), dpi=200)
    xs = np.linspace(0, x.max()*1.08, 40)
    ax.fill_between(xs, b*xs-1.96, b*xs+1.96, color="#eaf2fb", zorder=0)
    ax.plot(xs, b*xs, color=RED, lw=1.6); ax.plot(xs, b*xs+1.96, color=GREY, ls="--", lw=1)
    ax.plot(xs, b*xs-1.96, color=GREY, ls="--", lw=1)
    ax.scatter(x, y, s=60, facecolor=STEEL, edgecolor="black", lw=0.6, zorder=3)
    ax.set_xlabel("Precision (1 / SE)", fontsize=11, color=INK)
    ax.set_ylabel("Standardized effect (z-score)", fontsize=11, color=INK)
    ax.set_title("Radial (Galbraith) plot", fontsize=12.5, fontweight="bold", color=INK)
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
    fig, ax = plt.subplots(figsize=(7, 5.3), dpi=200)
    ax.scatter(contrib, infl, s=62, facecolor=STEEL, edgecolor="black", lw=0.6, zorder=3)
    for xi, yi2, lab in zip(contrib, infl, labels):
        ax.annotate(str(lab), (xi, yi2), fontsize=8.5, color=INK, xytext=(4, 3), textcoords="offset points")
    ax.set_xlabel("Contribution to overall heterogeneity", fontsize=11, color=INK)
    ax.set_ylabel("Influence on pooled result", fontsize=11, color=INK)
    ax.set_title("Baujat plot", fontsize=12.5, fontweight="bold", color=INK)
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

_TAU_LABEL = {"DL": "DL", "REML": "REML", "PM": "Paule–Mandel"}

def _2x2(df):
    a = _num(_col(df, "Events1")).values.astype(float); n1 = _num(_col(df, "N1")).values.astype(float)
    c = _num(_col(df, "Events2")).values.astype(float); n2 = _num(_col(df, "N2")).values.astype(float)
    return a, n1 - a, c, n2 - c   # a, b, c, d

def mh_pool(df, measure):
    """Mantel–Haenszel pooled OR/RR (log scale) with Robins–Breslow–Greenland SE."""
    a, b, c, d = _2x2(df); n = a + b + c + d
    if measure == "rr":
        R = np.sum(a*(c+d)/n); S = np.sum(c*(a+b)/n); est = np.log(R/S)
        var = np.sum(((a+b)*(c+d)*(a+c) - a*c*n)/n**2)/(R*S)
    else:  # OR
        R = np.sum(a*d/n); S = np.sum(b*c/n); est = np.log(R/S)
        PR = (a+d)/n; PS = (b+c)/n
        var = (np.sum(PR*a*d/n)/(2*R**2)
               + np.sum(PR*b*c/n + PS*a*d/n)/(2*R*S)
               + np.sum(PS*b*c/n)/(2*S**2))
    return float(est), float(np.sqrt(var))

def peto_pool(df):
    """Peto one-step pooled log OR (fixed-effect, best for rare events / balanced arms)."""
    a, b, c, d = _2x2(df); n = a + b + c + d
    E = (a+b)*(a+c)/n
    V = (a+b)*(c+d)*(a+c)*(b+d)/(n**2*(n-1))
    est = np.sum(a - E)/np.sum(V); var = 1/np.sum(V)
    return float(est), float(np.sqrt(var))

def run(measure_id, df, model="random", hksj=False, tau_method="DL"):
    meas = MEASURES[measure_id]
    labels, yi, vi, extra = meas.compute(df)
    labels = list(labels); yi = np.asarray(yi, float); vi = np.asarray(vi, float)
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0)
    labels = [l for l, o in zip(labels, ok) if o]; yi, vi = yi[ok], vi[ok]
    df = df.loc[ok].reset_index(drop=True)
    binary_method = model if model in ("mh", "peto") else None
    pool_model = "fixed" if binary_method else model
    r = pool(yi, vi, pool_model, hksj, tau_method)
    if binary_method:
        est, se = (peto_pool(df) if binary_method == "peto" else mh_pool(df, meas.id))
        r["est"], r["se"], r["ci"] = est, se, (est - Z*se, est + Z*se)
        r["p"] = 2*(1 - stats.norm.cdf(abs(est/se))); r["pi"] = (np.nan, np.nan)
    sc = meas.scale
    est_s, lo_s, hi_s = _fmt(sc, r["est"]), _fmt(sc, r["ci"][0]), _fmt(sc, r["ci"][1])
    if binary_method:
        mlab = ("Peto (fixed-effect)" if binary_method == "peto" else "Mantel–Haenszel (fixed-effect)")
    else:
        mlab = ("random-effects (" + _TAU_LABEL.get(tau_method, "DL") + (", HKSJ" if hksj else "") + ")"
                if model != "fixed" else "fixed-effect")
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

    _plab = "Peto" if binary_method == "peto" else ("MH" if binary_method == "mh"
             else ("RE" if model != "fixed" else "FE"))
    figs = {"Forest plot": forest_plot(labels, yi, vi, r, sc, meas.name, pooled_label="Pooled ("+_plab+")")}
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
        sub, qb = subgroups(yi, vi, g.astype(str).values, model, hksj, tau_method)
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

    # meta-regression (needs Moderator, Moderator1, Moderator2, …)
    mod_names = [c for c in df.columns if _re.fullmatch(r"(?i)moderator\d*", str(c).strip())]
    Xcols, used = [], []
    for c in mod_names:
        v = _num(df[c])
        if v.notna().all():
            Xcols.append(v.values); used.append(str(c))
    if used and r["k"] >= len(used) + 3:
        reg = metareg(yi, vi, np.column_stack(Xcols), model, tau_method)
        for j, c in enumerate(used):
            extras[f"Meta-regression: {c}"] = (f"β = {reg['beta'][j+1]:.3f} "
                                               f"(SE {reg['se'][j+1]:.3f}, p = {reg['p'][j+1]:.3f})")
        if len(used) > 1:
            extras["Meta-regression (omnibus)"] = (f"QM({reg['p_mod']}) = {reg['QM']:.2f}, "
                                                   f"p = {reg['QMp']:.3f}; R² = {reg['R2']:.0f}%, "
                                                   f"residual τ² = {reg['tau2_resid']:.3f}")
            figs["Meta-regression"] = _coef_plot(reg, used)
        else:
            extras["Meta-regression: R²"] = (f"{reg['R2']:.0f}% of between-study variance explained; "
                                             f"residual τ² = {reg['tau2_resid']:.3f}")
            figs["Meta-regression"] = bubble_plot(Xcols[0], yi, vi, reg, sc, used[0])

    return MetaResult(head, r, tab, interp, figs, extras, caveats)


def _coef_plot(reg, names):
    """Coefficient (forest-style) plot for multi-moderator meta-regression."""
    b = reg["beta"][1:]; se = reg["se"][1:]
    lo, hi = b - Z*se, b + Z*se
    n = len(names)
    fig, ax = plt.subplots(figsize=(7.4, 1.1 + 0.5*n), dpi=200)
    ys = np.arange(n)[::-1]
    for y, e, l, h in zip(ys, b, lo, hi):
        ax.plot([l, h], [y, y], color="black", lw=1.2, zorder=2)
        ax.scatter([e], [y], marker="s", s=90, color=STEEL, edgecolor="black", lw=0.6, zorder=3)
    ax.axvline(0, color="black", ls=":", lw=1)
    ax.set_yticks(ys); ax.set_yticklabels(names, fontsize=10)
    ax.set_xlabel("Regression coefficient (β, effect scale)", fontsize=11, color=INK)
    ax.set_title("Meta-regression coefficients", fontsize=12.5, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)


# ---------------------------------------------------------------------------
# metafor R export  (embed yi/vi -> rma; authoritative + matches our numbers)
# ---------------------------------------------------------------------------
def r_script(measure_id, df, model="random", hksj=False, tau_method="DL"):
    from .r_export import df_to_r, _header
    meas = MEASURES[measure_id]
    if model in ("mh", "peto") and meas.binary:
        a, b, c, d = _2x2(df)
        okm = np.isfinite(a) & np.isfinite(b) & np.isfinite(c) & np.isfinite(d)
        lb = _labels(df)
        dat = pd.DataFrame({"study": [str(l) for l, o in zip(lb, okm) if o],
                            "ai": a[okm].astype(int), "bi": b[okm].astype(int),
                            "ci": c[okm].astype(int), "di": d[okm].astype(int)})
        if model == "peto":
            call = 'res <- rma.peto(ai=ai, bi=bi, ci=ci, di=di, data=dat, slab=study)'
        else:
            mm = "RR" if meas.id == "rr" else "OR"
            call = f'res <- rma.mh(ai=ai, bi=bi, ci=ci, di=di, data=dat, measure="{mm}", slab=study)'
        lines = [_header(f"Meta-analysis — {meas.name} ({'Peto' if model=='peto' else 'Mantel–Haenszel'})",
                         ["metafor"]), df_to_r(dat, "dat"), "", call,
                 "print(summary(res))", "forest(res, atransf=exp, header=TRUE)", "funnel(res)"]
        return "\n".join(lines) + "\n"
    labels, yi, vi, extra = meas.compute(df)
    ok = np.isfinite(yi) & np.isfinite(vi) & (vi > 0)
    dat = pd.DataFrame({"study": [str(l) for l, o in zip(labels, ok) if o],
                        "yi": np.round(np.asarray(yi)[ok], 6), "vi": np.round(np.asarray(vi)[ok], 8)})
    sub = _col(df, "Subgroup"); yr = _col(df, "Year")
    mod_names = [c for c in df.columns if _re.fullmatch(r"(?i)moderator\d*", str(c).strip())]
    mod_r = []
    for i, c in enumerate(mod_names):
        v = _num(df[c])
        if v.notna().all():
            rn = "moderator" if len(mod_names) == 1 else f"mod{i+1}"
            dat[rn] = [x for x, o in zip(v, ok) if o]; mod_r.append(rn)
    if sub is not None: dat["subgroup"] = [str(x) for x, o in zip(sub, ok) if o]
    if yr is not None: dat["year"] = [x for x, o in zip(_num(yr), ok) if o]
    atr = {"log": "exp", "z": "transf.ztor", "logit": "transf.ilogit"}.get(meas.scale, "")
    atr_arg = f", atransf={atr}" if atr else ""
    method = "FE" if model == "fixed" else {"DL": "DL", "REML": "REML", "PM": "PM"}.get(tau_method, "DL")
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
    if mod_r:
        rhs = " + ".join(mod_r)
        lines.append(f'reg <- rma(yi, vi, mods = ~ {rhs}, data = dat, method = "{method}"); print(reg)')
        if len(mod_r) == 1:
            lines.append("regplot(reg)")
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


# ===========================================================================
# Publication-ready forest (meta::forest style) — overrides the earlier defs
# ===========================================================================
import re as _re
STEEL, ORANGE = "#4682B4", "#E8912A"

def _short(scale, mname):
    if scale == "logit": return "Proportion"
    if scale == "z":     return "Correlation"
    m = _re.search(r"\(([^)]+)\)", mname)
    return m.group(1) if m else mname

def _forest(rows, scale, xlab, col_label, title="", pooled=None, het=None,
            refx=None, xlim=None, xticks=None, weight_col=True, pi=None):
    """rows: list of dict(label, e, lo, hi, w). pooled: dict(label,e,lo,hi) or None."""
    nrow = len(rows)
    row_h = 0.34
    fig_h = 1.6 + row_h*(nrow + (2.0 if pooled else 0))
    fig = plt.figure(figsize=(11, fig_h), dpi=200)
    bottom = 0.85/fig_h; top = 0.55/fig_h
    ax = fig.add_axes([0.38, bottom, 0.27, 1-bottom-top])
    ys = [nrow-1-i for i in range(nrow)]
    ydia = -1.3
    maxw = max([r.get("w") or 0 for r in rows] + [1e-9])
    logx = scale == "log"
    for r, y in zip(rows, ys):
        ax.plot([r["lo"], r["hi"]], [y, y], color="black", lw=1, zorder=2)
        for xx in (r["lo"], r["hi"]):
            ax.plot([xx, xx], [y-0.14, y+0.14], color="black", lw=1, zorder=2)
        s = 45 + (r["w"]/maxw)*320 if (weight_col and r.get("w")) else 70
        ax.scatter([r["e"]], [y], marker="s", s=s, color=STEEL, edgecolor="black", lw=0.6, zorder=3)
    if refx is not None:
        ax.axvline(refx, color="black", ls=":", lw=1, zorder=1)
    if pooled:
        ax.add_patch(Polygon([(pooled["lo"], ydia), (pooled["e"], ydia+0.32),
                              (pooled["hi"], ydia), (pooled["e"], ydia-0.32)],
                             closed=True, facecolor=ORANGE, edgecolor="black", lw=0.8, zorder=4))
    ypi = ydia - 0.62
    if pooled and pi is not None and np.isfinite(pi[0]):
        ax.plot([pi[0], pi[1]], [ypi, ypi], color=ORANGE, lw=1.7, zorder=3, solid_capstyle="round")
        for xx in pi:
            ax.plot([xx, xx], [ypi-0.13, ypi+0.13], color=ORANGE, lw=1.4, zorder=3)
    if logx:
        ax.set_xscale("log")
        from matplotlib.ticker import FixedLocator, NullLocator, FuncFormatter
        loa = min(r["lo"] for r in rows); hia = max(r["hi"] for r in rows)
        cand = [0.1, 0.125, 0.2, 0.25, 0.33, 0.5, 0.67, 1, 1.5, 2, 3, 4, 5, 8, 10]
        ticks = [t for t in cand if loa*0.9 <= t <= hia*1.1] or [round(loa, 2), 1.0, round(hia, 2)]
        ax.xaxis.set_major_locator(FixedLocator(ticks)); ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: ("%g" % v)))
        ax.set_xlim(min(min(ticks), loa)*0.9, max(max(ticks), hia)*1.1)
    else:
        if xlim: ax.set_xlim(*xlim)
        if xticks is not None: ax.set_xticks(xticks)
    ax.set_ylim(ydia-1.05, nrow-0.4)
    ax.set_yticks([]); ax.set_xlabel(xlab, fontsize=11, color=INK)
    for sp in ("top", "right", "left"): ax.spines[sp].set_visible(False)
    ax.tick_params(labelsize=10)
    # ---- text columns (figure coords) ----
    inv = fig.transFigure.inverted()
    def fy(yd): return inv.transform(ax.transData.transform((ax.get_xlim()[0], yd)))[1]
    xL, xE, xC, xW = 0.03, 0.72, 0.80, 0.965
    for r, y in zip(rows, ys):
        yy = fy(y)
        fig.text(xL, yy, str(r["label"]), ha="left", va="center", fontsize=10, color=INK)
        fig.text(xE, yy, f"{r['e']:.2f}", ha="right", va="center", fontsize=10, color=INK)
        fig.text(xC, yy, f"[{r['lo']:.2f}; {r['hi']:.2f}]", ha="left", va="center", fontsize=10, color=INK)
        if weight_col and r.get("w") is not None:
            fig.text(xW, yy, f"{r['w']:.1f}%", ha="right", va="center", fontsize=10, color=INK)
    if pooled:
        yy = fy(ydia)
        fig.text(xL, yy, pooled["label"], ha="left", va="center", fontsize=10.5, fontweight="bold", color=INK)
        fig.text(xE, yy, f"{pooled['e']:.2f}", ha="right", va="center", fontsize=10.5, fontweight="bold", color=INK)
        fig.text(xC, yy, f"[{pooled['lo']:.2f}; {pooled['hi']:.2f}]", ha="left", va="center", fontsize=10.5, fontweight="bold", color=INK)
        if weight_col:
            fig.text(xW, yy, "100.0%", ha="right", va="center", fontsize=10.5, fontweight="bold", color=INK)
    if pooled and pi is not None and np.isfinite(pi[0]):
        yp = fy(ypi)
        fig.text(xL, yp, "95% prediction interval", ha="left", va="center", fontsize=9.5, style="italic", color="#B26A12")
        fig.text(xC, yp, f"[{pi[0]:.2f}; {pi[1]:.2f}]", ha="left", va="center", fontsize=9.5, style="italic", color="#B26A12")
    # header
    yh = fy(nrow-0.4) + 0.012
    fig.text(xL, yh, "Study", ha="left", va="bottom", fontsize=11, fontweight="bold", color=INK)
    fig.text(xE, yh, col_label, ha="right", va="bottom", fontsize=11, fontweight="bold", color=INK)
    fig.text(xC, yh, "95% CI", ha="left", va="bottom", fontsize=11, fontweight="bold", color=INK)
    if weight_col:
        fig.text(xW, yh, "Weight", ha="right", va="bottom", fontsize=11, fontweight="bold", color=INK)
    if het:
        hy = fy(ypi)-0.05 if (pooled and pi is not None and np.isfinite(pi[0])) else fy(ydia)-0.055
        fig.text(xL, hy, het, ha="left", va="top", fontsize=9, color=SUB)
    if title:
        fig.text(xL, 0.985, title, ha="left", va="top", fontsize=12.5, fontweight="bold", color=INK)
    _wm(fig); return fig_to_png(fig, dpi=200)


def _het_str(res):
    tau = f"{res['tau2']:.4f}".rstrip("0").rstrip(".")
    return (f"Heterogeneity: I² = {res['I2']:.1f}%, τ² = {tau}, "
            f"Q({res['df']}) = {res['Q']:.2f}, p = {res['Qp']:.4f}")

def forest_plot(labels, yi, vi, res, scale, mname, title="", pooled_label=None,
                xlab=None, col_label=None):
    k = len(yi); sei = np.sqrt(vi)
    ed, lo, hi = disp(scale, yi), disp(scale, yi-Z*sei), disp(scale, yi+Z*sei)
    w = res.get("weights")
    if w is None or len(w) != k:
        w = 100*(1/vi)/np.sum(1/vi)
    rows = [{"label": labels[i], "e": ed[i], "lo": lo[i], "hi": hi[i], "w": w[i]} for i in range(k)]
    pe, pl, ph = disp(scale, res["est"]), disp(scale, res["ci"][0]), disp(scale, res["ci"][1])
    plab = pooled_label or ("Random effects model" if res.get("model") != "fixed" else "Fixed effect model")
    pooled = {"label": plab, "e": pe, "lo": pl, "hi": ph}
    pi = None
    if res.get("pi") is not None and np.isfinite(res["pi"][0]) and res.get("model") != "fixed":
        pi = (disp(scale, res["pi"][0]), disp(scale, res["pi"][1]))
    if scale == "log": refx, xlim, xticks = 1.0, None, None
    elif scale == "raw": refx, xlim, xticks = 0.0, None, None
    elif scale == "logit": refx, xlim, xticks = pe, (0, 1), np.arange(0, 1.01, 0.2)
    else: refx, xlim, xticks = pe, (-1, 1), np.arange(-1, 1.01, 0.5)
    return _forest(rows, scale, xlab or _short(scale, mname), col_label or _short(scale, mname),
                   title=title, pooled=pooled, het=_het_str(res), refx=refx, xlim=xlim, xticks=xticks, pi=pi)


def _loo_forest(labels, rows_in, res, scale):
    ed = disp(scale, np.array([r[1] for r in rows_in]))
    lo = disp(scale, np.array([r[2] for r in rows_in])); hi = disp(scale, np.array([r[3] for r in rows_in]))
    rows = [{"label": f"Omitting {labels[rows_in[i][0]]}", "e": ed[i], "lo": lo[i], "hi": hi[i], "w": None}
            for i in range(len(rows_in))]
    refx = disp(scale, res["est"])
    xlim = (0, 1) if scale == "logit" else None
    return _forest(rows, scale, "Effect (leave-one-out)", _short(scale, ""), title="Leave-one-out analysis",
                   pooled=None, refx=refx, xlim=xlim, weight_col=False)

def _cumulative_forest(labels, rows_in, order_idx, scale):
    ed = disp(scale, np.array([r[1] for r in rows_in]))
    lo = disp(scale, np.array([r[2] for r in rows_in])); hi = disp(scale, np.array([r[3] for r in rows_in]))
    rows = [{"label": f"+ {labels[order_idx[i]]}", "e": ed[i], "lo": lo[i], "hi": hi[i], "w": None}
            for i in range(len(rows_in))]
    refx = 1.0 if scale == "log" else (0.0 if scale == "raw" else None)
    xlim = (0, 1) if scale == "logit" else None
    return _forest(rows, scale, "Cumulative effect", _short(scale, ""), title="Cumulative meta-analysis",
                   pooled=None, refx=refx, xlim=xlim, weight_col=False)


# ===========================================================================
# Categories + Diagnostic Test Accuracy (DTA) meta-analysis
# ===========================================================================
CAT_ORDER = ["Intervention (two groups)", "Prognostic / survival",
             "Prevalence / single proportion", "Correlation",
             "Pre-post (single arm)", "Diagnostic accuracy (DTA)", "Generic (effect + CI)"]
CATEGORY = {"md": CAT_ORDER[0], "smd": CAT_ORDER[0], "or": CAT_ORDER[0], "rr": CAT_ORDER[0],
            "rd": CAT_ORDER[0], "irr": CAT_ORDER[0], "hr": CAT_ORDER[1], "prop": CAT_ORDER[2],
            "cor": CAT_ORDER[3], "prepost": CAT_ORDER[4], "dta": CAT_ORDER[5], "generic": CAT_ORDER[6]}

# DTA measure (special flow; compute unused — page dispatches to run_dta)
_DTA_EX = {"Study": ["Combaret 2002","Shirai 2022","Kahana-Edwin 2021","Iehara 2019","Chicard 2018",
                     "Lodrini 2017","Chicard 2016","Yagyu 2016","Ruas 2023","Kurihara 2015",
                     "Gotoh 2005","Combaret 2009","Kojima 2013","Ma 2016"],
           "TP": [31,10,7,10,10,5,22,49,4,2,17,53,16,9], "FP": [1,0,0,0,0,0,0,5,2,0,0,0,0,2],
           "FN": [1,0,0,0,0,0,1,8,1,0,0,20,0,1], "TN": [69,12,12,33,9,5,47,86,3,8,70,194,34,93]}
_reg(Measure("dta", "Diagnostic accuracy (sensitivity / specificity / SROC)", "logit",
    [("Study", "Study label"), ("TP", "True positives"), ("FP", "False positives"),
     ("FN", "False negatives"), ("TN", "True negatives")],
    _DTA_EX, lambda df: (None, None, None, {}), "SENS", binary=True))

def by_category():
    out = {c: [] for c in CAT_ORDER}
    for mid, m in MEASURES.items():
        out[CATEGORY.get(mid, CAT_ORDER[-1])].append(m)
    return {c: v for c, v in out.items() if v}


def _prop_ma(labels, ev, n, model, metric):
    ev = np.asarray(ev, float); n = np.asarray(n, float)
    evc = np.clip(ev, 0.5, n-0.5); p = evc/n
    yi = np.log(p/(1-p)); vi = 1/(n*p*(1-p))
    r = pool(yi, vi, model)
    png = forest_plot(labels, yi, vi, r, "logit", "Proportion", xlab=metric, col_label="Proportion")
    return png, r, yi, vi

def _sroc_plot(TP, FP, FN, TN, sens_disp, spec_disp):
    tp, fp, fn, tn = TP+0.5, FP+0.5, FN+0.5, TN+0.5
    TPR = tp/(tp+fn); FPR = fp/(fp+tn); N = TP+FP+FN+TN
    lt = np.log(TPR/(1-TPR)); lf = np.log(FPR/(1-FPR))
    D = lt-lf; S = lt+lf
    slope, intercept = np.polyfit(S, D, 1)
    fg = np.linspace(0.005, 0.995, 200); lfg = np.log(fg/(1-fg))
    ltg = intercept/(1-slope) + (1+slope)/(1-slope)*lfg
    tg = 1/(1+np.exp(-ltg))
    fig, ax = plt.subplots(figsize=(6.4, 6.2), dpi=200)
    ax.plot(fg, tg, color=RED, lw=2, zorder=2, label="SROC curve")
    sizes = 30 + 240*np.sqrt(N)/np.sqrt(N.max())
    ax.scatter(FPR, TPR, s=sizes, facecolor=STEEL, edgecolor="black", lw=0.6, alpha=0.85, zorder=3)
    ax.scatter([1-spec_disp], [sens_disp], marker="*", s=420, color=ORANGE, edgecolor="black",
               lw=0.8, zorder=4, label="Summary point")
    ax.plot([0, 1], [0, 1], color=GREY, ls=":", lw=1)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_aspect("equal")
    ax.set_xlabel("False positive rate (1 − specificity)", fontsize=11, color=INK)
    ax.set_ylabel("Sensitivity", fontsize=11, color=INK)
    ax.set_title("Summary ROC (Moses–Littenberg)", fontsize=12.5, fontweight="bold", color=INK)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200)

def _deeks_plot(labels, TP, FP, FN, TN):
    tp, fp, fn, tn = TP+0.5, FP+0.5, FN+0.5, TN+0.5
    DOR = (tp*tn)/(fp*fn); logDOR = np.log(DOR)
    ndis = tp+fn; nnon = fp+tn; ESS = 4*ndis*nnon/(ndis+nnon); inv = 1/np.sqrt(ESS)
    W = ESS; X = np.column_stack([np.ones_like(inv), inv])
    XtWX = X.T@(W[:, None]*X); beta = np.linalg.solve(XtWX, X.T@(W*logDOR))
    resid = logDOR - X@beta; dof = len(inv)-2
    s2 = np.sum(W*resid**2)/dof; cov = s2*np.linalg.inv(XtWX); se = np.sqrt(np.diag(cov))
    p = 2*(1-stats.t.cdf(abs(beta[1]/se[1]), dof))
    fig, ax = plt.subplots(figsize=(7, 5.4), dpi=200)
    ax.scatter(inv, logDOR, s=55, facecolor=STEEL, edgecolor="black", lw=0.6, zorder=3)
    xs = np.linspace(inv.min(), inv.max(), 50)
    ax.plot(xs, beta[0]+beta[1]*xs, color=RED, lw=1.4)
    ax.set_xlabel("1 / √(Effective sample size)", fontsize=11, color=INK)
    ax.set_ylabel("ln(Diagnostic odds ratio)", fontsize=11, color=INK)
    ax.set_title(f"Deeks' funnel plot (asymmetry p = {p:.3f})", fontsize=12, fontweight="bold", color=INK)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200), p


def run_dta(df, model="random"):
    TP = _num(_col(df, "TP")); FP = _num(_col(df, "FP")); FN = _num(_col(df, "FN")); TN = _num(_col(df, "TN"))
    ok = TP.notna() & FP.notna() & FN.notna() & TN.notna()
    labels = [l for l, o in zip(_labels(df), ok) if o]
    TP, FP, FN, TN = TP[ok].values, FP[ok].values, FN[ok].values, TN[ok].values
    k = len(labels)
    sens_png, sens_r, sy, sv = _prop_ma(labels, TP, TP+FN, model, "Sensitivity")
    spec_png, spec_r, py, pv = _prop_ma(labels, TN, TN+FP, model, "Specificity")
    conc_png, conc_r, cy, cv = _prop_ma(labels, TP+TN, TP+FP+FN+TN, model, "Concordance")
    sens_d = disp("logit", sens_r["est"]); spec_d = disp("logit", spec_r["est"])
    try:
        sroc_png, biv = _sroc_bivariate(TP, FP, FN, TN)   # modern Reitsma bivariate/HSROC
    except Exception:
        sroc_png, biv = _sroc_plot(TP, FP, FN, TN, sens_d, spec_d), None
    deeks_png, deeks_p = _deeks_plot(labels, TP, FP, FN, TN)
    loo_s = _loo_forest(labels, leave_one_out(sy, sv, model), sens_r, "logit")
    loo_p = _loo_forest(labels, leave_one_out(py, pv, model), spec_r, "logit")
    figs = {"Sensitivity forest": sens_png, "Specificity forest": spec_png,
            "Concordance forest": conc_png, "Summary ROC (SROC)": sroc_png,
            "Deeks' funnel plot": deeks_png,
            "Leave-one-out (sensitivity)": loo_s, "Leave-one-out (specificity)": loo_p}
    def ci(r): return f"[{disp('logit', r['ci'][0]):.2f}, {disp('logit', r['ci'][1]):.2f}]"
    dor = (sens_d/(1-sens_d)) / ((1-spec_d)/spec_d)
    extras = {"Pooled sensitivity": f"{sens_d:.3f} {ci(sens_r)}",
              "Pooled specificity": f"{spec_d:.3f} {ci(spec_r)}",
              "Diagnostic odds ratio": f"{dor:.1f}",
              "Deeks' asymmetry test": f"p = {deeks_p:.3f} (" + ("no strong evidence of" if deeks_p >= .05 else "possible") + " publication bias)"}
    if biv is not None:
        extras["Bivariate summary (Reitsma)"] = (
            f"sensitivity {biv['sens']:.3f} [{biv['sensCI'][0]:.2f}, {biv['sensCI'][1]:.2f}], "
            f"specificity {biv['spec']:.3f} [{biv['specCI'][0]:.2f}, {biv['specCI'][1]:.2f}] "
            f"(between-study ρ = {biv['rho']:.2f})")
    table = pd.DataFrame({"Study": labels, "TP": TP.astype(int), "FP": FP.astype(int),
                          "FN": FN.astype(int), "TN": TN.astype(int),
                          "Sensitivity": [f"{t/(t+f):.2f}" for t, f in zip(TP, FN)],
                          "Specificity": [f"{n/(n+p):.2f}" for n, p in zip(TN, FP)]})
    head = (f"DTA meta-analysis (k = {k}): pooled sensitivity {sens_d:.2f} {ci(sens_r)}, "
            f"specificity {spec_d:.2f} {ci(spec_r)}")
    interp = (f"Across {k} studies, pooled sensitivity was {sens_d:.2f} and specificity {spec_d:.2f} "
              f"(diagnostic odds ratio {dor:.1f}). The SROC summarises the joint accuracy; "
              f"Deeks' test p = {deeks_p:.3f}.")
    caveats = ["The SROC uses the Reitsma bivariate / HSROC model (matching mada::reitsma); if it fails to "
               "converge it falls back to the Moses–Littenberg curve.",
               "Studies with a zero cell receive a 0.5 continuity correction."]
    return MetaResult(head, sens_r, table, interp, figs, extras, caveats)


def r_script_dta(df, model="random"):
    from .r_export import df_to_r
    TP = _num(_col(df, "TP")); FP = _num(_col(df, "FP")); FN = _num(_col(df, "FN")); TN = _num(_col(df, "TN"))
    ok = TP.notna() & FP.notna() & FN.notna() & TN.notna()
    dat = pd.DataFrame({"study": [l for l, o in zip(_labels(df), ok) if o],
                        "TP": TP[ok].astype(int).values, "FP": FP[ok].astype(int).values,
                        "FN": FN[ok].astype(int).values, "TN": TN[ok].astype(int).values})
    from .r_export import _header
    return "\n".join([
        _header("Diagnostic test accuracy meta-analysis", ["meta", "mada", "ggplot2", "ggrepel"]),
        df_to_r(dat, "d"), "",
        '# --- Sensitivity & Specificity forests (meta::metaprop, PLOGIT) ---',
        'm_sens <- metaprop(TP, TP+FN, studlab=study, data=d, sm="PLOGIT", method.tau="DL", random=TRUE, common=FALSE)',
        'meta::forest(m_sens, xlim=c(0,1), rightcols=c("effect","ci","w.random"), xlab="Sensitivity", col.diamond="orange", col.square="steelblue")',
        'm_spec <- metaprop(TN, TN+FP, studlab=study, data=d, sm="PLOGIT", method.tau="DL", random=TRUE, common=FALSE)',
        'meta::forest(m_spec, xlim=c(0,1), rightcols=c("effect","ci","w.random"), xlab="Specificity", col.diamond="orange", col.square="steelblue")',
        'm_conc <- metaprop(TP+TN, TP+FP+FN+TN, studlab=study, data=d, sm="PLOGIT", method.tau="DL", random=TRUE, common=FALSE)',
        'meta::forest(m_conc, xlim=c(0,1), xlab="Concordance", col.diamond="orange", col.square="steelblue")',
        "",
        '# --- Bivariate / HSROC model + SROC curve (mada::reitsma) ---',
        'dm <- data.frame(TP=d$TP, FP=d$FP, FN=d$FN, TN=d$TN)',
        'fit <- reitsma(dm, correction=0.5, correction.control="all"); print(summary(fit))',
        'plot(fit, sroclwd=2, xlim=c(0,1), ylim=c(0,1)); ROCellipse(fit, add=TRUE, col="firebrick")',
        "",
        "# --- Deeks' funnel plot for publication bias ---",
        'd2 <- transform(d, DOR=((TP+.5)*(TN+.5))/((FP+.5)*(FN+.5)),',
        '                ESS=4*((TP+.5)+(FN+.5))*((FP+.5)+(TN+.5))/(((TP+.5)+(FN+.5))+((FP+.5)+(TN+.5))))',
        'd2$logDOR <- log(d2$DOR); d2$inv <- 1/sqrt(d2$ESS)',
        'summary(lm(logDOR ~ inv, data=d2, weights=ESS))   # slope p = Deeks asymmetry',
        "",
        "# --- Leave-one-out sensitivity/specificity ---",
        'meta::forest(metainf(m_sens, pooled="random"), xlab="Sensitivity (leave-one-out)")',
        'meta::forest(metainf(m_spec, pooled="random"), xlab="Specificity (leave-one-out)")',
    ]) + "\n"


# ===========================================================================
# Reitsma bivariate model (modern DTA meta-analysis) + HSROC plot
# ===========================================================================
def _expit(x): return 1/(1+np.exp(-x))

def reitsma_bivariate(TP, FP, FN, TN):
    """ML fit of the Reitsma bivariate random-effects model on
    (logit sensitivity, logit false-positive-rate). Returns summary point,
    between-study covariance, and the covariance of the summary estimates."""
    from scipy.optimize import minimize
    tp, fp, fn, tn = TP+0.5, FP+0.5, FN+0.5, TN+0.5
    ySe = np.log(tp/fn); vSe = 1/tp + 1/fn          # logit(Se) + var
    yF = np.log(fp/tn);  vF = 1/fp + 1/tn           # logit(FPR) + var
    Y = np.column_stack([ySe, yF]); k = len(tp)
    S = [np.diag([vSe[i], vF[i]]) for i in range(k)]

    def nll(p):
        muSe, muF, lts, ltf, zr = p
        ts, tf, rho = np.exp(lts), np.exp(ltf), np.tanh(zr)
        Sb = np.array([[ts*ts, rho*ts*tf], [rho*ts*tf, tf*tf]])
        mu = np.array([muSe, muF]); tot = 0.0
        for i in range(k):
            V = Sb + S[i]
            sign, ld = np.linalg.slogdet(V)
            if sign <= 0: return 1e12
            d = Y[i]-mu; tot += 0.5*ld + 0.5*d @ np.linalg.solve(V, d)
        return tot

    p0 = [ySe.mean(), yF.mean(), np.log(0.4), np.log(0.4), 0.0]
    r = minimize(nll, p0, method="Nelder-Mead",
                 options={"maxiter": 6000, "xatol": 1e-7, "fatol": 1e-7})
    muSe, muF, lts, ltf, zr = r.x
    ts, tf, rho = np.exp(lts), np.exp(ltf), np.tanh(zr)
    Sb = np.array([[ts*ts, rho*ts*tf], [rho*ts*tf, tf*tf]])
    A = np.zeros((2, 2))
    for i in range(k):
        A += np.linalg.inv(Sb + S[i])
    covmu = np.linalg.inv(A)
    return {"muSe": muSe, "muF": muF, "Sb": Sb, "covmu": covmu, "rho": rho,
            "sens": _expit(muSe), "spec": _expit(-muF),
            "sensCI": (_expit(muSe-Z*np.sqrt(covmu[0, 0])), _expit(muSe+Z*np.sqrt(covmu[0, 0]))),
            "specCI": (_expit(-(muF+Z*np.sqrt(covmu[1, 1]))), _expit(-(muF-Z*np.sqrt(covmu[1, 1]))))}

def _sroc_bivariate(TP, FP, FN, TN):
    r = reitsma_bivariate(TP, FP, FN, TN)
    tp, fp, fn, tn = TP+0.5, FP+0.5, FN+0.5, TN+0.5
    TPR = tp/(tp+fn); FPR = fp/(fp+tn); N = TP+FP+FN+TN
    # SROC curve = conditional mean of logit(Se) given logit(FPR)
    slope = r["Sb"][0, 1]/r["Sb"][1, 1]
    fg = np.linspace(0.005, 0.995, 300); lf = np.log(fg/(1-fg))
    Se = _expit(r["muSe"] + slope*(lf - r["muF"]))
    sx, sy = _expit(r["muF"]), _expit(r["muSe"])   # summary operating point
    # 95% confidence ellipse in (FPR, Se) space
    C = np.array([[r["covmu"][1, 1], r["covmu"][1, 0]], [r["covmu"][0, 1], r["covmu"][0, 0]]])
    center = np.array([r["muF"], r["muSe"]])
    vals, vecs = np.linalg.eigh(C); vals = np.clip(vals, 1e-12, None)
    th = np.linspace(0, 2*np.pi, 200); sc = np.sqrt(stats.chi2.ppf(0.95, 2))
    pts = center[:, None] + (vecs @ (np.sqrt(vals)[:, None]*np.vstack([np.cos(th), np.sin(th)])))*sc
    ex, ey = _expit(pts[0]), _expit(pts[1])
    fig, ax = plt.subplots(figsize=(6.4, 6.3), dpi=200)
    ax.plot(fg, Se, color=RED, lw=2, zorder=2, label="Bivariate SROC")
    ax.plot(ex, ey, color=ORANGE, lw=1.6, ls="--", zorder=3, label="95% confidence region")
    sizes = 30 + 240*np.sqrt(N)/np.sqrt(N.max())
    ax.scatter(FPR, TPR, s=sizes, facecolor=STEEL, edgecolor="black", lw=0.6, alpha=0.85, zorder=4)
    ax.scatter([sx], [sy], marker="*", s=430, color=ORANGE, edgecolor="black", lw=0.8, zorder=5,
               label="Summary point")
    ax.plot([0, 1], [0, 1], color=GREY, ls=":", lw=1)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.set_aspect("equal")
    ax.set_xlabel("False positive rate (1 − specificity)", fontsize=11, color=INK)
    ax.set_ylabel("Sensitivity", fontsize=11, color=INK)
    ax.set_title("Summary ROC — Reitsma bivariate model", fontsize=12.5, fontweight="bold", color=INK)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    for s in ("top", "right"): ax.spines[s].set_visible(False)
    fig.tight_layout(); _wm(fig); return fig_to_png(fig, dpi=200), r
