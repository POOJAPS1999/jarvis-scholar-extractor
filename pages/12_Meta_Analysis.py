"""
Meta-Analysis
=============
No-setup meta-analysis. Choose an effect measure, download its Excel template,
upload your study-level data, and get a pooled effect + heterogeneity +
forest/funnel/radial/L'Abbé/Baujat plots + publication-bias tests +
leave-one-out / cumulative / subgroup / meta-regression + an APA paragraph +
a metafor R script. Engine: bibliometric_pipeline.meta_analysis.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline import meta_analysis as MA

st.set_page_config(page_title="Jarvis Scholar - Meta-Analysis", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Meta-Analysis")
st.caption("Choose an effect measure → download its Excel template → upload your studies → get a pooled "
           "estimate, forest & funnel plots, heterogeneity, publication-bias and sensitivity analyses, "
           "plus a metafor R script. Add optional Subgroup / Year / Moderator columns to unlock more.")

cats = MA.by_category()
c0, c1, c2, c3 = st.columns([1.4, 1.6, 1, 0.9])
cat = c0.selectbox("What are you meta-analysing?", list(cats.keys()))
names = {m.name: m for m in cats[cat]}
meas = names[c1.selectbox("Effect measure", list(names.keys()))]
model = "random" if c2.selectbox("Model", ["Random-effects (DL)", "Fixed-effect"]).startswith("Random") else "fixed"
hksj = c3.checkbox("Knapp–Hartung", value=False, help="More conservative CI for few studies (random-effects only).")
is_dta = meas.id == "dta"

# ---- required columns + template ----
cols_df = pd.DataFrame({"Column": [c for c, _ in meas.columns] + ["Subgroup", "Year", "Moderator"],
                        "Required": ["Required"] * len(meas.columns) + ["Optional"] * 3,
                        "What to enter": [h for _, h in meas.columns] +
                        ["Subgroup analysis + forest", "Cumulative meta-analysis (numeric)",
                         "Meta-regression + bubble (numeric)"]})
tcol, dcol = st.columns([3, 1])
tcol.dataframe(cols_df, hide_index=True, width="stretch")
dcol.download_button("⬇ Download Excel template", data=MA.template_bytes(meas),
                     file_name=f"jarvis_meta_{meas.id}_template.xlsx",
                     mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     width="stretch")
dcol.caption("One row per study. Fill the **Data** sheet.")

# ---- upload ----
st.markdown("#### Your studies")
up = st.file_uploader("Upload the filled template (or your own .xlsx / .csv)",
                      type=["xlsx", "xls", "csv"], key=f"mup_{meas.id}")
use_example = st.checkbox("Use the built-in example data instead", value=False)


def _read(file):
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    xls = pd.ExcelFile(file)
    sheet = "Data" if "Data" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)


df = None
if use_example:
    df = pd.DataFrame(meas.example)
elif up is not None:
    try:
        df = _read(up)
    except Exception as e:
        st.error(f"Could not read the file: {e}")

if df is not None:
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(30), width="stretch")

if st.button("📊 Run meta-analysis", type="primary", disabled=(df is None)):
    problems = MA.validate(meas, df)
    if problems:
        st.error("Please fix the data:\n\n- " + "\n- ".join(problems))
    else:
        try:
            with jarvis_spinner("Pooling the studies…"):
                if is_dta:
                    res = MA.run_dta(df, model=model)
                    r_src = MA.r_script_dta(df, model=model)
                else:
                    res = MA.run(meas.id, df, model=model, hksj=hksj)
                    r_src = MA.r_script(meas.id, df, model=model, hksj=hksj)
            st.session_state["mr_res"] = res
            st.session_state["mr_id"] = meas.id
            st.session_state["mr_r"] = r_src
        except Exception as e:
            st.error(f"Could not run the meta-analysis: {e}")
            st.caption("Tip: download the template above and match the column names/types exactly.")

res = st.session_state.get("mr_res")
if res is not None and st.session_state.get("mr_id") == meas.id:
    st.markdown("### Result")
    st.success(res.headline)
    st.markdown(f"**Interpretation.** {res.interpretation}")
    if not res.table.empty:
        st.dataframe(res.table, hide_index=True, width="stretch")
    if res.extras:
        st.markdown("#### Publication bias & moderators")
        for k, v in res.extras.items():
            st.info(f"**{k}** — {v}")
    for c in res.caveats:
        st.warning("Caveat — " + c)

    st.markdown("#### Figures")
    for i, (name, png) in enumerate(res.figures.items()):
        st.image(png, caption=name, width="stretch")
        st.download_button(f"⬇ {name} (PNG)", data=png, file_name=f"jarvis_meta_{meas.id}_{i}.png",
                           mime="image/png", key=f"figdl_{i}")

    st.markdown("---")
    d1, d2 = st.columns(2)
    d1.download_button("⬇ Full report (.txt)", data=res.report_text().encode("utf-8"),
                       file_name=f"jarvis_meta_{meas.id}_report.txt", mime="text/plain", width="stretch")
    if st.session_state.get("mr_r"):
        d2.download_button("⬇ metafor R script (.R)", data=st.session_state["mr_r"].encode("utf-8"),
                           file_name=f"jarvis_meta_{meas.id}.R", mime="text/plain", width="stretch",
                           help="Reproduce this meta-analysis in RStudio with the metafor package.")
    if st.button("🤖 Explain the main figure with AI"):
        try:
            from bibliometric_pipeline.ai import interpret_figure
            _first = next(iter(res.figures.values()))
            with jarvis_spinner("Interpreting…"):
                text = interpret_figure(_first,
                                        context=f"Meta-analysis figure. {res.headline}",
                                        filename="figure.png", mime="image/png")
            st.markdown("**AI explanation.**")
            st.write(text)
            st.caption("AI-generated — verify against the numbers before quoting in a manuscript.")
        except Exception as e:
            st.error(f"AI explanation unavailable: {e}")
    brand_footer()

st.markdown("---")
how_to_use([
    ("🧭", "Pick your effect measure",
     "OR/RR/RD for binary outcomes, MD/SMD for continuous, HR for survival, correlation/proportion/generic for the rest."),
    ("⬇", "Download the Excel template",
     "One row per study. Add optional Subgroup, Year or Moderator columns to unlock subgroup, cumulative and meta-regression."),
    ("📤", "Upload & run",
     "Choose fixed or random-effects (with optional Knapp–Hartung), then run — you get the pooled effect, heterogeneity and every plot."),
    ("📈", "Export",
     "Download each figure, a full text report, and a ready-to-run metafor R script — or get a plain-English AI read of the forest plot."),
])
st.caption("Fixed & DerSimonian–Laird random-effects, Q/I²/τ²/prediction interval, Egger/Begg/trim-and-fill, "
           "leave-one-out, cumulative, subgroup and meta-regression. R export uses the metafor package.")
