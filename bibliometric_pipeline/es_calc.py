"""
es_calc.py
==========
Effect-size calculator / data-prep converters for meta-analysis. Closes the
"getting the data in" gap: turn oddly-reported study data into the standard
inputs a meta-analysis needs.

Two families:
  • Effect + SE from a reported effect (95% CI → SE, p-value → SE). The output
    has Study, Effect, SE, LowerCI, UpperCI → drop straight into the
    Generic (effect + CI) meta-analysis template and pool.
  • Mean + SD from medians (Wan 2014 SD + Luo 2018 mean estimators) for the
    three common scenarios → drop into the MD / SMD template.

All pure numpy/scipy; no new dependency.
"""
from __future__ import annotations

import io
import numpy as np
import pandas as pd
from scipy import stats

from .plot_studio import _col, _num

Z = 1.959963985


# --------------------------------------------------------------------------- #
# conversion registry
# --------------------------------------------------------------------------- #
class Conv:
    def __init__(self, cid, name, columns, note, poolable, example):
        self.id = cid; self.name = name; self.columns = columns
        self.note = note; self.poolable = poolable; self.example = example


CONVERSIONS = {}
def _reg(c): CONVERSIONS[c.id] = c; return c


_reg(Conv(
    "ci_to_se", "95% CI → standard error",
    [("Study", "Study label"), ("Effect", "Point estimate (OR/RR/HR/MD…)"),
     ("LowerCI", "Lower 95% CI"), ("UpperCI", "Upper 95% CI")],
    "Set 'Ratio measure?' if the effect is an OR/RR/HR (SE is computed on the log scale). "
    "Output has Effect + SE + CI — use the Generic (effect + CI) meta-analysis template to pool.",
    True,
    {"Study": ["Trial A", "Trial B", "Trial C"], "Effect": [0.75, 0.62, 0.88],
     "LowerCI": [0.55, 0.40, 0.70], "UpperCI": [1.02, 0.96, 1.10]}))

_reg(Conv(
    "p_to_se", "p-value → standard error",
    [("Study", "Study label"), ("Effect", "Point estimate"), ("P", "Two-sided p-value")],
    "Set 'Ratio measure?' for OR/RR/HR (works on the log scale). SE = |effect| / z(1−p/2). "
    "Output has Effect + SE + CI — pool with the Generic template.",
    True,
    {"Study": ["Trial A", "Trial B", "Trial C"], "Effect": [0.40, 0.55, 0.30],
     "P": [0.02, 0.08, 0.001]}))

_reg(Conv(
    "median_iqr", "Median + IQR → mean + SD",
    [("Study", "Study label"), ("N", "Sample size"), ("Q1", "Lower quartile"),
     ("Median", "Median"), ("Q3", "Upper quartile")],
    "Luo (2018) mean + Wan (2014) SD, scenario C2. Output has Mean + SD + N — "
    "use these in the Mean difference / SMD template (one arm per sheet).",
    False,
    {"Study": ["Trial A", "Trial B"], "N": [50, 42], "Q1": [12, 9],
     "Median": [18, 15], "Q3": [25, 22]}))

_reg(Conv(
    "median_range", "Median + range → mean + SD",
    [("Study", "Study label"), ("N", "Sample size"), ("Min", "Minimum"),
     ("Median", "Median"), ("Max", "Maximum")],
    "Luo (2018) mean + Wan (2014) SD, scenario C1. Output has Mean + SD + N for the MD / SMD template.",
    False,
    {"Study": ["Trial A", "Trial B"], "N": [50, 42], "Min": [4, 3],
     "Median": [18, 15], "Max": [40, 33]}))

_reg(Conv(
    "median_full", "Median + IQR + range → mean + SD",
    [("Study", "Study label"), ("N", "Sample size"), ("Min", "Minimum"), ("Q1", "Lower quartile"),
     ("Median", "Median"), ("Q3", "Upper quartile"), ("Max", "Maximum")],
    "Luo (2018) mean + Wan (2014) SD, scenario C3 (most precise). Output has Mean + SD + N.",
    False,
    {"Study": ["Trial A", "Trial B"], "N": [50, 42], "Min": [4, 3], "Q1": [12, 9],
     "Median": [18, 15], "Q3": [25, 22], "Max": [40, 33]}))


