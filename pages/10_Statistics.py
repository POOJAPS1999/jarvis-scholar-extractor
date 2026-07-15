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

st.set_page_config(page_title="Jarvis Scholar - Statistics", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Statistics (no-code)")
st.caption("Pick a test → download its Excel template → upload your data → get an APA-style result with "
           "assumption checks, effect sizes and a plain-language verdict. No coding, no biostatistician.")

cats = SL.by_category()
cat_names = sorted(cats.keys(), key=lambda s: int(s.split(".")[0]))

c1, c2 = st.columns(2)
cat = c1.selectbox("Category", cat_names)
specs = sorted(cats[cat], key=lambda s: s.name)
name_to_spec = {s.name: s for s in specs}
test_name = c2.selectbox("Test", list(name_to_spec.keys()))
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

    d1, d2 = st.columns(2)
    d1.download_button("⬇ Download report (.txt)", data=res.report_text(spec.name).encode("utf-8"),
                       file_name=f"jarvis_{spec.id}_report.txt", mime="text/plain",
                       use_container_width=True)
    if res.figure_png:
        d2.download_button("⬇ Download figure (PNG)", data=res.figure_png,
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
