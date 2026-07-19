"""
stats_lab.py
============
Jarvis Scholar — No-Code Statistics (Phase A).

Mirrors the Plot Studio engine: every test is a `TestSpec` in `REGISTRY`
describing the Excel template columns and a run(df, params) -> StatResult.
Each result carries an APA-style headline, a numeric table, assumption
checks, a plain-language interpretation, caveats, and (optionally) a
companion figure — so a non-statistician gets a defensible answer, not just
a p-value.

Wheel-safe libs only: scipy, statsmodels, scikit-learn, pingouin,
scikit-posthocs. Heavy libs are imported lazily inside each run().
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import numpy as np
import pandas as pd

from .plot_studio import _col, _num, PlotOptions, new_fig, fig_to_png, finish, palette


# ---------------------------------------------------------------------------
# Specs + results
# ---------------------------------------------------------------------------
@dataclass
class Column:
    name: str
    kind: str = "number"          # number | text | int
    required: bool = True
    help: str = ""


@dataclass
class Param:
    name: str
    kind: str = "number"          # number | int | select
    default: object = 0.0
    options: Optional[list] = None
    help: str = ""


@dataclass
class TestSpec:
    id: str
    name: str
    category: str
    desc: str
    columns: List[Column]
    example: dict
    run: Callable
    needs_data: bool = True
    params: List[Param] = field(default_factory=list)
    notes: str = ""


@dataclass
class StatResult:
    headline: str                          # APA-style one-liner
    table: pd.DataFrame                    # main numbers
    interpretation: str = ""               # plain language
    assumptions: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    figure_png: Optional[bytes] = None

    def report_text(self, title="") -> str:
        lines = []
        if title:
            lines += [title, "=" * len(title), ""]
        lines += [self.headline, ""]
        if not self.table.empty:
            lines += [self.table.to_string(index=False), ""]
        if self.interpretation:
            lines += ["Interpretation:", self.interpretation, ""]
        if self.assumptions:
            lines += ["Assumption checks:"] + [f"  - {a}" for a in self.assumptions] + [""]
        if self.caveats:
            lines += ["Caveats:"] + [f"  - {c}" for c in self.caveats] + [""]
        lines += ["Generated with Jarvis Scholar — verify against your data and study design."]
        return "\n".join(lines)


REGISTRY: "dict[str, TestSpec]" = {}


def register(spec: TestSpec):
    REGISTRY[spec.id] = spec
    return spec


def by_category() -> "dict[str, list[TestSpec]]":
    out: "dict[str, list[TestSpec]]" = {}
    for s in REGISTRY.values():
        out.setdefault(s.category, []).append(s)
    return out


def locate(test_id: str):
    """Return (category, display_name) for a test id — used by the wizard to
    jump the picker to a recommended test."""
    s = REGISTRY.get(test_id)
    return (s.category, s.name) if s else (None, None)


def template_bytes(spec: TestSpec) -> bytes:
    data = pd.DataFrame({c.name: spec.example.get(c.name, []) for c in spec.columns})
    info = pd.DataFrame({"Column": [c.name for c in spec.columns],
                         "Type": [c.kind for c in spec.columns],
                         "Required": ["Yes" if c.required else "Optional" for c in spec.columns],
                         "What to enter": [c.help for c in spec.columns]})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        data.to_excel(xl, sheet_name="Data", index=False)
        info.to_excel(xl, sheet_name="Instructions", index=False)
    return buf.getvalue()


def validate(spec: TestSpec, df: pd.DataFrame) -> "list[str]":
    problems = []
    have = {c.strip().lower() for c in df.columns}
    for c in spec.columns:
        if c.required and c.name.strip().lower() not in have:
            problems.append(f"Missing required column '{c.name}'.")
    if df.dropna(how="all").empty:
        problems.append("The Data sheet is empty.")
    return problems


# ---------------------------------------------------------------------------
# Formatting + small stats helpers
# ---------------------------------------------------------------------------
def fmt_p(p) -> str:
    if p is None or (isinstance(p, float) and np.isnan(p)):
        return "p = n/a"
    return "p < .001" if p < 0.001 else f"p = {p:.3f}"


def star(p) -> str:
    if p is None or np.isnan(p):
        return ""
    return "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else "ns"


def cohen_d(a, b) -> float:
    a = np.asarray(a, float); b = np.asarray(b, float)
    na, nb = len(a), len(b)
    sp = np.sqrt(((na - 1) * a.std(ddof=1) ** 2 + (nb - 1) * b.std(ddof=1) ** 2) / (na + nb - 2))
    return (a.mean() - b.mean()) / sp if sp else np.nan


def d_magnitude(d) -> str:
    ad = abs(d)
    return "negligible" if ad < .2 else "small" if ad < .5 else "medium" if ad < .8 else "large"


def _fig_from(ax_builder, opt=None):
    opt = opt or PlotOptions(figsize=(7, 4.4), dpi=160)
    fig, ax = new_fig(opt)
    ax_builder(fig, ax, opt)
    return fig_to_png(finish(fig, ax, opt), dpi=opt.dpi)


def _welch_df(a, b):
    va, vb = a.var(ddof=1), b.var(ddof=1); na, nb = len(a), len(b)
    num = (va/na + vb/nb) ** 2
    den = (va/na) ** 2 / (na-1) + (vb/nb) ** 2 / (nb-1)
    return num/den if den else (na+nb-2)


def _group_fig(d, gcol, vcol, title=""):
    def build(fig, ax, opt):
        groups = list(pd.unique(d[gcol]))
        data = [d[d[gcol] == gr][vcol].values for gr in groups]
        bp = ax.boxplot(data, patch_artist=True, labels=[str(x) for x in groups], widths=0.6)
        for i, box in enumerate(bp["boxes"]):
            box.set(facecolor=palette(opt)[i % 8], alpha=0.65, edgecolor="#41566b")
        for m in bp["medians"]:
            m.set(color="#12283b", linewidth=1.5)
        for i, gr in enumerate(groups):
            y = d[d[gcol] == gr][vcol].values
            ax.scatter(np.full(len(y), i+1) + np.random.uniform(-.08, .08, len(y)), y,
                       s=18, color=palette(opt)[i % 8], alpha=0.6, edgecolor="white", linewidth=.4)
        ax.set_ylabel(vcol); ax.set_title(title, fontsize=12, fontweight="bold", color="#12283b")
    return _fig_from(build)


# ===========================================================================
# 1. DESCRIPTIVE
# ===========================================================================
def run_descriptives(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")); g = _col(df, "Group")
    def summ(vals, name):
        vals = vals.dropna(); n = len(vals)
        m = vals.mean(); sd = vals.std(ddof=1); se = sd/np.sqrt(n) if n else np.nan
        ci = stats.t.interval(0.95, n-1, loc=m, scale=se) if n > 1 else (np.nan, np.nan)
        return {"Group": name, "n": n, "Mean": round(m, 3), "SD": round(sd, 3),
                "Median": round(vals.median(), 3),
                "IQR": round(vals.quantile(.75) - vals.quantile(.25), 3),
                "Min": round(vals.min(), 3), "Max": round(vals.max(), 3),
                "95% CI (mean)": f"[{ci[0]:.2f}, {ci[1]:.2f}]"}
    rows = ([summ(v[g == grp], str(grp)) for grp in pd.unique(g.dropna())]
            if g is not None else [summ(v, "All")])
    return StatResult("Descriptive summary (with 95% CI for the mean)", pd.DataFrame(rows),
                      interpretation="Central tendency, spread and a 95% confidence interval for each group's mean.")

register(TestSpec("descriptives", "Descriptive summary", "1. Descriptive",
    "n, mean, SD, median, IQR, range and 95% CI — overall or by group.",
    [Column("Value", "number", True, "Numeric values"),
     Column("Group", "text", False, "Optional grouping")],
    {"Value": [12,15,14,18,21,13,16,19,17,20], "Group": ["A"]*5 + ["B"]*5},
    run_descriptives))


def run_crosstab(df, params=None):
    a = _col(df, "CatA").astype(str); b = _col(df, "CatB").astype(str)
    ct = pd.crosstab(a, b, margins=True, margins_name="Total")
    return StatResult("Cross-tabulation (counts)", ct.reset_index(),
                      interpretation="Contingency table of the two categorical variables. "
                                     "For a significance test use Chi-square or Fisher's exact.")

register(TestSpec("crosstab", "Cross-tabulation", "1. Descriptive",
    "Counts for two categorical variables.",
    [Column("CatA", "text", True, "First category"), Column("CatB", "text", True, "Second category")],
    {"CatA": ["M","M","F","F","M","F"], "CatB": ["Yes","No","Yes","No","Yes","Yes"]},
    run_crosstab))


# ===========================================================================
# 2. ASSUMPTION CHECKS
# ===========================================================================
def run_shapiro(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")); g = _col(df, "Group")
    groups = list(pd.unique(g.dropna())) if g is not None else [None]
    rows = []
    for grp in groups:
        vals = (v[g == grp] if grp is not None else v).dropna()
        if len(vals) < 3:
            continue
        W, p = stats.shapiro(vals)
        rows.append({"Group": str(grp) if grp is not None else "All", "n": len(vals),
                     "W": round(W, 3), "p": round(p, 4), "Normal? (α=.05)": "Yes" if p >= .05 else "No"})
    table = pd.DataFrame(rows)
    bad = [r["Group"] for r in rows if r["p"] < .05]
    interp = ("Data look approximately normal — parametric tests are appropriate."
              if not bad else f"Non-normal (p < .05): {', '.join(bad)}. Prefer a non-parametric alternative "
                             "(Mann–Whitney, Kruskal–Wallis, Wilcoxon).")
    return StatResult("Shapiro–Wilk normality test", table, interpretation=interp,
                      caveats=["Shapiro–Wilk is sensitive with large n; also check a Q–Q plot."])

register(TestSpec("shapiro", "Normality (Shapiro–Wilk)", "2. Assumption checks",
    "Test whether values are normally distributed (per group).",
    [Column("Value", "number", True, "Numeric values"), Column("Group", "text", False, "Optional group")],
    {"Value": [12,15,14,18,21,13,16,19,17,20], "Group": ["A"]*5 + ["B"]*5},
    run_shapiro))


def run_levene(df, params=None):
    from scipy import stats
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = [d[d.g == gr]["v"].values for gr in pd.unique(d.g)]
    W, p = stats.levene(*groups)
    table = pd.DataFrame([{"Levene W": round(W, 3), "p": round(p, 4),
                           "Equal variances? (α=.05)": "Yes" if p >= .05 else "No"}])
    return StatResult(f"Levene's test: W = {W:.3f}, {fmt_p(p)}", table,
                      interpretation=("Variances are homogeneous — standard t-test/ANOVA are fine."
                                      if p >= .05 else "Variances differ — use Welch's t-test / Welch ANOVA."))

register(TestSpec("levene", "Equal variances (Levene)", "2. Assumption checks",
    "Test homogeneity of variance across groups.",
    [Column("Group", "text", True, "Group label"), Column("Value", "number", True, "Numeric values")],
    {"Group": ["A"]*5 + ["B"]*5, "Value": [12,15,14,18,21,5,26,9,32,11]},
    run_levene))


# ===========================================================================
# 3. TWO-GROUP COMPARISON
# ===========================================================================
def run_ttest_ind(df, params=None):
    from scipy import stats
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = list(pd.unique(d.g))
    if len(groups) != 2:
        return StatResult("Independent t-test needs exactly two groups.",
                          pd.DataFrame({"Groups found": [", ".join(map(str, groups))]}),
                          caveats=["Provide a Group column with exactly two distinct values."])
    a = d[d.g == groups[0]]["v"].values; b = d[d.g == groups[1]]["v"].values
    lev_p = stats.levene(a, b)[1]; equal = lev_p >= .05
    t, p = stats.ttest_ind(a, b, equal_var=equal)
    dof = (len(a)+len(b)-2) if equal else _welch_df(a, b)
    dval = cohen_d(a, b)
    norm = [stats.shapiro(x)[1] for x in (a, b) if len(x) >= 3]
    test_name = "Student's t-test" if equal else "Welch's t-test"
    table = pd.DataFrame([
        {"Group": str(groups[0]), "n": len(a), "Mean": round(a.mean(), 3), "SD": round(a.std(ddof=1), 3)},
        {"Group": str(groups[1]), "n": len(b), "Mean": round(b.mean(), 3), "SD": round(b.std(ddof=1), 3)}])
    hi, lo = (groups[0], groups[1]) if a.mean() >= b.mean() else (groups[1], groups[0])
    assum = [f"Levene equal-variance p = {lev_p:.3f} → {'equal' if equal else 'unequal'} variances "
             f"({test_name} used).",
             "Normality (Shapiro p): " + ", ".join(f"{gr}={pp:.3f}" for gr, pp in zip(groups, norm))
             if norm else "Normality not tested (n<3)."]
    caveats = []
    if min(len(a), len(b)) < 15:
        caveats.append("Small sample — consider Mann–Whitney U as a robust check.")
    if any(pp < .05 for pp in norm):
        caveats.append("A group looks non-normal — Mann–Whitney U may be more appropriate.")
    return StatResult(
        f"{test_name}: t({dof:.0f}) = {t:.2f}, {fmt_p(p)}, d = {dval:.2f} ({d_magnitude(dval)})",
        table,
        interpretation=(f"{'A significant' if p < .05 else 'No significant'} difference"
                        f"{' — ' + str(hi) + ' > ' + str(lo) if p < .05 else ''}. "
                        f"Effect size d = {dval:.2f} ({d_magnitude(dval)})."),
        assumptions=assum, caveats=caveats,
        figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("ttest_ind", "Independent t-test", "3. Two-group comparison",
    "Compare the means of two independent groups (auto-selects Student vs Welch).",
    [Column("Group", "text", True, "Two-group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*6 + ["B"]*6, "Value": [12,15,14,18,13,16, 20,22,19,24,21,23]},
    run_ttest_ind))


def run_mann_whitney(df, params=None):
    from scipy import stats
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = list(pd.unique(d.g))
    if len(groups) != 2:
        return StatResult("Mann–Whitney needs exactly two groups.",
                          pd.DataFrame({"Groups found": [", ".join(map(str, groups))]}))
    a = d[d.g == groups[0]]["v"].values; b = d[d.g == groups[1]]["v"].values
    U, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    rbc = 1 - (2 * U) / (len(a) * len(b))
    table = pd.DataFrame([
        {"Group": str(groups[0]), "n": len(a), "Median": round(np.median(a), 3)},
        {"Group": str(groups[1]), "n": len(b), "Median": round(np.median(b), 3)}])
    return StatResult(
        f"Mann–Whitney U = {U:.1f}, {fmt_p(p)}, rank-biserial r = {rbc:.2f}", table,
        interpretation=(f"{'A significant' if p < .05 else 'No significant'} difference in distributions/medians. "
                        f"Rank-biserial effect r = {rbc:.2f}."),
        assumptions=["Non-parametric — no normality assumption; compares distributions/medians."],
        figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("mann_whitney", "Mann–Whitney U", "3. Two-group comparison",
    "Non-parametric comparison of two independent groups.",
    [Column("Group", "text", True, "Two-group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*6 + ["B"]*6, "Value": [12,15,14,18,13,16, 20,22,19,24,21,23]},
    run_mann_whitney))


def run_ttest_one(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")).dropna()
    mu = float((params or {}).get("Population mean (mu0)", 0.0))
    t, p = stats.ttest_1samp(v, mu)
    d = (v.mean() - mu) / v.std(ddof=1)
    table = pd.DataFrame([{"n": len(v), "Mean": round(v.mean(), 3), "SD": round(v.std(ddof=1), 3),
                           "Tested against μ₀": mu}])
    return StatResult(f"One-sample t-test: t({len(v)-1}) = {t:.2f}, {fmt_p(p)}, d = {d:.2f}", table,
                      interpretation=(f"The mean {'differs' if p < .05 else 'does not differ'} "
                                      f"significantly from {mu}."))

register(TestSpec("ttest_one", "One-sample t-test", "3. Two-group comparison",
    "Compare a sample mean to a fixed reference value.",
    [Column("Value", "number", True, "Numeric values")],
    {"Value": [12,15,14,18,21,13,16,19,17,20]},
    run_ttest_one, params=[Param("Population mean (mu0)", "number", 15.0, help="Reference value μ₀")]))


# ===========================================================================
# 4. THREE-OR-MORE GROUPS
# ===========================================================================
def run_anova(df, params=None):
    from scipy import stats
    from statsmodels.stats.multicomp import pairwise_tukeyhsd
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = list(pd.unique(d.g))
    arrays = [d[d.g == gr]["v"].values for gr in groups]
    F, p = stats.f_oneway(*arrays)
    grand = d["v"].mean()
    ss_b = sum(len(x) * (x.mean() - grand) ** 2 for x in arrays)
    ss_t = ((d["v"] - grand) ** 2).sum()
    eta2 = ss_b / ss_t if ss_t else np.nan
    dfb = len(groups) - 1; dfw = len(d) - len(groups)
    tukey = pairwise_tukeyhsd(d["v"], d["g"])
    tk = pd.DataFrame(tukey._results_table.data[1:], columns=tukey._results_table.data[0])
    lev = stats.levene(*arrays)[1]
    caveats = ["Variances differ (Levene p<.05) — consider Welch's ANOVA."] if lev < .05 else []
    return StatResult(
        f"One-way ANOVA: F({dfb}, {dfw}) = {F:.2f}, {fmt_p(p)}, η² = {eta2:.3f}", tk,
        interpretation=(f"{'At least one group differs' if p < .05 else 'No significant difference between groups'}"
                        f" (η² = {eta2:.3f}). Tukey HSD table shows which pairs differ (reject = True)."),
        assumptions=[f"Levene equal-variance p = {lev:.3f}."], caveats=caveats,
        figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("anova_oneway", "One-way ANOVA (+ Tukey)", "4. Three+ groups",
    "Compare means across ≥3 groups, with Tukey HSD post-hoc.",
    [Column("Group", "text", True, "Group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*4 + ["B"]*4 + ["C"]*4, "Value": [12,14,13,15, 18,20,19,21, 9,11,10,12]},
    run_anova))


def run_welch_anova(df, params=None):
    import pingouin as pg
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    aov = pg.welch_anova(dv="v", between="g", data=d)
    pcol = "p_unc" if "p_unc" in aov.columns else ("p-unc" if "p-unc" in aov.columns else aov.columns[-2])
    F = aov["F"].iloc[0]; p = aov[pcol].iloc[0]; np2 = aov["np2"].iloc[0]
    ddof1 = aov["ddof1"].iloc[0]; ddof2 = aov["ddof2"].iloc[0]
    return StatResult(f"Welch's ANOVA: F({ddof1:.0f}, {ddof2:.1f}) = {F:.2f}, {fmt_p(p)}, η²_p = {np2:.3f}",
                      aov.round(4),
                      interpretation=("At least one group mean differs (robust to unequal variances)."
                                      if p < .05 else "No significant difference between group means."),
                      figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("welch_anova", "Welch's ANOVA", "4. Three+ groups",
    "ANOVA that does not assume equal variances.",
    [Column("Group", "text", True, "Group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*4 + ["B"]*4 + ["C"]*4, "Value": [12,14,13,15, 18,25,19,30, 9,11,10,12]},
    run_welch_anova))


def run_kruskal(df, params=None):
    from scipy import stats
    import scikit_posthocs as sp
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = list(pd.unique(d.g))
    arrays = [d[d.g == gr]["v"].values for gr in groups]
    H, p = stats.kruskal(*arrays)
    dunn = sp.posthoc_dunn(d, val_col="v", group_col="g", p_adjust="bonferroni").round(4)
    return StatResult(f"Kruskal–Wallis H({len(groups)-1}) = {H:.2f}, {fmt_p(p)}",
                      dunn.reset_index().rename(columns={"index": "group"}),
                      interpretation=("Groups differ; Dunn's post-hoc (Bonferroni) table shows which pairs "
                                      "(p<.05)." if p < .05 else "No significant difference between groups."),
                      assumptions=["Non-parametric — no normality assumption."],
                      figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("kruskal", "Kruskal–Wallis (+ Dunn)", "4. Three+ groups",
    "Non-parametric comparison of ≥3 groups, with Dunn post-hoc.",
    [Column("Group", "text", True, "Group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*4 + ["B"]*4 + ["C"]*4, "Value": [12,14,13,15, 18,20,19,21, 9,11,10,12]},
    run_kruskal))


# ===========================================================================
# 5. PAIRED / REPEATED
# ===========================================================================
def run_ttest_paired(df, params=None):
    from scipy import stats
    a = _num(_col(df, "Before")); b = _num(_col(df, "After"))
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    t, p = stats.ttest_rel(d["a"], d["b"])
    diff = d["a"] - d["b"]; dz = diff.mean() / diff.std(ddof=1)
    table = pd.DataFrame([{"n pairs": len(d), "Mean Before": round(d["a"].mean(), 3),
                           "Mean After": round(d["b"].mean(), 3), "Mean diff": round(diff.mean(), 3)}])
    return StatResult(f"Paired t-test: t({len(d)-1}) = {t:.2f}, {fmt_p(p)}, dz = {dz:.2f}", table,
                      interpretation=(f"The paired change is {'statistically significant' if p < .05 else 'not significant'} "
                                      f"(dz = {dz:.2f}, {d_magnitude(dz)})."),
                      caveats=(["Small n — consider Wilcoxon signed-rank."] if len(d) < 15 else []))

register(TestSpec("ttest_paired", "Paired t-test", "5. Paired / repeated",
    "Compare two related measurements (e.g. before vs after).",
    [Column("Before", "number", True, "First measurement"), Column("After", "number", True, "Second measurement")],
    {"Before": [10,12,14,11,13,9], "After": [14,15,16,13,17,12]},
    run_ttest_paired))


def run_wilcoxon(df, params=None):
    from scipy import stats
    a = _num(_col(df, "Before")); b = _num(_col(df, "After"))
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    W, p = stats.wilcoxon(d["a"], d["b"])
    table = pd.DataFrame([{"n pairs": len(d), "Median Before": round(d["a"].median(), 3),
                           "Median After": round(d["b"].median(), 3)}])
    return StatResult(f"Wilcoxon signed-rank: W = {W:.1f}, {fmt_p(p)}", table,
                      interpretation=("A significant paired change." if p < .05 else "No significant paired change."),
                      assumptions=["Non-parametric paired test — no normality assumption."])

register(TestSpec("wilcoxon", "Wilcoxon signed-rank", "5. Paired / repeated",
    "Non-parametric paired comparison.",
    [Column("Before", "number", True, "First measurement"), Column("After", "number", True, "Second measurement")],
    {"Before": [10,12,14,11,13,9], "After": [14,15,16,13,17,12]},
    run_wilcoxon))


def run_friedman(df, params=None):
    from scipy import stats
    s = _col(df, "Subject").astype(str); c = _col(df, "Condition").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"s": s, "c": c, "v": v}).dropna()
    wide = d.pivot_table(index="s", columns="c", values="v").dropna()
    chi, p = stats.friedmanchisquare(*[wide[col].values for col in wide.columns])
    table = wide.median().reset_index(); table.columns = ["Condition", "Median"]
    return StatResult(f"Friedman χ²({wide.shape[1]-1}) = {chi:.2f}, {fmt_p(p)}", table,
                      interpretation=("Conditions differ across repeated measures." if p < .05
                                      else "No significant difference across conditions."),
                      assumptions=["Non-parametric repeated-measures test."])

register(TestSpec("friedman", "Friedman test", "5. Paired / repeated",
    "Non-parametric test across ≥3 repeated conditions.",
    [Column("Subject", "text", True, "Subject ID"), Column("Condition", "text", True, "Condition"),
     Column("Value", "number", True, "Numeric outcome")],
    {"Subject": ["P1","P1","P1","P2","P2","P2","P3","P3","P3"],
     "Condition": ["T1","T2","T3"]*3, "Value": [10,12,15,9,11,14,8,13,16]},
    run_friedman))


# ===========================================================================
# 6. CATEGORICAL
# ===========================================================================
def run_chi_square(df, params=None):
    from scipy import stats
    a = _col(df, "CatA").astype(str); b = _col(df, "CatB").astype(str)
    ct = pd.crosstab(a, b)
    chi, p, dof, exp = stats.chi2_contingency(ct)
    n = ct.values.sum(); k = min(ct.shape) - 1
    V = np.sqrt(chi / (n * k)) if k else np.nan
    caveats = ["Some expected counts < 5 — use Fisher's exact instead."] if (exp < 5).any() else []
    return StatResult(f"Chi-square χ²({dof}) = {chi:.2f}, {fmt_p(p)}, Cramér's V = {V:.2f}",
                      ct.reset_index(),
                      interpretation=(f"The variables are {'associated' if p < .05 else 'not significantly associated'} "
                                      f"(Cramér's V = {V:.2f})."),
                      caveats=caveats)

register(TestSpec("chi_square", "Chi-square (independence)", "6. Categorical",
    "Test association between two categorical variables.",
    [Column("CatA", "text", True, "First category"), Column("CatB", "text", True, "Second category")],
    {"CatA": ["M","M","M","F","F","F","M","F","M","F"],
     "CatB": ["Yes","No","Yes","No","No","Yes","Yes","No","No","Yes"]},
    run_chi_square))


def run_fisher(df, params=None):
    from scipy import stats
    a = _col(df, "CatA").astype(str); b = _col(df, "CatB").astype(str)
    ct = pd.crosstab(a, b)
    if ct.shape != (2, 2):
        return StatResult("Fisher's exact needs a 2×2 table.", ct.reset_index(),
                          caveats=["Each category must have exactly two levels."])
    OR, p = stats.fisher_exact(ct)
    return StatResult(f"Fisher's exact: OR = {OR:.2f}, {fmt_p(p)}", ct.reset_index(),
                      interpretation=(f"{'A significant' if p < .05 else 'No significant'} association "
                                      f"(odds ratio = {OR:.2f})."))

register(TestSpec("fisher", "Fisher's exact (2×2)", "6. Categorical",
    "Exact test for small 2×2 tables.",
    [Column("CatA", "text", True, "First category (2 levels)"), Column("CatB", "text", True, "Second category (2 levels)")],
    {"CatA": ["Yes","Yes","No","No","Yes","No"], "CatB": ["Pos","Neg","Neg","Neg","Pos","Pos"]},
    run_fisher))


def run_riskratio(df, params=None):
    exp = _col(df, "Exposure").astype(str); out = _col(df, "Outcome").astype(str)
    ct = pd.crosstab(exp, out)
    if ct.shape != (2, 2):
        return StatResult("Risk/odds ratio needs 2×2 (Exposure × Outcome).", ct.reset_index())
    a, b = ct.iloc[0, 0], ct.iloc[0, 1]; c, d = ct.iloc[1, 0], ct.iloc[1, 1]
    a, b, c, d = [x + 0.5 if x == 0 else x for x in (a, b, c, d)]
    rr = (a / (a + b)) / (c / (c + d)); se_rr = np.sqrt(1/a - 1/(a+b) + 1/c - 1/(c+d))
    orr = (a * d) / (b * c); se_or = np.sqrt(1/a + 1/b + 1/c + 1/d)
    rr_ci = (np.exp(np.log(rr) - 1.96*se_rr), np.exp(np.log(rr) + 1.96*se_rr))
    or_ci = (np.exp(np.log(orr) - 1.96*se_or), np.exp(np.log(orr) + 1.96*se_or))
    table = pd.DataFrame([
        {"Measure": "Risk ratio", "Estimate": round(rr, 3), "95% CI": f"[{rr_ci[0]:.2f}, {rr_ci[1]:.2f}]"},
        {"Measure": "Odds ratio", "Estimate": round(orr, 3), "95% CI": f"[{or_ci[0]:.2f}, {or_ci[1]:.2f}]"}])
    return StatResult(f"RR = {rr:.2f} [{rr_ci[0]:.2f}, {rr_ci[1]:.2f}];  OR = {orr:.2f} [{or_ci[0]:.2f}, {or_ci[1]:.2f}]",
                      table,
                      interpretation="First level of Exposure is treated as 'exposed' and first level of Outcome as "
                                     "the event. RR/OR > 1 (with CI excluding 1) indicates increased risk/odds.",
                      caveats=["Confirm the row/column ordering matches your intended exposed/event definition."])

register(TestSpec("riskratio", "Risk ratio / odds ratio", "6. Categorical",
    "2×2 effect measures with 95% CI.",
    [Column("Exposure", "text", True, "Exposure (2 levels)"), Column("Outcome", "text", True, "Outcome (2 levels)")],
    {"Exposure": ["Exposed","Exposed","Exposed","Unexposed","Unexposed","Unexposed"],
     "Outcome": ["Event","Event","NoEvent","Event","NoEvent","NoEvent"]},
    run_riskratio))


def run_gof(df, params=None):
    from scipy import stats
    cat = _col(df, "Category").astype(str); obs = _num(_col(df, "Observed")); exp = _num(_col(df, "Expected"))
    d = pd.DataFrame({"c": cat, "o": obs, "e": exp}).dropna()
    e_scaled = d["e"] * (d["o"].sum() / d["e"].sum())
    chi, p = stats.chisquare(d["o"], f_exp=e_scaled)
    table = d.rename(columns={"c": "Category", "o": "Observed", "e": "Expected"})
    return StatResult(f"Goodness-of-fit χ²({len(d)-1}) = {chi:.2f}, {fmt_p(p)}", table,
                      interpretation=("Observed counts differ from expected." if p < .05
                                      else "Observed counts fit the expected distribution."))

register(TestSpec("gof", "Chi-square goodness-of-fit", "6. Categorical",
    "Compare observed counts to an expected distribution.",
    [Column("Category", "text", True, "Category"), Column("Observed", "number", True, "Observed count"),
     Column("Expected", "number", True, "Expected count/proportion")],
    {"Category": ["A","B","C","D"], "Observed": [30,25,20,25], "Expected": [25,25,25,25]},
    run_gof))


def _wilson(k, n):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n; z = 1.96
    den = 1 + z**2/n; centre = p + z**2/(2*n)
    half = z * np.sqrt(p*(1-p)/n + z**2/(4*n**2))
    return ((centre-half)/den, (centre+half)/den)


# ===========================================================================
# 7. CORRELATION
# ===========================================================================
def run_correlation(df, params=None):
    from scipy import stats
    x = _num(_col(df, "X")); y = _num(_col(df, "Y"))
    d = pd.DataFrame({"x": x, "y": y}).dropna(); n = len(d)
    pr, pp = stats.pearsonr(d["x"], d["y"])
    sr, sp_ = stats.spearmanr(d["x"], d["y"])
    kt, kp = stats.kendalltau(d["x"], d["y"])
    z = np.arctanh(pr); se = 1/np.sqrt(n-3) if n > 3 else np.nan
    ci = (np.tanh(z-1.96*se), np.tanh(z+1.96*se)) if n > 3 else (np.nan, np.nan)
    table = pd.DataFrame([
        {"Method": "Pearson r", "Coefficient": round(pr, 3), "p": round(pp, 4),
         "95% CI": f"[{ci[0]:.2f}, {ci[1]:.2f}]"},
        {"Method": "Spearman ρ", "Coefficient": round(sr, 3), "p": round(sp_, 4), "95% CI": ""},
        {"Method": "Kendall τ", "Coefficient": round(kt, 3), "p": round(kp, 4), "95% CI": ""}])
    def build(fig, ax, opt):
        ax.scatter(d["x"], d["y"], s=36, color=palette(opt)[0], alpha=0.75, edgecolor="white")
        sl, ic = np.polyfit(d["x"], d["y"], 1)
        xs = np.linspace(d["x"].min(), d["x"].max(), 50)
        ax.plot(xs, sl*xs+ic, color="#d8572a", lw=2)
        ax.set_xlabel("X"); ax.set_ylabel("Y")
    return StatResult(f"Pearson r = {pr:.3f} [{ci[0]:.2f}, {ci[1]:.2f}], {fmt_p(pp)} (n = {n})", table,
                      interpretation=(f"{'A significant' if pp < .05 else 'No significant'} linear correlation "
                                      f"(r = {pr:.2f}). Spearman/Kendall given for non-linear/ranked robustness."),
                      figure_png=_fig_from(build))

register(TestSpec("correlation", "Correlation (Pearson/Spearman/Kendall)", "7. Correlation",
    "All three correlation coefficients with p-values and a scatter+fit.",
    [Column("X", "number", True, "First variable"), Column("Y", "number", True, "Second variable")],
    {"X": [1,2,3,4,5,6,7,8], "Y": [2,4,5,4,6,7,8,9]},
    run_correlation))


def run_corr_matrix(df, params=None):
    mat = df.apply(_num).dropna(axis=1, how="all")
    r = mat.corr().round(3)
    return StatResult("Correlation matrix (Pearson r)", r.reset_index().rename(columns={"index": ""}),
                      interpretation="Pairwise Pearson correlations. Use the Correlation test for p-values and CIs, "
                                     "or the Plot Studio correlation heatmap to visualise.")

register(TestSpec("corr_matrix", "Correlation matrix", "7. Correlation",
    "Pairwise correlations for several numeric variables.",
    [Column("Var1", "number", True, "Numeric variable"), Column("Var2", "number", True, "Numeric variable"),
     Column("Var3", "number", False, "Numeric variable")],
    {"Var1": [1,2,3,4,5], "Var2": [2,4,5,4,6], "Var3": [5,3,2,4,1]},
    run_corr_matrix))


# ===========================================================================
# 8. REGRESSION
# ===========================================================================
def run_linear_reg(df, params=None):
    import statsmodels.api as sm
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    ycol = _col(df, "Y")
    preds = [c for c in df.columns if c.strip().lower() != "y"]
    data = df[[ycol.name] + preds].apply(_num).dropna()
    y = data[ycol.name]; X = sm.add_constant(data[preds])
    m = sm.OLS(y, X).fit()
    ci = m.conf_int()
    coef = pd.DataFrame({"Term": X.columns, "Coef": m.params.round(4).values,
                         "Std err": m.bse.round(4).values, "t": m.tvalues.round(2).values,
                         "p": m.pvalues.round(4).values,
                         "95% CI": [f"[{ci.iloc[i,0]:.3f}, {ci.iloc[i,1]:.3f}]" for i in range(len(X.columns))]})
    vif_note = []
    if len(preds) > 1:
        for i, c in enumerate(preds, start=1):
            try:
                vif_note.append(f"{c}: VIF = {variance_inflation_factor(X.values, i):.2f}")
            except Exception:
                pass
    def build(fig, ax, opt):
        ax.scatter(m.fittedvalues, m.resid, s=30, color=palette(opt)[0], alpha=0.8, edgecolor="white")
        ax.axhline(0, color="#d8572a", lw=1.4, ls="--"); ax.set_xlabel("Fitted"); ax.set_ylabel("Residual")
    return StatResult(
        f"Linear regression: R² = {m.rsquared:.3f} (adj {m.rsquared_adj:.3f}), "
        f"F({int(m.df_model)}, {int(m.df_resid)}) = {m.fvalue:.2f}, {fmt_p(m.f_pvalue)}", coef,
        interpretation="Coefficients with p-values and 95% CI. A significant term (p<.05) predicts the outcome "
                       "holding others constant.",
        assumptions=(["Multicollinearity — " + "; ".join(vif_note) + " (VIF>5 is a concern)."] if vif_note else []),
        figure_png=_fig_from(build))

register(TestSpec("linear_reg", "Linear regression", "8. Regression",
    "Predict a continuous outcome Y from one or more predictors (+ R², CIs, VIF, residuals).",
    [Column("Y", "number", True, "Outcome"), Column("X1", "number", True, "Predictor"),
     Column("X2", "number", False, "Predictor")],
    {"Y": [3,4,5,6,7,8,9,10], "X1": [1,2,3,4,5,6,7,8], "X2": [2,1,4,3,6,5,8,7]},
    run_linear_reg))


def run_logistic_reg(df, params=None):
    import statsmodels.api as sm
    ycol = _col(df, "Y")
    preds = [c for c in df.columns if c.strip().lower() != "y"]
    data = df[[ycol.name] + preds].apply(_num).dropna()
    y = data[ycol.name]; X = sm.add_constant(data[preds])
    m = sm.Logit(y, X).fit(disp=0)
    ci = m.conf_int()
    tab = pd.DataFrame({"Term": X.columns, "Coef": m.params.round(3).values,
                        "Odds ratio": np.exp(m.params).round(3).values,
                        "OR 95% CI": [f"[{np.exp(ci.iloc[i,0]):.2f}, {np.exp(ci.iloc[i,1]):.2f}]" for i in range(len(X.columns))],
                        "p": m.pvalues.round(4).values})
    return StatResult(f"Logistic regression: pseudo R² = {m.prsquared:.3f}, n = {int(m.nobs)}", tab,
                      interpretation="Odds ratios with 95% CI. OR>1 (CI excluding 1) increases the odds of the outcome.",
                      caveats=["Needs a binary 0/1 outcome and enough events per predictor (~10)."])

register(TestSpec("logistic_reg", "Logistic regression", "8. Regression",
    "Model a binary outcome; reports odds ratios with 95% CI.",
    [Column("Y", "int", True, "Binary outcome (0/1)"), Column("X1", "number", True, "Predictor"),
     Column("X2", "number", False, "Predictor")],
    {"Y": [0,1,0,0,1,0,1,1,0,1,1,0,1,0], "X1": [2,3,4,3,6,5,7,6,4,8,7,5,6,3],
     "X2": [1,3,2,4,5,3,6,5,4,7,6,4,5,3]},
    run_logistic_reg))


# ===========================================================================
# 9. RELIABILITY / AGREEMENT
# ===========================================================================
def run_cronbach(df, params=None):
    import pingouin as pg
    items = df.apply(_num).dropna(axis=1, how="all").dropna()
    alpha, ci = pg.cronbach_alpha(data=items)
    table = pd.DataFrame([{"Items": items.shape[1], "n": items.shape[0],
                           "Cronbach's α": round(alpha, 3), "95% CI": f"[{ci[0]:.2f}, {ci[1]:.2f}]"}])
    lab = ("excellent" if alpha >= .9 else "good" if alpha >= .8 else "acceptable" if alpha >= .7
           else "questionable" if alpha >= .6 else "poor")
    return StatResult(f"Cronbach's α = {alpha:.3f} [{ci[0]:.2f}, {ci[1]:.2f}] ({lab})", table,
                      interpretation=f"Internal consistency is {lab}. Each column is a scale item.")

register(TestSpec("cronbach", "Cronbach's alpha", "9. Reliability",
    "Internal consistency of a multi-item scale (one column per item).",
    [Column("Item1", "number", True, "Item score"), Column("Item2", "number", True, "Item score"),
     Column("Item3", "number", True, "Item score"), Column("Item4", "number", False, "Item score")],
    {"Item1": [4,5,3,4,5,2], "Item2": [4,4,3,5,5,2], "Item3": [3,5,2,4,4,1], "Item4": [4,5,3,4,5,2]},
    run_cronbach))


def run_icc(df, params=None):
    import pingouin as pg
    d = pd.DataFrame({"Subject": _col(df, "Subject").astype(str),
                      "Rater": _col(df, "Rater").astype(str), "Value": _num(_col(df, "Value"))}).dropna()
    icc = pg.intraclass_corr(data=d, targets="Subject", raters="Rater", ratings="Value")
    keep = [c for c in ["Type", "Description", "ICC", "F", "pval", "CI95", "CI95%"] if c in icc.columns]
    icc = icc[keep].copy()
    icc["ICC"] = icc["ICC"].round(3)
    pref = icc[icc["Type"].isin(["ICC(A,1)", "ICC2"])]
    row = pref.iloc[0] if len(pref) else icc.iloc[0]
    return StatResult(f"ICC ({row['Type']}, two-way agreement) = {row['ICC']:.3f}", icc,
                      interpretation="ICC < .5 poor, .5–.75 moderate, .75–.9 good, > .9 excellent agreement. "
                                     "ICC(A,1) = absolute agreement, single rater (the usual choice).")

register(TestSpec("icc", "Intraclass correlation (ICC)", "9. Reliability",
    "Agreement between raters on a continuous measure.",
    [Column("Subject", "text", True, "Subject/target"), Column("Rater", "text", True, "Rater"),
     Column("Value", "number", True, "Rating")],
    {"Subject": ["S1","S1","S2","S2","S3","S3","S4","S4"], "Rater": ["R1","R2"]*4,
     "Value": [4,5,3,3,5,4,2,3]},
    run_icc))


def run_kappa(df, params=None):
    from sklearn.metrics import cohen_kappa_score
    a = _col(df, "Rater1").astype(str); b = _col(df, "Rater2").astype(str)
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    k = cohen_kappa_score(d["a"], d["b"])
    kw = cohen_kappa_score(d["a"], d["b"], weights="linear") if d["a"].nunique() > 2 else None
    lab = ("almost perfect" if k >= .81 else "substantial" if k >= .61 else "moderate" if k >= .41
           else "fair" if k >= .21 else "slight")
    table = pd.DataFrame([{"Cohen's κ": round(k, 3), "Weighted κ": round(kw, 3) if kw is not None else "n/a",
                           "Agreement": lab, "n": len(d)}])
    return StatResult(f"Cohen's κ = {k:.3f} ({lab})", table,
                      interpretation=f"Inter-rater agreement is {lab} beyond chance.")

register(TestSpec("kappa", "Cohen's kappa", "9. Reliability",
    "Agreement between two raters on categorical labels.",
    [Column("Rater1", "text", True, "Rater 1 label"), Column("Rater2", "text", True, "Rater 2 label")],
    {"Rater1": ["Yes","No","Yes","Yes","No","No","Yes","No"],
     "Rater2": ["Yes","No","Yes","No","No","No","Yes","Yes"]},
    run_kappa))


# ===========================================================================
# 10. DIAGNOSTIC / CLASSIFICATION
# ===========================================================================
def run_diagnostic(df, params=None):
    actual = _col(df, "Actual").astype(str).str.strip()
    pred = _col(df, "Predicted").astype(str).str.strip()
    d = pd.DataFrame({"a": actual, "p": pred}).dropna()
    labels = sorted(d["a"].unique())
    pos = None
    for cand in ["1", "yes", "pos", "positive", "true", "case", "disease", "present", "abnormal"]:
        for l in labels:
            if str(l).lower() == cand:
                pos = l
    if pos is None:
        pos = labels[-1]
    TP = ((d.a == pos) & (d.p == pos)).sum(); FP = ((d.a != pos) & (d.p == pos)).sum()
    FN = ((d.a == pos) & (d.p != pos)).sum(); TN = ((d.a != pos) & (d.p != pos)).sum()
    def rate(k, n):
        ci = _wilson(k, n)
        return (k/n if n else np.nan), ci
    sens, sci = rate(TP, TP+FN); spec, spci = rate(TN, TN+FP)
    ppv, pci = rate(TP, TP+FP); npv, nci = rate(TN, TN+FN); acc, aci = rate(TP+TN, TP+TN+FP+FN)
    table = pd.DataFrame([
        {"Metric": "Sensitivity", "Value": round(sens, 3), "95% CI": f"[{sci[0]:.2f}, {sci[1]:.2f}]"},
        {"Metric": "Specificity", "Value": round(spec, 3), "95% CI": f"[{spci[0]:.2f}, {spci[1]:.2f}]"},
        {"Metric": "PPV", "Value": round(ppv, 3), "95% CI": f"[{pci[0]:.2f}, {pci[1]:.2f}]"},
        {"Metric": "NPV", "Value": round(npv, 3), "95% CI": f"[{nci[0]:.2f}, {nci[1]:.2f}]"},
        {"Metric": "Accuracy", "Value": round(acc, 3), "95% CI": f"[{aci[0]:.2f}, {aci[1]:.2f}]"}])
    return StatResult(f"Sensitivity {sens:.2f}, Specificity {spec:.2f} (positive class = '{pos}')", table,
                      interpretation=f"Diagnostic accuracy metrics with 95% Wilson CIs. Positive class inferred as '{pos}'.",
                      caveats=[f"Confirm '{pos}' is your intended positive/disease label."])

register(TestSpec("diagnostic", "Diagnostic accuracy", "10. Diagnostic",
    "Sensitivity, specificity, PPV, NPV, accuracy (+95% CI) from actual vs predicted.",
    [Column("Actual", "text", True, "True class"), Column("Predicted", "text", True, "Test/model result")],
    {"Actual": ["Pos","Pos","Pos","Neg","Neg","Neg","Pos","Neg","Pos","Neg"],
     "Predicted": ["Pos","Pos","Neg","Neg","Neg","Pos","Pos","Neg","Pos","Neg"]},
    run_diagnostic))


def run_roc(df, params=None):
    from sklearn.metrics import roc_curve, auc
    y = _num(_col(df, "TrueLabel")); s = _num(_col(df, "Score"))
    d = pd.DataFrame({"y": y, "s": s}).dropna()
    fpr, tpr, thr = roc_curve(d["y"], d["s"]); a = auc(fpr, tpr)
    j = tpr - fpr; k = int(np.argmax(j)); cut = thr[k]
    table = pd.DataFrame([{"AUC": round(a, 3), "Optimal cut-off (Youden)": round(float(cut), 3),
                           "Sensitivity@cut": round(float(tpr[k]), 3),
                           "Specificity@cut": round(float(1-fpr[k]), 3)}])
    def build(fig, ax, opt):
        ax.plot(fpr, tpr, color=palette(opt)[0], lw=2.2, label=f"AUC = {a:.3f}")
        ax.plot([0, 1], [0, 1], color="#c3d0dd", ls="--")
        ax.scatter([fpr[k]], [tpr[k]], color="#d8572a", zorder=5, s=45)
        ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
        ax.legend(frameon=False)
    return StatResult(f"ROC AUC = {a:.3f}; optimal cut-off (Youden) = {float(cut):.3f}", table,
                      interpretation=f"AUC {a:.2f} — {'excellent' if a>=.9 else 'good' if a>=.8 else 'fair' if a>=.7 else 'poor'} "
                                     f"discrimination. Youden cut-off maximises sensitivity+specificity.",
                      figure_png=_fig_from(build))

register(TestSpec("roc_auc", "ROC / AUC (+ cut-off)", "10. Diagnostic",
    "Discrimination of a continuous score, with AUC and optimal threshold.",
    [Column("TrueLabel", "int", True, "Actual class (0/1)"), Column("Score", "number", True, "Predicted score/probability")],
    {"TrueLabel": [0,0,0,1,1,1,0,1,1,0], "Score": [.1,.3,.4,.6,.8,.9,.2,.7,.85,.35]},
    run_roc))


# ===========================================================================
# 11. POWER / SAMPLE SIZE
# ===========================================================================
def run_power(df, params=None):
    from statsmodels.stats.power import TTestIndPower
    p = params or {}
    d = float(p.get("Effect size (Cohen's d)", 0.5)); alpha = float(p.get("Alpha", 0.05))
    power = float(p.get("Desired power", 0.8)); n = float(p.get("Sample size per group (0 = solve)", 0))
    an = TTestIndPower()
    if n and n > 0:
        achieved = an.power(effect_size=d, nobs1=int(n), alpha=alpha, ratio=1)
        table = pd.DataFrame([{"Effect size d": d, "Alpha": alpha, "n per group": int(n),
                               "Achieved power": round(achieved, 3)}])
        head = f"With n = {int(n)}/group and d = {d}, achieved power = {achieved:.2f}"
    else:
        need = an.solve_power(effect_size=d, alpha=alpha, power=power, ratio=1)
        table = pd.DataFrame([{"Effect size d": d, "Alpha": alpha, "Desired power": power,
                               "Required n per group": int(np.ceil(need))}])
        head = f"For d = {d}, α = {alpha}, power = {power}: need {int(np.ceil(need))} per group"
    return StatResult(head, table,
                      interpretation="Two-sample t-test power analysis. Leave n = 0 to solve for sample size, "
                                     "or enter n to get achieved power.")

register(TestSpec("power_ttest", "Power / sample size (t-test)", "11. Power",
    "Plan a two-group study: solve for sample size or achieved power.",
    [], {}, run_power, needs_data=False,
    params=[Param("Effect size (Cohen's d)", "number", 0.5, help="Expected standardized difference"),
            Param("Alpha", "number", 0.05), Param("Desired power", "number", 0.8),
            Param("Sample size per group (0 = solve)", "number", 0.0)]))


# ===========================================================================
# 12. RESAMPLING
# ===========================================================================
def run_bootstrap(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")).dropna().values
    res = stats.bootstrap((v,), np.mean, confidence_level=0.95, n_resamples=5000, method="BCa")
    lo, hi = res.confidence_interval
    table = pd.DataFrame([{"n": len(v), "Mean": round(v.mean(), 3),
                           "Bootstrap 95% CI": f"[{lo:.3f}, {hi:.3f}]",
                           "SE (bootstrap)": round(res.standard_error, 3)}])
    return StatResult(f"Bootstrap mean = {v.mean():.3f}, 95% CI [{lo:.3f}, {hi:.3f}]", table,
                      interpretation="Assumption-free (BCa bootstrap, 5000 resamples) CI for the mean.")

register(TestSpec("bootstrap", "Bootstrap CI (mean)", "12. Resampling",
    "Confidence interval for the mean without distributional assumptions.",
    [Column("Value", "number", True, "Numeric values")],
    {"Value": [12,15,14,18,21,13,16,19,17,20]},
    run_bootstrap))


def run_permutation(df, params=None):
    from scipy import stats
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value"))
    d = pd.DataFrame({"g": g, "v": v}).dropna()
    groups = list(pd.unique(d.g))
    if len(groups) != 2:
        return StatResult("Permutation test needs two groups.", pd.DataFrame({"Groups": [", ".join(groups)]}))
    a = d[d.g == groups[0]]["v"].values; b = d[d.g == groups[1]]["v"].values
    def stat(x, y):
        return np.mean(x) - np.mean(y)
    res = stats.permutation_test((a, b), stat, n_resamples=10000, alternative="two-sided")
    table = pd.DataFrame([{"Group": groups[0], "Mean": round(a.mean(), 3)},
                          {"Group": groups[1], "Mean": round(b.mean(), 3)}])
    return StatResult(f"Permutation test: mean diff = {stat(a,b):.3f}, {fmt_p(res.pvalue)}", table,
                      interpretation=("A significant difference in means (assumption-free)." if res.pvalue < .05
                                      else "No significant difference (assumption-free)."),
                      figure_png=_group_fig(d, "g", "v", "Group comparison"))

register(TestSpec("permutation", "Permutation test", "12. Resampling",
    "Assumption-free comparison of two group means (10,000 permutations).",
    [Column("Group", "text", True, "Two-group label"), Column("Value", "number", True, "Numeric outcome")],
    {"Group": ["A"]*6 + ["B"]*6, "Value": [12,15,14,18,13,16, 20,22,19,24,21,23]},
    run_permutation))


# ===========================================================================
# PHASE B/C — extended tests
# ===========================================================================
def _kappa_mag(k):
    return ("poor" if k < .2 else "fair" if k < .4 else "moderate" if k < .6
            else "substantial" if k < .8 else "almost perfect")

def _xcols(df, prefix="x"):
    return [c for c in df.columns if str(c).strip().lower().startswith(prefix)]

# --- 1. Descriptive: CI for a mean ---
def run_ci_mean(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")).dropna().values; n = len(v)
    m = v.mean(); sd = v.std(ddof=1); se = sd/np.sqrt(n); t = stats.t.ppf(.975, n-1)
    lo, hi = m-t*se, m+t*se
    tab = pd.DataFrame({"n": [n], "Mean": [round(m, 4)], "SD": [round(sd, 4)],
                        "SE": [round(se, 4)], "95% CI": [f"[{lo:.4f}, {hi:.4f}]"]})
    return StatResult(f"Mean = {m:.3f}, 95% CI [{lo:.3f}, {hi:.3f}] (n = {n})", tab,
                      interpretation=f"95% confident the population mean lies between {lo:.3f} and {hi:.3f}.")
register(TestSpec("ci_mean", "Confidence interval (mean)", "1. Descriptive",
    "95% confidence interval for a mean.",
    [Column("Value", "number", True, "Numeric values")],
    {"Value": [12, 14, 13, 15, 11, 16, 12, 14, 13, 15]}, run_ci_mean))

# --- 2. Assumption: KS / Anderson + skew/kurtosis ---
def run_normality_more(df, params=None):
    from scipy import stats
    v = _num(_col(df, "Value")).dropna().values
    ks = stats.kstest((v-v.mean())/v.std(ddof=1), "norm"); ad = stats.anderson(v, "norm")
    sk = stats.skew(v); ku = stats.kurtosis(v); ad_sig = ad.statistic > ad.critical_values[2]
    tab = pd.DataFrame({"Test": ["Kolmogorov–Smirnov", "Anderson–Darling", "Skewness", "Kurtosis (excess)"],
                        "Statistic": [round(ks.statistic, 4), round(ad.statistic, 4), round(sk, 3), round(ku, 3)],
                        "p / crit": [f"{ks.pvalue:.4f}", f"crit(5%)={ad.critical_values[2]:.3f}", "", ""]})
    return StatResult(f"KS p = {ks.pvalue:.3f}; Anderson–Darling A² = {ad.statistic:.3f} "
                      f"({'non-normal' if ad_sig else 'normal'} at 5%)", tab,
                      interpretation=("Distribution deviates from normal." if (ks.pvalue < .05 or ad_sig)
                                      else "Consistent with a normal distribution."),
                      assumptions=[f"Skewness {sk:.2f}, excess kurtosis {ku:.2f} (≈0 = normal-ish)."])
register(TestSpec("normality_more", "Normality (KS / Anderson–Darling)", "2. Assumption checks",
    "K–S and Anderson–Darling normality tests plus skewness/kurtosis.",
    [Column("Value", "number", True, "Numeric values")],
    {"Value": [12, 14, 13, 15, 11, 16, 12, 14, 13, 15, 10, 17]}, run_normality_more))

def run_bartlett(df, params=None):
    from scipy import stats
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value")); d = pd.DataFrame({"g": g, "v": v}).dropna()
    arrays = [d[d.g == gr]["v"].values for gr in pd.unique(d.g)]
    T, p = stats.bartlett(*arrays)
    return StatResult(f"Bartlett's test: T = {T:.2f}, {fmt_p(p)}",
                      pd.DataFrame({"Statistic": [round(T, 3)], "p": [round(p, 4)]}),
                      interpretation=("Variances differ across groups." if p < .05 else "Equal variances."),
                      caveats=["Bartlett is sensitive to non-normality — prefer Levene if data are skewed."])
register(TestSpec("bartlett", "Equal variances (Bartlett)", "2. Assumption checks",
    "Bartlett test for equal variances.",
    [Column("Group", "text", True, "Group"), Column("Value", "number", True, "Outcome")],
    {"Group": ["A"]*5 + ["B"]*5, "Value": [12, 14, 13, 15, 11, 20, 25, 19, 30, 22]}, run_bartlett))

# --- 3. Effect size ---
def run_effect_size(df, params=None):
    import pingouin as pg
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value")); d = pd.DataFrame({"g": g, "v": v}).dropna()
    grs = list(pd.unique(d.g))[:2]; a = d[d.g == grs[0]]["v"].values; b = d[d.g == grs[1]]["v"].values
    dd = cohen_d(a, b); n1, n2 = len(a), len(b); J = 1 - 3/(4*(n1+n2)-9); g_h = dd*J
    ci = pg.compute_esci(stat=dd, nx=n1, ny=n2, eftype="cohen")
    tab = pd.DataFrame({"Metric": ["Cohen's d", "Hedges' g", "95% CI (d)"],
                        "Value": [round(dd, 3), round(g_h, 3), f"[{ci[0]:.3f}, {ci[1]:.3f}]"]})
    return StatResult(f"Cohen's d = {dd:.3f} ({d_magnitude(dd)}), Hedges' g = {g_h:.3f}", tab,
                      interpretation=f"Standardized mean difference between {grs[0]} and {grs[1]} is {d_magnitude(dd)}.")
register(TestSpec("effect_size", "Effect size (Cohen's d / Hedges' g)", "3. Two-group comparison",
    "Standardized mean-difference effect size with 95% CI.",
    [Column("Group", "text", True, "Group (2 levels)"), Column("Value", "number", True, "Outcome")],
    {"Group": ["A"]*6 + ["B"]*6, "Value": [12, 14, 13, 15, 11, 16, 18, 20, 19, 21, 17, 22]}, run_effect_size))

# --- 4. Three+ groups: Games-Howell, two-way, ANCOVA ---
def run_games_howell(df, params=None):
    import pingouin as pg
    g = _col(df, "Group").astype(str); v = _num(_col(df, "Value")); d = pd.DataFrame({"g": g, "v": v}).dropna()
    gh = pg.pairwise_gameshowell(dv="v", between="g", data=d).round(4)
    return StatResult("Games–Howell post-hoc (unequal variances)", gh,
                      interpretation="Pairwise comparisons robust to unequal variances/sample sizes; see 'pval'.")
register(TestSpec("games_howell", "Games–Howell post-hoc", "4. Three+ groups",
    "Post-hoc pairwise comparisons that don't assume equal variances.",
    [Column("Group", "text", True, "Group"), Column("Value", "number", True, "Outcome")],
    {"Group": ["A"]*5 + ["B"]*5 + ["C"]*5, "Value": [12,14,13,15,11, 18,25,19,30,22, 9,11,10,12,8]}, run_games_howell))

def run_anova_two(df, params=None):
    import pingouin as pg
    d = pd.DataFrame({"F1": _col(df, "Factor1").astype(str), "F2": _col(df, "Factor2").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna()
    aov = pg.anova(dv="v", between=["F1", "F2"], data=d, detailed=True).round(4)
    return StatResult("Two-way / factorial ANOVA (main effects + interaction)", aov,
                      interpretation="Check each Source's p-value; the 'F1 * F2' row is the interaction.",
                      figure_png=_group_fig(d.assign(cell=d.F1 + "×" + d.F2), "cell", "v", "Cell means"))
register(TestSpec("anova_two", "Two-way / factorial ANOVA", "4. Three+ groups",
    "Two factors plus their interaction.",
    [Column("Factor1", "text", True, "Factor A"), Column("Factor2", "text", True, "Factor B"),
     Column("Value", "number", True, "Outcome")],
    {"Factor1": ["A", "A", "B", "B"]*3, "Factor2": ["X", "Y", "X", "Y"]*3,
     "Value": [10, 12, 14, 18, 11, 13, 15, 19, 9, 12, 14, 17]}, run_anova_two))

def run_ancova(df, params=None):
    import pingouin as pg
    d = pd.DataFrame({"g": _col(df, "Group").astype(str), "cov": _num(_col(df, "Covariate")),
                      "v": _num(_col(df, "Value"))}).dropna()
    aov = pg.ancova(data=d, dv="v", covar="cov", between="g").round(4)
    return StatResult("ANCOVA (group effect adjusted for covariate)", aov,
                      interpretation="The group row's p-value tests differences after adjusting for the covariate.")
register(TestSpec("ancova", "ANCOVA", "4. Three+ groups", "Group means adjusted for a covariate.",
    [Column("Group", "text", True, "Group"), Column("Covariate", "number", True, "Covariate"),
     Column("Value", "number", True, "Outcome")],
    {"Group": ["A"]*5 + ["B"]*5, "Covariate": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5],
     "Value": [10, 12, 13, 15, 17, 14, 15, 17, 19, 21]}, run_ancova))

# --- 5. Repeated-measures ANOVA ---
def run_rm_anova(df, params=None):
    import pingouin as pg
    d = pd.DataFrame({"s": _col(df, "Subject").astype(str), "c": _col(df, "Condition").astype(str),
                      "v": _num(_col(df, "Value"))}).dropna()
    aov = pg.rm_anova(dv="v", within="c", subject="s", data=d, detailed=True).round(4)
    return StatResult("Repeated-measures ANOVA", aov,
                      interpretation="Tests whether within-subject condition means differ (Condition row).")
register(TestSpec("rm_anova", "Repeated-measures ANOVA", "5. Paired / repeated",
    "≥3 within-subject conditions.",
    [Column("Subject", "text", True, "Subject ID"), Column("Condition", "text", True, "Within condition"),
     Column("Value", "number", True, "Outcome")],
    {"Subject": ["s1", "s2", "s3", "s4"]*3, "Condition": ["T1"]*4 + ["T2"]*4 + ["T3"]*4,
     "Value": [10, 11, 9, 12, 14, 15, 13, 16, 18, 19, 17, 20]}, run_rm_anova))

# --- 6. Categorical: McNemar, Cochran's Q ---
def run_mcnemar(df, params=None):
    from statsmodels.stats.contingency_tables import mcnemar
    d = pd.DataFrame({"a": _col(df, "Before").astype(str), "b": _col(df, "After").astype(str)}).dropna()
    tab = pd.crosstab(d.a, d.b); res = mcnemar(tab.values, exact=True)
    return StatResult(f"McNemar's test: statistic = {res.statistic:.3f}, {fmt_p(res.pvalue)}",
                      tab.reset_index(),
                      interpretation=("Significant change between paired measurements." if res.pvalue < .05
                                      else "No significant change between paired measurements."))
register(TestSpec("mcnemar", "McNemar (paired 2×2)", "6. Categorical", "Paired binary before/after.",
    [Column("Before", "text", True, "Before (e.g. Pos/Neg)"), Column("After", "text", True, "After")],
    {"Before": ["Pos", "Pos", "Neg", "Neg", "Pos", "Neg", "Pos", "Neg"],
     "After": ["Pos", "Neg", "Pos", "Neg", "Neg", "Neg", "Pos", "Pos"]}, run_mcnemar))

def run_cochran_q(df, params=None):
    from statsmodels.stats.contingency_tables import cochrans_q
    d = pd.DataFrame({"s": _col(df, "Subject").astype(str), "c": _col(df, "Condition").astype(str),
                      "o": _num(_col(df, "Outcome"))}).dropna()
    wide = d.pivot_table(index="s", columns="c", values="o", aggfunc="first")
    res = cochrans_q(wide.values)
    return StatResult(f"Cochran's Q = {res.statistic:.3f}, {fmt_p(res.pvalue)}", wide.reset_index(),
                      interpretation=("Proportion of the binary outcome differs across conditions." if res.pvalue < .05
                                      else "No difference across conditions."))
register(TestSpec("cochran_q", "Cochran's Q", "6. Categorical",
    "Paired binary outcome across ≥3 conditions.",
    [Column("Subject", "text", True, "Subject"), Column("Condition", "text", True, "Condition"),
     Column("Outcome", "int", True, "0/1 outcome")],
    {"Subject": ["s1", "s2", "s3", "s4"]*3, "Condition": ["C1"]*4 + ["C2"]*4 + ["C3"]*4,
     "Outcome": [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0]}, run_cochran_q))

# --- 7. Correlation: point-biserial, partial ---
def run_pointbiserial(df, params=None):
    from scipy import stats
    d = pd.DataFrame({"b": _num(_col(df, "Binary")), "v": _num(_col(df, "Value"))}).dropna()
    r, p = stats.pointbiserialr(d.b, d.v)
    return StatResult(f"Point-biserial r = {r:.3f}, {fmt_p(p)}",
                      pd.DataFrame({"r_pb": [round(r, 3)], "p": [round(p, 4)]}),
                      interpretation=f"Binary–continuous association is {'significant' if p < .05 else 'not significant'} (r = {r:.2f}).")
register(TestSpec("pointbiserial", "Point-biserial correlation", "7. Correlation",
    "Correlation between a binary and a continuous variable.",
    [Column("Binary", "int", True, "0/1"), Column("Value", "number", True, "Continuous")],
    {"Binary": [0, 0, 0, 1, 1, 1, 0, 1, 0, 1], "Value": [10, 12, 11, 18, 20, 19, 13, 17, 12, 21]}, run_pointbiserial))

def run_partial_corr(df, params=None):
    import pingouin as pg
    d = pd.DataFrame({"X": _num(_col(df, "X")), "Y": _num(_col(df, "Y")),
                      "Covariate": _num(_col(df, "Covariate"))}).dropna()
    pc = pg.partial_corr(data=d, x="X", y="Y", covar="Covariate").round(4)
    r = pc["r"].iloc[0]; p = pc["p-val"].iloc[0] if "p-val" in pc.columns else pc.iloc[0, -1]
    return StatResult(f"Partial correlation r = {r:.3f}, {fmt_p(p)} (controlling for covariate)", pc,
                      interpretation=f"X–Y association after removing the covariate is {'significant' if p < .05 else 'not significant'}.")
register(TestSpec("partial_corr", "Partial correlation", "7. Correlation",
    "Correlation between X and Y controlling for a covariate.",
    [Column("X", "number", True, "X"), Column("Y", "number", True, "Y"),
     Column("Covariate", "number", True, "Control variable")],
    {"X": [1, 2, 3, 4, 5, 6, 7, 8], "Y": [2, 4, 5, 4, 5, 7, 8, 9], "Covariate": [1, 1, 2, 2, 3, 3, 4, 4]},
    run_partial_corr))

# --- 8. Regression: diagnostics, Poisson ---
def run_reg_diagnostics(df, params=None):
    import statsmodels.api as sm
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    from statsmodels.stats.stattools import durbin_watson
    xc = _xcols(df); X = df[xc].apply(_num)
    d = pd.concat([_num(_col(df, "Y")).rename("Y"), X], axis=1).dropna()
    Xd = sm.add_constant(d[xc]); model = sm.OLS(d["Y"], Xd).fit()
    vif = pd.DataFrame({"Term": xc, "VIF": [round(variance_inflation_factor(Xd.values, i+1), 3) for i in range(len(xc))]})
    return StatResult(f"R² = {model.rsquared:.3f}, adj R² = {model.rsquared_adj:.3f}, F p = {model.f_pvalue:.3g}", vif,
                      interpretation=f"Model explains {model.rsquared:.0%} of variance. VIF > 5–10 flags multicollinearity.",
                      assumptions=[f"Durbin–Watson = {durbin_watson(model.resid):.2f} (≈2 = no autocorrelation)."])
register(TestSpec("reg_diagnostics", "Regression diagnostics (R²/VIF)", "8. Regression",
    "Model fit + multicollinearity (VIF) for a multiple regression.",
    [Column("Y", "number", True, "Outcome"), Column("X1", "number", True, "Predictor 1"),
     Column("X2", "number", False, "Predictor 2")],
    {"Y": [10, 12, 13, 16, 18, 20], "X1": [1, 2, 3, 4, 5, 6], "X2": [2, 1, 4, 3, 6, 5]}, run_reg_diagnostics))

def run_poisson(df, params=None):
    import statsmodels.api as sm
    xc = _xcols(df); X = df[xc].apply(_num)
    d = pd.concat([_num(_col(df, "Count")).rename("Count"), X], axis=1).dropna()
    Xd = sm.add_constant(d[xc]); model = sm.GLM(d["Count"], Xd, family=sm.families.Poisson()).fit()
    tab = pd.DataFrame({"Term": ["const"] + xc, "Coef": model.params.round(4).values,
                        "IRR": np.exp(model.params).round(3).values, "p": model.pvalues.round(4).values})
    return StatResult(f"Poisson regression (deviance = {model.deviance:.1f})", tab,
                      interpretation="IRR = incidence-rate ratio (exp of coef). p<.05 = significant predictor.",
                      caveats=["If variance ≫ mean (overdispersion), use negative binomial instead."])
register(TestSpec("poisson", "Poisson regression", "8. Regression", "Count-outcome regression (IRR).",
    [Column("Count", "int", True, "Count outcome"), Column("X1", "number", True, "Predictor")],
    {"Count": [1, 2, 1, 3, 4, 6, 5, 8], "X1": [1, 2, 3, 4, 5, 6, 7, 8]}, run_poisson))

# --- 9. Reliability: Fleiss' kappa ---
def run_fleiss(df, params=None):
    from statsmodels.stats.inter_rater import fleiss_kappa, aggregate_raters
    num = df.apply(_num).dropna(axis=1, how="all"); mat = num.dropna().astype(int).values
    agg, cats = aggregate_raters(mat); kappa = fleiss_kappa(agg)
    return StatResult(f"Fleiss' κ = {kappa:.3f} ({_kappa_mag(kappa)})",
                      pd.DataFrame({"Fleiss kappa": [round(kappa, 3)], "Subjects": [mat.shape[0]], "Raters": [mat.shape[1]]}),
                      interpretation="Agreement among ≥3 raters: <.2 poor, .2–.4 fair, .4–.6 moderate, .6–.8 substantial, >.8 almost perfect.")
register(TestSpec("fleiss", "Fleiss' kappa", "9. Reliability",
    "Agreement among ≥3 raters (each column = a rater, values = category codes).",
    [Column("Rater1", "int", True, "Rater 1 category"), Column("Rater2", "int", True, "Rater 2"),
     Column("Rater3", "int", True, "Rater 3")],
    {"Rater1": [1, 2, 3, 1, 2], "Rater2": [1, 2, 3, 1, 3], "Rater3": [1, 2, 2, 1, 2]}, run_fleiss))

# --- 11. Power: ANOVA / proportions / correlation ---
def run_power_anova(df, params=None):
    from statsmodels.stats.power import FTestAnovaPower
    p = params or {}; k = int(p.get("groups", 3) or 3); f = float(p.get("effect_f", 0.25) or 0.25)
    alpha = float(p.get("alpha", .05) or .05); power = float(p.get("power", .8) or .8)
    n = FTestAnovaPower().solve_power(effect_size=f, k_groups=k, alpha=alpha, power=power)
    nper = int(np.ceil(n))
    return StatResult(f"One-way ANOVA: need n ≈ {nper} per group ({nper*k} total)",
                      pd.DataFrame({"Groups": [k], "Effect f": [f], "Alpha": [alpha], "Power": [power],
                                    "n per group": [nper], "Total N": [nper*k]}),
                      interpretation="Sample size to detect effect size f (0.1 small, 0.25 medium, 0.4 large).")
register(TestSpec("power_anova", "Power / sample size (ANOVA)", "11. Power",
    "Sample size for a one-way ANOVA.", [], {}, run_power_anova, needs_data=False,
    params=[Param("groups", "int", 3, help="Number of groups"), Param("effect_f", "number", 0.25, help="Cohen's f"),
            Param("alpha", "number", 0.05), Param("power", "number", 0.8)]))

def run_power_prop(df, params=None):
    from statsmodels.stats.power import NormalIndPower
    from statsmodels.stats.proportion import proportion_effectsize
    p = params or {}; p1 = float(p.get("p1", .5) or .5); p2 = float(p.get("p2", .65) or .65)
    alpha = float(p.get("alpha", .05) or .05); power = float(p.get("power", .8) or .8)
    es = proportion_effectsize(p1, p2)
    n = NormalIndPower().solve_power(effect_size=abs(es), alpha=alpha, power=power, ratio=1, alternative="two-sided")
    nper = int(np.ceil(n))
    return StatResult(f"Two proportions: need n ≈ {nper} per group",
                      pd.DataFrame({"p1": [p1], "p2": [p2], "Alpha": [alpha], "Power": [power], "n per group": [nper]}),
                      interpretation="Sample size to detect a difference between two proportions.")
register(TestSpec("power_prop", "Power / sample size (proportions)", "11. Power",
    "Sample size to compare two proportions.", [], {}, run_power_prop, needs_data=False,
    params=[Param("p1", "number", 0.5, help="Proportion group 1"), Param("p2", "number", 0.65, help="Proportion group 2"),
            Param("alpha", "number", 0.05), Param("power", "number", 0.8)]))

def run_power_corr(df, params=None):
    import pingouin as pg
    p = params or {}; r = float(p.get("r", 0.3) or 0.3); alpha = float(p.get("alpha", .05) or .05)
    power = float(p.get("power", .8) or .8)
    n = pg.power_corr(r=r, power=power, alpha=alpha); nn = int(np.ceil(n))
    return StatResult(f"Correlation: need n ≈ {nn}",
                      pd.DataFrame({"r": [r], "Alpha": [alpha], "Power": [power], "n": [nn]}),
                      interpretation="Sample size to detect a correlation of r.")
register(TestSpec("power_corr", "Power / sample size (correlation)", "11. Power",
    "Sample size to detect a correlation.", [], {}, run_power_corr, needs_data=False,
    params=[Param("r", "number", 0.3, help="Expected correlation"), Param("alpha", "number", 0.05),
            Param("power", "number", 0.8)]))

# --- 13. Survival: Kaplan–Meier (+ log-rank), Cox ---
def run_km(df, params=None):
    from lifelines import KaplanMeierFitter
    from lifelines.statistics import multivariate_logrank_test
    gc = _col(df, "Group")
    d = pd.DataFrame({"t": _num(_col(df, "Time")), "e": _num(_col(df, "Event"))})
    if gc is not None:
        d["g"] = gc.astype(str)
    d = d.dropna()
    has_g = "g" in d.columns and d["g"].nunique() > 1
    def build(fig, ax, opt):
        kmf = KaplanMeierFitter()
        if has_g:
            for gr in pd.unique(d.g):
                m = d.g == gr; kmf.fit(d.t[m], d.e[m], label=str(gr)); kmf.plot_survival_function(ax=ax, ci_show=True)
        else:
            kmf.fit(d.t, d.e, label="All"); kmf.plot_survival_function(ax=ax)
        ax.set_xlabel("Time"); ax.set_ylabel("Survival probability"); ax.set_ylim(0, 1.02)
        ax.set_title("Kaplan–Meier", fontsize=12, fontweight="bold", color="#12283b")
    png = _fig_from(build, PlotOptions(figsize=(7, 4.6), dpi=160))
    kmf = KaplanMeierFitter(); rows = []
    if has_g:
        for gr in pd.unique(d.g):
            m = d.g == gr; kmf.fit(d.t[m], d.e[m])
            rows.append({"Group": gr, "n": int(m.sum()), "Events": int(d.e[m].sum()),
                         "Median survival": kmf.median_survival_time_})
        lr = multivariate_logrank_test(d.t, d.g, d.e)
        head = f"Log-rank χ² = {lr.test_statistic:.2f}, {fmt_p(lr.p_value)}"
        interp = ("Survival differs between groups." if lr.p_value < .05 else "No significant survival difference.")
    else:
        kmf.fit(d.t, d.e); rows.append({"Group": "All", "n": len(d), "Events": int(d.e.sum()),
                                        "Median survival": kmf.median_survival_time_})
        head = "Kaplan–Meier survival estimate"; interp = "Median survival shown in the table."
    return StatResult(head, pd.DataFrame(rows), interpretation=interp, figure_png=png)
register(TestSpec("kaplan_meier", "Kaplan–Meier (+ log-rank)", "13. Survival",
    "Time-to-event survival curves; add a Group column for a log-rank comparison.",
    [Column("Time", "number", True, "Follow-up time"), Column("Event", "int", True, "1=event, 0=censored"),
     Column("Group", "text", False, "Group (optional)")],
    {"Time": [5, 6, 6, 8, 10, 12, 3, 4, 7, 9, 11, 14], "Event": [1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1],
     "Group": ["A"]*6 + ["B"]*6}, run_km))

def run_cox(df, params=None):
    from lifelines import CoxPHFitter
    xc = _xcols(df); d = df[["Time", "Event"] + xc].copy()
    d["Time"] = _num(_col(df, "Time")); d["Event"] = _num(_col(df, "Event"))
    for c in xc:
        d[c] = _num(df[c])
    d = d.dropna()
    cph = CoxPHFitter().fit(d, duration_col="Time", event_col="Event")
    s = cph.summary
    tab = pd.DataFrame({"Term": s.index, "HR": s["exp(coef)"].round(3).values,
                        "95% CI": [f"[{np.exp(lo):.2f}, {np.exp(hi):.2f}]"
                                   for lo, hi in zip(s["coef lower 95%"], s["coef upper 95%"])],
                        "p": s["p"].round(4).values})
    return StatResult(f"Cox PH: concordance = {cph.concordance_index_:.3f}", tab,
                      interpretation="HR>1 = higher hazard (worse survival). p<.05 = significant predictor.",
                      caveats=["Assumes proportional hazards — verify (e.g. lifelines check_assumptions)."])
register(TestSpec("cox_ph", "Cox proportional hazards (+HR)", "13. Survival",
    "Multivariable survival regression → hazard ratios.",
    [Column("Time", "number", True, "Follow-up time"), Column("Event", "int", True, "1=event, 0=censored"),
     Column("X1", "number", True, "Predictor 1"), Column("X2", "number", False, "Predictor 2")],
    {"Time": [5, 6, 6, 8, 10, 12, 3, 4, 7, 9, 11, 14], "Event": [1, 1, 0, 1, 0, 1, 1, 1, 0, 1, 0, 1],
     "X1": [1, 2, 1, 3, 2, 4, 1, 2, 3, 2, 4, 5], "X2": [50, 60, 55, 65, 70, 62, 48, 52, 58, 63, 66, 70]}, run_cox))

# --- 14. Multivariate: PCA, k-means, LDA, MANOVA ---
def run_pca(df, params=None):
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    xc = _xcols(df) or [c for c in df.columns if _num(df[c]).notna().any()]
    X = df[xc].apply(_num).dropna(); Xs = StandardScaler().fit_transform(X)
    pca = PCA(n_components=min(len(xc), 5)).fit(Xs); evr = pca.explained_variance_ratio_
    tab = pd.DataFrame({"Component": [f"PC{i+1}" for i in range(len(evr))],
                        "Explained variance %": (evr*100).round(2), "Cumulative %": (np.cumsum(evr)*100).round(2)})
    png = None
    if len(evr) >= 2:
        sc = pca.transform(Xs)
        def build(fig, ax, opt):
            ax.scatter(sc[:, 0], sc[:, 1], s=42, color=palette(opt)[0], alpha=0.75, edgecolor="white")
            ax.set_xlabel(f"PC1 ({evr[0]*100:.1f}%)"); ax.set_ylabel(f"PC2 ({evr[1]*100:.1f}%)")
            ax.set_title("PCA", fontsize=12, fontweight="bold", color="#12283b")
        png = _fig_from(build)
    return StatResult(f"PCA: PC1 explains {evr[0]*100:.1f}%" + (f", PC2 {evr[1]*100:.1f}%" if len(evr) > 1 else ""),
                      tab, interpretation="Components ordered by variance explained; use cumulative % to choose how many to keep.",
                      figure_png=png)
register(TestSpec("pca", "PCA", "14. Multivariate", "Principal component analysis of several numeric variables.",
    [Column("X1", "number", True, "Variable 1"), Column("X2", "number", True, "Variable 2"),
     Column("X3", "number", False, "Variable 3")],
    {"X1": [1, 2, 3, 4, 5, 6], "X2": [2, 1, 4, 3, 6, 5], "X3": [5, 3, 6, 2, 8, 4]}, run_pca))

def run_kmeans(df, params=None):
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score
    k = int((params or {}).get("k", 3) or 3)
    xc = _xcols(df) or [c for c in df.columns if _num(df[c]).notna().any()]
    X = df[xc].apply(_num).dropna().reset_index(drop=True); Xs = StandardScaler().fit_transform(X)
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Xs)
    sil = silhouette_score(Xs, km.labels_) if (k > 1 and len(X) > k) else np.nan
    counts = pd.Series(km.labels_).value_counts().sort_index()
    tab = pd.DataFrame({"Cluster": counts.index, "n": counts.values})
    png = None
    if X.shape[1] >= 2:
        c0, c1 = X.columns[0], X.columns[1]
        def build(fig, ax, opt):
            for c in sorted(set(km.labels_)):
                m = km.labels_ == c
                ax.scatter(X.loc[m, c0], X.loc[m, c1], s=42, color=palette(opt)[c % 8], alpha=0.75,
                           edgecolor="white", label=f"C{c}")
            ax.set_xlabel(str(c0)); ax.set_ylabel(str(c1)); ax.legend(fontsize=8)
            ax.set_title("k-means clusters", fontsize=12, fontweight="bold", color="#12283b")
        png = _fig_from(build)
    head = f"k-means (k={k}): silhouette = {sil:.3f}" if not np.isnan(sil) else f"k-means (k={k})"
    return StatResult(head, tab, interpretation="Higher silhouette (−1..1) = better-separated clusters.",
                      figure_png=png)
register(TestSpec("kmeans", "k-means clustering", "14. Multivariate", "Partition cases into k clusters.",
    [Column("X1", "number", True, "Variable 1"), Column("X2", "number", True, "Variable 2")],
    {"X1": [1, 1.2, 5, 5.2, 9, 9.1], "X2": [1, 0.9, 5, 5.1, 9, 8.9]}, run_kmeans,
    params=[Param("k", "int", 3, help="Number of clusters")]))

def run_lda(df, params=None):
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    xc = _xcols(df); X = df[xc].apply(_num)
    d = pd.concat([_col(df, "Group").astype(str).rename("g"), X], axis=1).dropna()
    lda = LinearDiscriminantAnalysis().fit(d[xc], d["g"]); acc = lda.score(d[xc], d["g"])
    tab = pd.DataFrame({"Group": lda.classes_, "n": [int((d.g == c).sum()) for c in lda.classes_]})
    return StatResult(f"LDA: resubstitution accuracy = {acc:.1%}", tab,
                      interpretation="Linear discriminant analysis classifies cases into the known groups.",
                      caveats=["Accuracy is on training data — validate on held-out data for honest performance."])
register(TestSpec("lda", "Linear discriminant analysis", "14. Multivariate", "Classify cases into known groups.",
    [Column("Group", "text", True, "Known group"), Column("X1", "number", True, "Predictor 1"),
     Column("X2", "number", False, "Predictor 2")],
    {"Group": ["A", "A", "A", "B", "B", "B"], "X1": [1, 2, 1.5, 5, 6, 5.5], "X2": [2, 1, 2.5, 6, 5, 6.5]}, run_lda))

def run_manova(df, params=None):
    from statsmodels.multivariate.manova import MANOVA
    yc = [c for c in df.columns if str(c).strip().lower().startswith("y")]
    d = df[["Group"] + yc].copy(); d["Group"] = _col(df, "Group").astype(str)
    for c in yc:
        d[c] = _num(df[c])
    d = d.dropna()
    m = MANOVA.from_formula(" + ".join(yc) + " ~ Group", data=d); r = m.mv_test()
    stat = r.results["Group"]["stat"].round(4)
    wp = stat.loc["Wilks' lambda", "Pr > F"]
    return StatResult(f"MANOVA (Wilks' λ): {fmt_p(wp)}", stat.reset_index(),
                      interpretation=("Groups differ on the combined outcomes." if wp < .05
                                      else "No multivariate group difference."))
register(TestSpec("manova", "MANOVA", "14. Multivariate", "Compare groups on several outcomes jointly.",
    [Column("Group", "text", True, "Group"), Column("Y1", "number", True, "Outcome 1"),
     Column("Y2", "number", True, "Outcome 2")],
    {"Group": ["A", "A", "A", "A", "A", "B", "B", "B", "B", "B"],
     "Y1": [10, 12, 11, 13, 9, 18, 20, 19, 21, 17], "Y2": [5, 4, 6, 5, 7, 9, 11, 8, 10, 12]},
    run_manova))