def template_bytes(conv: "Conv") -> bytes:
    data = pd.DataFrame(conv.example)
    info = pd.DataFrame([(c, h) for c, h in conv.columns], columns=["Column", "What to enter"])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        data.to_excel(xl, sheet_name="Data", index=False)
        info.to_excel(xl, sheet_name="Instructions", index=False)
    return buf.getvalue()


def validate(conv: "Conv", df: pd.DataFrame) -> "list[str]":
    have = {c.strip().lower() for c in df.columns}
    miss = [c for c, _ in conv.columns if c.strip().lower() not in have]
    problems = []
    if miss:
        problems.append("Missing required columns: " + ", ".join(miss))
    if df.dropna(how="all").empty:
        problems.append("The Data sheet is empty.")
    return problems


# --------------------------------------------------------------------------- #
# estimators
# --------------------------------------------------------------------------- #
def _xi(n):   # Wan 2014 ξ(n) for range-based SD
    return 2*stats.norm.ppf((n - 0.375)/(n + 0.25))

def _eta(n):  # Wan 2014 η(n) for IQR-based SD
    return 2*stats.norm.ppf((0.75*n - 0.125)/(n + 0.25))


def compute(conv_id, df, ratio=False):
    """Return (result_df, note, poolable). result_df is clean and ready to
    drop into the matching meta-analysis template."""
    conv = CONVERSIONS[conv_id]
    lab = _col(df, "Study")
    lab = lab.astype(str).values if lab is not None else np.arange(1, len(df)+1).astype(str)

    if conv_id == "ci_to_se":
        e = _num(_col(df, "Effect")).values.astype(float)
        lo = _num(_col(df, "LowerCI")).values.astype(float)
        hi = _num(_col(df, "UpperCI")).values.astype(float)
        if ratio:
            se = (np.log(hi) - np.log(lo))/(2*Z)
        else:
            se = (hi - lo)/(2*Z)
        out = pd.DataFrame({"Study": lab, "Effect": np.round(e, 4), "SE": np.round(se, 4),
                            "LowerCI": np.round(lo, 4), "UpperCI": np.round(hi, 4)})
        return out, "SE computed from the reported 95% CI." + (" (log scale — ratio measure)" if ratio else ""), True

    if conv_id == "p_to_se":
        e = _num(_col(df, "Effect")).values.astype(float)
        p = _num(_col(df, "P")).values.astype(float)
        p = np.clip(p, 1e-12, 0.999999)
        z = stats.norm.ppf(1 - p/2)
        base = np.log(e) if ratio else e
        se = np.abs(base)/z
        lo = np.exp(base - Z*se) if ratio else base - Z*se
        hi = np.exp(base + Z*se) if ratio else base + Z*se
        out = pd.DataFrame({"Study": lab, "Effect": np.round(e, 4), "SE": np.round(se, 4),
                            "LowerCI": np.round(lo, 4), "UpperCI": np.round(hi, 4)})
        return out, "SE = |effect| / z(1−p/2)." + (" (log scale — ratio measure)" if ratio else ""), True

    # median-based → mean + SD
    n = _num(_col(df, "N")).values.astype(float)
    m = _num(_col(df, "Median")).values.astype(float)
    if conv_id == "median_iqr":
        q1 = _num(_col(df, "Q1")).values.astype(float); q3 = _num(_col(df, "Q3")).values.astype(float)
        mean = (q1 + m + q3)/3.0
        sd = (q3 - q1)/_eta(n)
        scen = "C2 (median + IQR)"
    elif conv_id == "median_range":
        a = _num(_col(df, "Min")).values.astype(float); b = _num(_col(df, "Max")).values.astype(float)
        mean = (a + 2*m + b)/4.0 + (a - 2*m + b)/(4.0*n)
        sd = (b - a)/_xi(n)
        scen = "C1 (median + range)"
    else:  # median_full
        a = _num(_col(df, "Min")).values.astype(float); b = _num(_col(df, "Max")).values.astype(float)
        q1 = _num(_col(df, "Q1")).values.astype(float); q3 = _num(_col(df, "Q3")).values.astype(float)
        mean = (a + 2*q1 + 2*m + 2*q3 + b)/8.0
        sd = 0.5*(b - a)/_xi(n) + 0.5*(q3 - q1)/_eta(n)
        scen = "C3 (median + IQR + range)"
    out = pd.DataFrame({"Study": lab, "N": n.astype(int),
                        "Mean": np.round(mean, 4), "SD": np.round(sd, 4)})
    return out, f"Mean (Luo 2018) + SD (Wan 2014), scenario {scen}.", False
