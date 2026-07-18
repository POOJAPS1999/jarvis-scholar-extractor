"""
Meta-Analysis
=============
No-setup meta-analysis: pairwise (intervention, prognostic, prevalence,
correlation, pre-post, generic), diagnostic test accuracy (DTA), and
network meta-analysis (NMA). Choose your analysis, download the Excel
template, upload, and get pooled effects + publication-ready figures +
an R script (metafor / meta / mada / netmeta). Engines:
bibliometric_pipeline.meta_analysis and .network_meta.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline import meta_analysis as MA
from bibliometric_pipeline import network_meta as NM

st.set_page_config(page_title="Jarvis Scholar - Meta-Analysis", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Meta-Analysis")
st.caption("Choose your analysis → download the Excel template → upload → get pooled effects, "
           "publication-ready figures and an R script. Pairwise, diagnostic accuracy (DTA) and "
           "network meta-analysis (NMA) are all supported.")

NMA_CAT = "Network meta-analysis"
cats = MA.by_category()
cat_list = list(cats.keys()) + [NMA_CAT]

c0, c1, c2, c3 = st.columns([1.5, 1.6, 1, 0.9])
cat = c0.selectbox("What are you meta-analysing?", cat_list)
is_nma = cat == NMA_CAT

if not is_nma:
    names = {m.name: m for m in cats[cat]}
    meas = names[c1.selectbox("Effect measure", list(names.keys()))]
    is_dta = meas.id == "dta"
    columns = meas.columns
    template = MA.template_bytes(meas)
    tmpl_name = f"jarvis_meta_{meas.id}_template.xlsx"
else:
    meas = None; is_dta = False
    columns = NM.COLUMNS
    template = NM.template_bytes()
    tmpl_name = "jarvis_meta_network_template.xlsx"
    c1.caption("One row per pairwise comparison (contrast format).")

model = "random" if c2.selectbox("Model", ["Random-effects", "Fixed-effect"]).startswith("Random") else "fixed"
if is_nma:
    nma_scale = "log" if c3.selectbox("Effect scale", ["Ratio (OR/RR/HR)", "Difference (MD)"]).startswith("Ratio") else "raw"
    hksj = False
else:
    nma_scale = "log"
    hksj = c3.checkbox("Knapp–Hartung", value=False, help="Conservative CI for few studies (random-effects only).")

# ---- required columns + template ----
cols_rows = [(c, "Required", h) for c, h in columns]
if not is_nma:
    cols_rows += [("Subgroup", "Optional", "Subgroup analysis + forest"),
                  ("Year", "Optional", "Cumulative meta-analysis (numeric)"),
                  ("Moderator", "Optional", "Meta-regression + bubble (numeric)")]
cols_df = pd.DataFrame(cols_rows, columns=["Column", "Required", "What to enter"])
tcol, dcol = st.columns([3, 1])
tcol.dataframe(cols_df, hide_index=True, width="stretch")
dcol.download_button("⬇ Download Excel template", data=template, file_name=tmpl_name,
                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
dcol.caption("Fill the **Data** sheet, then upload it below.")

# ---- upload ----
st.markdown("#### Your studies")
up = st.file_uploader("Upload the filled template (or your own .xlsx / .csv)",
                      type=["xlsx", "xls", "csv"], key=f"mup_{cat}_{'' if is_nma else meas.id}")
use_example = st.checkbox("Use the built-in example data instead", value=False)


def _read(file):
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    xls = pd.ExcelFile(file)
    sheet = "Data" if "Data" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)


df = None
if use_example:
    df = pd.DataFrame(NM.EXAMPLE if is_nma else meas.example)
elif up is not None:
    try:
        df = _read(up)
    except Exception as e:
        st.error(f"Could not read the file: {e}")

if df is not None:
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(30), width="stretch")

# ---- NMA extra controls (need the data first) ----
nma_ref = None; nma_dir = False
if is_nma and df is not None and "Treatment1" in df.columns and "Treatment2" in df.columns:
    treats = sorted(set(df["Treatment1"].astype(str)) | set(df["Treatment2"].astype(str)))
    r1, r2 = st.columns(2)
    nma_ref = r1.selectbox("Reference treatment", treats)
    nma_dir = r2.selectbox("Which is better?", ["Lower effect is better (e.g., fewer events)",
                                                 "Higher effect is better"]).startswith("Higher")

if st.button("📊 Run meta-analysis", type="primary", disabled=(df is None)):
    problems = NM.validate(df) if is_nma else MA.validate(meas, df)
    if problems:
        st.error("Please fix the data:\n\n- " + "\n- ".join(problems))
    else:
        try:
            with jarvis_spinner("Pooling the studies…"):
                if is_nma:
                    res, rank, ref = NM.run_nma(df, scale=nma_scale, model=model,
                                                reference=nma_ref, higher_better=nma_dir)
                    r_src = NM.r_script_nma(df, scale=nma_scale, reference=nma_ref, model=model)
                    st.session_state["mr_rank"] = rank
                elif is_dta:
                    res = MA.run_dta(df, model=model); r_src = MA.r_script_dta(df, model=model)
                    st.session_state["mr_rank"] = None
                else:
                    res = MA.run(meas.id, df, model=model, hksj=hksj)
                    r_src = MA.r_script(meas.id, df, model=model, hksj=hksj)
                    st.session_state["mr_rank"] = None
            st.session_state["mr_res"] = res
            st.session_state["mr_key"] = cat + ("" if is_nma else meas.id)
            st.session_state["mr_r"] = r_src
        except Exception as e:
            st.error(f"Could not run the meta-analysis: {e}")
            st.caption("Tip: download the template above and match the column names/types exactly.")

res = st.session_state.get("mr_res")
if res is not None and st.session_state.get("mr_key") == cat + ("" if is_nma else meas.id):
    st.markdown("### Result")
    st.success(res.headline)
    st.markdown(f"**Interpretation.** {res.interpretation}")
    if is_nma:
        st.markdown("**League table** (row vs column):")
    if not res.table.empty:
        st.dataframe(res.table, hide_index=True, width="stretch")
    if st.session_state.get("mr_rank") is not None:
        st.markdown("**Ranking:**")
        st.dataframe(st.session_state["mr_rank"], hide_index=True, width="stretch")
    if res.extras:
        st.markdown("#### Publication bias & moderators" if not is_nma else "#### Heterogeneity & ranking")
        for k, v in res.extras.items():
            st.info(f"**{k}** — {v}")
    for c in res.caveats:
        st.warning("Caveat — " + c)

    st.markdown("#### Figures")
    for i, (name, png) in enumerate(res.figures.items()):
        st.image(png, caption=name, width="stretch")
        st.download_button(f"⬇ {name} (PNG)", data=png, file_name=f"jarvis_meta_{i}.png",
                           mime="image/png", key=f"figdl_{i}")

    st.markdown("---")
    d1, d2 = st.columns(2)
    d1.download_button("⬇ Full report (.txt)", data=res.report_text().encode("utf-8"),
                       file_name="jarvis_meta_report.txt", mime="text/plain", width="stretch")
    if st.session_state.get("mr_r"):
        d2.download_button("⬇ R script (.R)", data=st.session_state["mr_r"].encode("utf-8"),
                           file_name="jarvis_meta.R", mime="text/plain", width="stretch",
                           help="Reproduce in RStudio (metafor / meta / mada / netmeta).")
    if st.button("🤖 Explain the main figure with AI"):
        try:
            from bibliometric_pipeline.ai import interpret_figure
            _first = next(iter(res.figures.values()))
            with jarvis_spinner("Interpreting…"):
                text = interpret_figure(_first, context=f"Meta-analysis figure. {res.headline}",
                                        filename="figure.png", mime="image/png")
            st.markdown("**AI explanation.**"); st.write(text)
            st.caption("AI-generated — verify against the numbers before quoting in a manuscript.")
        except Exception as e:
            st.error(f"AI explanation unavailable: {e}")
    brand_footer()

st.markdown("---")
how_to_use([
    ("🧭", "Choose your analysis",
     "Pairwise (OR/RR/MD/HR…), diagnostic accuracy (DTA), or network meta-analysis (NMA) of ≥3 treatments."),
    ("⬇", "Download the Excel template",
     "Pairwise/DTA: one row per study. NMA: one row per pairwise comparison (Study, Treatment1, Treatment2, TE, seTE)."),
    ("📤", "Upload & run",
     "Pick fixed or random-effects. NMA also asks for a reference treatment and which direction is 'better'."),
    ("📈", "Export",
     "Download every figure, a full report, and an R script (metafor / meta / mada / netmeta) — or an AI read of the main figure."),
])
st.caption("Pairwise: metafor. DTA: meta + mada (SROC, Deeks). Network: netmeta (league table, P-scores, "
           "network graph). Frequentist estimation; the R exports also cover inconsistency / node-splitting.")
