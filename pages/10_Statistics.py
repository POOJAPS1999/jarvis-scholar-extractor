"""
Statistics (No-Code)
====================
Pick a statistical test, download its Excel template, fill your data, upload,
and get an APA-style result with assumption checks, effect sizes, a plain-
language verdict and (where useful) a figure — no coding, no biostatistician.
Every test is defined in bibliometric_pipeline.stats_lab (one engine).
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline import stats_lab as SL
from bibliometric_pipeline import r_export as RX

st.set_page_config(page_title="Jarvis Scholar - Statistics", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Statistics")
st.caption("Pick a test → download its Excel template → upload your data → get an APA-style result with "
           "assumption checks, effect sizes and a plain-language verdict. No coding, no biostatistician.")

cats = SL.by_category()
cat_names = sorted(cats.keys(), key=lambda s: int(s.split(".")[0]))

# Apply a wizard jump BEFORE the picker widgets are instantiated this run.
if st.session_state.pop("_apply_wiz", False):
    st.session_state["sl_cat"] = st.session_state.get("_wiz_cat")
    st.session_state["sl_test"] = st.session_state.get("_wiz_test")
    st.session_state.pop("sl_res", None)

# ---- "Which test should I use?" wizard --------------------------------------
with st.expander("🧭 Not sure which test? Answer a few questions", expanded=False):
    rec_id = why = alt_id = None
    goal = st.selectbox("What do you want to do?", [
        "— select —",
        "Compare groups or conditions",
        "Measure a relationship between variables",
        "Predict or model an outcome",
        "Assess agreement or reliability",
        "Evaluate a diagnostic test",
        "Describe or summarise data",
        "Check a statistical assumption",
        "Plan sample size / power",
    ], key="wz_goal")

    if goal == "Compare groups or conditions":
        otype = st.selectbox("What is the outcome?",
                             ["Numeric (score / measurement)", "Categorical (yes/no, category)"], key="wz_ot")
        if otype.startswith("Numeric"):
            design = st.selectbox("Study design",
                                  ["Independent groups", "Paired / repeated (same subjects)",
                                   "One group vs a fixed value"], key="wz_des")
            if design == "Independent groups":
                ng = st.selectbox("How many groups?", ["2 groups", "3 or more groups"], key="wz_ng")
                norm = st.selectbox("Is the outcome roughly normal (or n fairly large)?",
                                    ["Yes / not sure", "No (skewed, small n, or ordinal)"], key="wz_nm")
                if ng == "2 groups":
                    if norm.startswith("Yes"):
                        rec_id, why, alt_id = "ttest_ind", "two independent groups, numeric and ~normal → independent t-test (auto-switches to Welch if variances differ).", "mann_whitney"
                    else:
                        rec_id, why, alt_id = "mann_whitney", "two independent groups, non-normal/ordinal → Mann–Whitney U.", "ttest_ind"
                else:
                    if norm.startswith("Yes"):
                        rec_id, why, alt_id = "anova_oneway", "3+ independent groups, ~normal → one-way ANOVA + Tukey.", "welch_anova"
                    else:
                        rec_id, why, alt_id = "kruskal", "3+ independent groups, non-normal → Kruskal–Wallis + Dunn.", "anova_oneway"
            elif design.startswith("Paired"):
                nc = st.selectbox("How many conditions?", ["2 conditions", "3 or more conditions"], key="wz_nc")
                if nc == "2 conditions":
                    norm = st.selectbox("Roughly normal differences?", ["Yes / not sure", "No"], key="wz_nm2")
                    if norm.startswith("Yes"):
                        rec_id, why, alt_id = "ttest_paired", "two related measurements, ~normal → paired t-test.", "wilcoxon"
                    else:
                        rec_id, why, alt_id = "wilcoxon", "two related measurements, non-normal → Wilcoxon signed-rank.", "ttest_paired"
                else:
                    rec_id, why = "friedman", "3+ repeated conditions (non-parametric) → Friedman test. (Repeated-measures ANOVA comes in Phase B.)"
            else:
                rec_id, why = "ttest_one", "comparing one sample's mean to a known value → one-sample t-test."
        else:
            kind = st.selectbox("What are you comparing?",
                                ["Association between two categorical variables",
                                 "Risk / odds between an exposure and an outcome (2×2)",
                                 "Observed counts vs an expected distribution"], key="wz_ck")
            if kind.startswith("Association"):
                rec_id, why, alt_id = "chi_square", "association between two categorical variables → Chi-square (use Fisher's exact for small 2×2).", "fisher"
            elif kind.startswith("Risk"):
                rec_id, why = "riskratio", "exposure vs outcome in a 2×2 → risk ratio / odds ratio with 95% CI."
            else:
                rec_id, why = "gof", "observed vs expected counts → Chi-square goodness-of-fit."

    elif goal == "Measure a relationship between variables":
        hv = st.selectbox("How many variables?", ["Two variables", "Several variables"], key="wz_rel")
        rec_id, why = (("correlation", "two variables → correlation (Pearson, plus Spearman/Kendall for ranked/non-linear).")
                       if hv == "Two variables" else ("corr_matrix", "several variables → correlation matrix."))
    elif goal == "Predict or model an outcome":
        ot = st.selectbox("Outcome to predict", ["Numeric (continuous)", "Binary (yes/no, 0/1)"], key="wz_pred")
        rec_id, why = (("linear_reg", "continuous outcome → linear regression.")
                       if ot.startswith("Numeric") else ("logistic_reg", "binary outcome → logistic regression (odds ratios)."))
    elif goal == "Assess agreement or reliability":
        at = st.selectbox("What kind?",
                          ["Two raters — numeric ratings", "Two raters — categorical labels",
                           "Internal consistency of a multi-item scale"], key="wz_rel2")
        rec_id, why = {"Two raters — numeric ratings": ("icc", "numeric ratings across raters → intraclass correlation (ICC)."),
                       "Two raters — categorical labels": ("kappa", "categorical labels across two raters → Cohen's kappa."),
                       "Internal consistency of a multi-item scale": ("cronbach", "multi-item scale → Cronbach's alpha.")}[at]
    elif goal == "Evaluate a diagnostic test":
        dt = st.selectbox("What do you have?",
                          ["Test result vs truth (categorical)", "A continuous score vs truth"], key="wz_dx")
        rec_id, why = (("diagnostic", "categorical test result vs truth → sensitivity / specificity / PPV / NPV.")
                       if dt.startswith("Test result") else ("roc_auc", "continuous score vs truth → ROC / AUC with optimal cut-off."))
    elif goal == "Describe or summarise data":
        dd = st.selectbox("Data type", ["Numeric", "Categorical (counts)"], key="wz_desc")
        rec_id, why = (("descriptives", "numeric summary → descriptives with 95% CI.")
                       if dd == "Numeric" else ("crosstab", "categorical → cross-tabulation."))
    elif goal == "Check a statistical assumption":
        aa = st.selectbox("Which assumption?", ["Normality", "Equal variances across groups"], key="wz_as")
        rec_id, why = (("shapiro", "normality → Shapiro–Wilk.")
                       if aa == "Normality" else ("levene", "equal variances → Levene's test."))
    elif goal == "Plan sample size / power":
        rec_id, why = "power_ttest", "planning a two-group study → power / sample-size analysis."

    if rec_id:
        st.success(f"Recommended: **{SL.REGISTRY[rec_id].name}** — {why}")
        if alt_id:
            st.caption(f"Alternative to consider: {SL.REGISTRY[alt_id].name}.")
        if st.button("Use this test →", type="primary", key="wz_use"):
            cat_, name_ = SL.locate(rec_id)
            st.session_state["_wiz_cat"] = cat_
            st.session_state["_wiz_test"] = name_
            st.session_state["_apply_wiz"] = True
            st.rerun()

# ---- picker (keyed so the wizard can pre-select) ----------------------------
if st.session_state.get("sl_cat") not in cat_names:
    st.session_state["sl_cat"] = cat_names[0]
c1, c2 = st.columns(2)
cat = c1.selectbox("Category", cat_names, key="sl_cat")
specs = sorted(cats[cat], key=lambda s: s.name)
name_to_spec = {s.name: s for s in specs}
test_names = list(name_to_spec.keys())
if st.session_state.get("sl_test") not in test_names:
    st.session_state["sl_test"] = test_names[0]
test_name = c2.selectbox("Test", test_names, key="sl_test")
spec = name_to_spec[test_name]

st.markdown(f"**{spec.name}** — {spec.desc}")
if spec.notes:
    st.caption(spec.notes)

df = None
params = {}

if spec.needs_data:
    cols_df = pd.DataFrame({"Column": [c.name for c in spec.columns],
                            "Type": [c.kind for c in spec.columns],
                            "Required": ["Required" if c.required else "Optional" for c in spec.columns],
                            "What to enter": [c.help for c in spec.columns]})
    tcol, dcol = st.columns([3, 1])
    tcol.dataframe(cols_df, hide_index=True, use_container_width=True)
    dcol.download_button("⬇ Download Excel template", data=SL.template_bytes(spec),
                         file_name=f"jarvis_stat_{spec.id}_template.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         use_container_width=True)
    dcol.caption("Fill the **Data** sheet, then upload it below.")

    st.markdown("#### Your data")
    up = st.file_uploader("Upload the filled template (or your own .xlsx / .csv)",
                          type=["xlsx", "xls", "csv"], key=f"up_{spec.id}")
    use_example = st.checkbox("Use the built-in example data instead", value=False)

    def _read(file):
        if file.name.lower().endswith(".csv"):
            return pd.read_csv(file)
        xls = pd.ExcelFile(file)
        sheet = "Data" if "Data" in xls.sheet_names else xls.sheet_names[0]
        return pd.read_excel(xls, sheet_name=sheet)

    if use_example:
        df = pd.DataFrame({c.name: spec.example[c.name] for c in spec.columns if c.name in spec.example})
    elif up is not None:
        try:
            df = _read(up)
        except Exception as e:
            st.error(f"Could not read the file: {e}")
    if df is not None:
        with st.expander("Preview data", expanded=False):
            st.dataframe(df.head(20), use_container_width=True)

# extra numeric parameters (e.g. one-sample μ0, power inputs)
if spec.params:
    st.markdown("#### Parameters")
    pcols = st.columns(min(len(spec.params), 4))
    for i, p in enumerate(spec.params):
        params[p.name] = pcols[i % len(pcols)].number_input(p.name, value=float(p.default),
                                                            help=p.help, key=f"p_{spec.id}_{p.name}")

ready = (df is not None) or (not spec.needs_data)
if st.button("🧮 Run analysis", type="primary", disabled=not ready):
    if spec.needs_data:
        problems = SL.validate(spec, df)
    else:
        problems = []
    if problems:
        st.error("Please fix the data:\n\n- " + "\n- ".join(problems))
    else:
        try:
            with jarvis_spinner("Running the analysis…"):
                res = spec.run(df, params)
            st.session_state["sl_res"] = res
            st.session_state["sl_id"] = spec.id
            st.session_state["sl_name"] = spec.name
            try:
                st.session_state["sl_r"] = RX.stat_r_script(spec, df if spec.needs_data else None, params)
            except Exception:
                st.session_state["sl_r"] = None
        except Exception as e:
            st.error(f"Could not run this test with the data provided: {e}")
            st.caption("Tip: download the template above and match the column names/types exactly.")

res = st.session_state.get("sl_res")
if res is not None and st.session_state.get("sl_id") == spec.id:
    st.markdown("### Result")
    st.success(res.headline)
    if not res.table.empty:
        st.dataframe(res.table, hide_index=True, use_container_width=True)
    if res.interpretation:
        st.markdown(f"**Interpretation.** {res.interpretation}")
    for a in res.assumptions:
        st.info("Assumption — " + a)
    for c in res.caveats:
        st.warning("Caveat — " + c)
    if res.figure_png:
        st.image(res.figure_png, use_container_width=True)

    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ Report (.txt)", data=res.report_text(spec.name).encode("utf-8"),
                       file_name=f"jarvis_{spec.id}_report.txt", mime="text/plain",
                       use_container_width=True)
    if st.session_state.get("sl_r"):
        d2.download_button("⬇ R script (.R)", data=st.session_state["sl_r"].encode("utf-8"),
                           file_name=f"jarvis_{spec.id}.R", mime="text/plain",
                           use_container_width=True, help="Reproduce this exact result in RStudio.")
    if res.figure_png:
        d3.download_button("⬇ Figure (PNG)", data=res.figure_png,
                           file_name=f"jarvis_{spec.id}.png", mime="image/png", use_container_width=True)
    if st.button("🤖 Explain this result in plain English (AI)"):
        try:
            from bibliometric_pipeline.ai import interpret_figure
            payload = (res.figure_png if res.figure_png else None)
            with jarvis_spinner("Interpreting…"):
                if payload:
                    text = interpret_figure(payload, context=f"{spec.name}. {res.headline}. {res.interpretation}",
                                            filename=f"{spec.id}.png", mime="image/png")
                else:
                    text = res.interpretation
            st.markdown("**AI explanation.**")
            st.write(text)
            st.caption("AI-generated — verify against the numbers before quoting in a manuscript.")
        except Exception as e:
            st.error(f"AI explanation unavailable: {e}")
    brand_footer()

st.markdown("---")
how_to_use([
    ("🧭", "Pick your test",
     "Choose a category and test. Not sure which? Check the assumption tests first (normality, equal variance)."),
    ("⬇", "Download the Excel template",
     "It lists the exact columns to fill and what each means on an Instructions sheet."),
    ("📤", "Fill & upload",
     "Enter your data under the labelled columns and upload (or tick 'use example' to see how it works)."),
    ("🧮", "Run & report",
     "Get an APA-style result, effect size, assumption checks and a figure — download the report or a plain-English AI explanation."),
])
st.caption("Powered by scipy / statsmodels / scikit-learn / pingouin. Results still need domain interpretation — "
           "when assumptions fail, use the suggested non-parametric alternative.")
