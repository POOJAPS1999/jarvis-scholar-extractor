"""
Meta-Analysis
=============
Pairwise (intervention, prognostic, prevalence, correlation, pre-post, generic),
diagnostic test accuracy (DTA), network meta-analysis (NMA), plus an
effect-size calculator (data prep). Choose your analysis, download the Excel
template, upload, and get pooled effects + publication-ready figures + an R
script (metafor / meta / mada / netmeta). Engines: bibliometric_pipeline.
meta_analysis, .network_meta and .es_calc.
"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline import meta_analysis as MA
from bibliometric_pipeline import network_meta as NM
from bibliometric_pipeline import es_calc as EC
from bibliometric_pipeline import prisma as PR

st.set_page_config(page_title="Jarvis Scholar - Meta-Analysis", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Meta-Analysis")
st.caption("Choose your analysis → download the Excel template → upload → get pooled effects, "
           "publication-ready figures and an R script. Pairwise (with REML / Paule–Mandel, "
           "Mantel–Haenszel & Peto), diagnostic accuracy (DTA), network meta-analysis (NMA) and an "
           "effect-size calculator are all supported.")


def _read(file):
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    xls = pd.ExcelFile(file)
    sheet = "Data" if "Data" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)


NMA_CAT = "Network meta-analysis"
CALC_CAT = "Effect-size calculator (data prep)"
PRISMA_CAT = "PRISMA 2020 flow diagram"
cats = MA.by_category()
cat_list = list(cats.keys()) + [NMA_CAT, CALC_CAT, PRISMA_CAT]
cat = st.selectbox("What are you meta-analysing?", cat_list)
is_nma = cat == NMA_CAT
is_calc = cat == CALC_CAT
is_prisma = cat == PRISMA_CAT

# ===========================================================================
# PRISMA 2020 flow diagram — self-contained form flow
# ===========================================================================
if is_prisma:
    st.markdown("#### PRISMA 2020 flow diagram")
    st.caption("Enter your study-selection counts → get a publication-ready PRISMA 2020 figure "
               "(databases & registers template) plus a matching DiagrammeR R script.")
    st.markdown("**Records identified from — sources** (one per line, as `name = count`; "
                "list each database/register you searched):")
    default_sources = "\n".join(f"{nm} = {c}" for nm, c in PR.DEFAULT_SOURCES)
    src_txt = st.text_area("Sources", value=default_sources, key="pr_sources",
                           label_visibility="collapsed", height=110)

    d = {}
    fc = st.columns(2)
    _core = [f for f in PR.FIELDS if f[0] not in ("databases", "registers")]
    for i, (k, label, default) in enumerate(_core):
        d[k] = fc[i % 2].number_input(label, min_value=0, value=int(default), step=1, key=f"pr_{k}")
    st.markdown("**Reports excluded — reasons** (one per line, as `reason = count`):")
    default_reasons = "\n".join(f"{r} = {n}" for r, n in PR.EXAMPLE_REASONS)
    rtxt = st.text_area("Exclusion reasons", value=default_reasons, key="pr_reasons",
                        label_visibility="collapsed", height=120)

    two_stream = st.checkbox("Add the 'other methods' identification stream "
                             "(websites / organisations / citation searching)", value=False,
                             help="Turns the single-column figure into the full two-stream PRISMA 2020 layout.")
    om, om_rtxt, om_src_txt = {}, "", ""
    if two_stream:
        st.markdown("**Other-methods sources** (one per line, as `name = count`; "
                    "list only the ones you used — e.g. just citation searching):")
        om_default_src = "\n".join(f"{nm} = {c}" for nm, c in PR.DEFAULT_OM_SOURCES)
        om_src_txt = st.text_area("Other-methods sources", value=om_default_src,
                                  key="pr_om_sources", label_visibility="collapsed", height=80)
        oc = st.columns(2)
        _om_core = [f for f in PR.OM_FIELDS if f[0] not in ("om_websites", "om_orgs", "om_citation")]
        for i, (k, label, default) in enumerate(_om_core):
            om[k] = oc[i % 2].number_input(label, min_value=0, value=int(default), step=1, key=f"pr_{k}")
        st.markdown("**Other-methods reports excluded — reasons** (`reason = count`):")
        om_default = "\n".join(f"{r} = {n}" for r, n in PR.EXAMPLE_OM_REASONS)
        om_rtxt = st.text_area("Other-methods exclusion reasons", value=om_default,
                               key="pr_om_reasons", label_visibility="collapsed", height=90)

    title = st.text_input("Figure title", value="PRISMA 2020 flow diagram", key="pr_title")

    def _parse_reasons(txt):
        out = []
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            if "=" in line:
                r, n = line.rsplit("=", 1)
                try:
                    out.append((r.strip(), int(float(n.strip()))))
                except Exception:
                    out.append((r.strip(), 0))
            else:
                out.append((line, 0))
        return out

    if st.button("🖼 Generate PRISMA diagram", type="primary"):
        reasons = _parse_reasons(rtxt)
        om_reasons = _parse_reasons(om_rtxt)
        sources = _parse_reasons(src_txt)
        om_sources = _parse_reasons(om_src_txt)
        ttl = title or "PRISMA 2020 flow diagram"
        try:
            with jarvis_spinner("Drawing the PRISMA flow…"):
                if two_stream:
                    st.session_state["prisma_png"] = PR.flow_png_2stream(
                        d, om, reasons=reasons or None, om_reasons=om_reasons or None, title=ttl,
                        sources=sources or None, om_sources=om_sources or None)
                    st.session_state["prisma_r"] = PR.r_script(
                        d, reasons=reasons or None, om=om, om_reasons=om_reasons or None,
                        sources=sources or None, om_sources=om_sources or None)
                else:
                    st.session_state["prisma_png"] = PR.flow_png(d, reasons=reasons or None, title=ttl,
                                                                 sources=sources or None)
                    st.session_state["prisma_r"] = PR.r_script(d, reasons=reasons or None,
                                                               sources=sources or None)
        except Exception as e:
            st.error(f"Could not build the diagram: {e}")

    if st.session_state.get("prisma_png"):
        st.image(st.session_state["prisma_png"], width="stretch")
        p1, p2 = st.columns(2)
        p1.download_button("⬇ PRISMA diagram (PNG)", data=st.session_state["prisma_png"],
                           file_name="prisma_2020_flow.png", mime="image/png", width="stretch")
        p2.download_button("⬇ R script (DiagrammeR)", data=st.session_state["prisma_r"].encode("utf-8"),
                           file_name="prisma_2020_flow.R", mime="text/plain", width="stretch")
    st.markdown("---")
    how_to_use([
        ("🔢", "Enter your counts", "Databases/registers found, duplicates removed, screened, excluded, "
         "reports sought/assessed, and studies included."),
        ("📝", "List exclusion reasons", "One per line as 'reason = count' — they fill the 'Reports excluded' box."),
        ("🖼", "Generate", "Get the PRISMA 2020 figure (databases & registers version)."),
        ("⬇", "Export", "Download a high-res PNG for your manuscript, or a DiagrammeR R script."),
    ])
    st.caption("Follows the PRISMA 2020 template: a 'records removed before screening' box and "
               "'Reports' wording. For the two-stream version (other methods / citation searching), ask to enable it.")
    st.stop()

# ===========================================================================
# Effect-size calculator (data prep) — its own self-contained flow
# ===========================================================================
if is_calc:
    st.markdown("#### Turn oddly-reported data into meta-analysis inputs")
    cname = {c.name: c for c in EC.CONVERSIONS.values()}
    conv = cname[st.selectbox("What do you have?", list(cname.keys()))]
    ratio = False
    if conv.id in ("ci_to_se", "p_to_se"):
        ratio = st.checkbox("Ratio measure? (OR / RR / HR — compute on the log scale)", value=False)
    st.info(conv.note)

    cols_df = pd.DataFrame([(c, "Required", h) for c, h in conv.columns],
                           columns=["Column", "Required", "What to enter"])
    tcol, dcol = st.columns([3, 1])
    tcol.dataframe(cols_df, hide_index=True, width="stretch")
    dcol.download_button("⬇ Download Excel template", data=EC.template_bytes(conv),
                         file_name=f"jarvis_escalc_{conv.id}_template.xlsx",
                         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         width="stretch")
    up = st.file_uploader("Upload the filled template (.xlsx / .csv)", type=["xlsx", "xls", "csv"],
                          key=f"calc_{conv.id}")
    use_ex = st.checkbox("Use the built-in example data instead", value=False, key=f"calcex_{conv.id}")
    cdf = None
    if use_ex:
        cdf = pd.DataFrame(conv.example)
    elif up is not None:
        try:
            cdf = _read(up)
        except Exception as e:
            st.error(f"Could not read the file: {e}")
    if cdf is not None:
        with st.expander("Preview data", expanded=False):
            st.dataframe(cdf.head(30), width="stretch")
    if st.button("🧮 Convert", type="primary", disabled=(cdf is None)):
        problems = EC.validate(conv, cdf)
        if problems:
            st.error("Please fix the data:\n\n- " + "\n- ".join(problems))
        else:
            try:
                out, note, poolable = EC.compute(conv.id, cdf, ratio=ratio)
                st.success(f"Converted {len(out)} rows. {note}")
                st.dataframe(out, hide_index=True, width="stretch")
                st.download_button("⬇ Download result (.csv)", data=out.to_csv(index=False).encode("utf-8"),
                                   file_name=f"jarvis_escalc_{conv.id}.csv", mime="text/csv")
                if poolable:
                    st.markdown("These **Effect + 95% CI** rows drop straight into the *Generic (effect + CI)* "
                                "analysis. Here is a quick pooled forest:")
                    res = MA.run("generic", out, model="random")
                    st.image(res.figures["Forest plot"], caption=res.headline, width="stretch")
                    if ratio:
                        st.caption("Ratio note: this quick pool is on the raw scale. For proper log-scale "
                                   "pooling, use the *Hazard ratio (from reported)* template with these values.")
                else:
                    st.caption("Use the **Mean + SD + N** columns in the *Mean difference* or *SMD* template "
                               "(one arm per sheet).")
            except Exception as e:
                st.error(f"Could not convert: {e}")
    st.markdown("---")
    how_to_use([
        ("🧭", "Pick what you have", "A 95% CI, a p-value, or medians/quartiles instead of mean ± SD."),
        ("⬇", "Download the template", "Fill one row per study with the numbers you have."),
        ("🧮", "Convert", "Get standard-error / mean+SD columns ready for the meta-analysis templates."),
        ("📈", "Pool", "Effect+CI rows can be pooled right here; mean+SD rows feed MD / SMD."),
    ])
    st.caption("Median→mean via Luo (2018); median→SD via Wan (2014). CI→SE and p→SE on the natural "
               "(or log) scale.")
    st.stop()

# ===========================================================================
# Pairwise / DTA / NMA
# ===========================================================================
if not is_nma:
    c1, c2, c3, c4 = st.columns([1.7, 1.5, 1.3, 0.9])
    names = {m.name: m for m in cats[cat]}
    meas = names[c1.selectbox("Effect measure", list(names.keys()))]
    is_dta = meas.id == "dta"
    columns = meas.columns
    template = MA.template_bytes(meas)
    tmpl_name = f"jarvis_meta_{meas.id}_template.xlsx"

    model_opts = ["Random-effects", "Fixed-effect"]
    if not is_dta and meas.binary:
        model_opts.append("Mantel–Haenszel (fixed)")
        if meas.id == "or":
            model_opts.append("Peto (fixed)")
    model_choice = c2.selectbox("Model", model_opts)
    model = {"Random-effects": "random", "Fixed-effect": "fixed",
             "Mantel–Haenszel (fixed)": "mh", "Peto (fixed)": "peto"}[model_choice]

    tau_method = "DL"
    if not is_dta:
        tau_lbl = c3.selectbox("τ² estimator", ["DerSimonian–Laird", "REML", "Paule–Mandel"],
                               help="Between-study variance estimator (random-effects only).")
        tau_method = {"DerSimonian–Laird": "DL", "REML": "REML", "Paule–Mandel": "PM"}[tau_lbl]
        hksj = c4.checkbox("Knapp–Hartung", value=False,
                           help="Conservative CI for few studies (random-effects only).")
    else:
        hksj = False
    nma_scale = "log"
else:
    meas = None; is_dta = False; tau_method = "DL"
    columns = NM.COLUMNS
    template = NM.template_bytes()
    tmpl_name = "jarvis_meta_network_template.xlsx"
    c1, c2, c3 = st.columns([1.8, 1.3, 1.3])
    c1.caption("One row per pairwise comparison (contrast format).")
    model = "random" if c2.selectbox("Model", ["Random-effects", "Fixed-effect"]).startswith("Random") else "fixed"
    nma_scale = "log" if c3.selectbox("Effect scale", ["Ratio (OR/RR/HR)", "Difference (MD)"]).startswith("Ratio") else "raw"
    hksj = False

# ---- required columns + template ----
cols_rows = [(c, "Required", h) for c, h in columns]
if not is_nma and not is_dta:
    cols_rows += [("Subgroup", "Optional", "Subgroup analysis + forest"),
                  ("Year", "Optional", "Cumulative meta-analysis (numeric)"),
                  ("Moderator / Moderator1, Moderator2…", "Optional", "Meta-regression + bubble (numeric)")]
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
                    res = MA.run(meas.id, df, model=model, hksj=hksj, tau_method=tau_method)
                    r_src = MA.r_script(meas.id, df, model=model, hksj=hksj, tau_method=tau_method)
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
        st.markdown("#### Publication bias & moderators" if not is_nma else "#### Heterogeneity, ranking & consistency")
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
     "Pairwise (OR/RR/MD/HR…), diagnostic accuracy (DTA), network meta-analysis (NMA), or the "
     "effect-size calculator for data prep."),
    ("⬇", "Download the Excel template",
     "Pairwise/DTA: one row per study. NMA: one row per pairwise comparison (Study, Treatment1, Treatment2, TE, seTE)."),
    ("📤", "Upload & run",
     "Pick your model (random / fixed / Mantel–Haenszel / Peto), τ² estimator (DL / REML / PM), and options."),
    ("📈", "Export",
     "Download every figure, a full report, and an R script (metafor / meta / mada / netmeta) — or an AI read of the main figure."),
])
st.caption("Pairwise: metafor (DL / REML / PM, HKSJ, Mantel–Haenszel, Peto). DTA: meta + mada "
           "(bivariate/HSROC SROC, Deeks). Network: netmeta (league table, P-scores, node-splitting).")
