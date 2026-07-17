"""
Scientific Plot Studio
======================
No-code publication-ready scientific plots. Pick a plot, download its Excel
template, fill the labelled columns, upload, and get a finished high-res
figure — no scripting, no Python, no biostatistician. Every plot is defined
in bibliometric_pipeline.plot_studio (one engine, ~60 plot types).
"""
import io
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.branding import THEME_CSS, jarvis_spinner, how_to_use, brand_footer
from bibliometric_pipeline import plot_studio as PS
from bibliometric_pipeline import r_export as RX

st.set_page_config(page_title="Jarvis Scholar - Scientific Plot Studio", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()

st.title("Scientific Plot Studio")
st.caption("Pick a plot → download its Excel template → fill your data → upload → get a publication-ready "
           "figure. No coding, no Python, no biostatistician. ~60 plot types across 7 categories.")

cats = PS.by_category()
cat_names = sorted(cats.keys())

# ---- pick category + plot ------------------------------------------------
c1, c2 = st.columns(2)
cat = c1.selectbox("Category", cat_names)
specs = sorted(cats[cat], key=lambda s: s.name)
name_to_spec = {s.name: s for s in specs}
plot_name = c2.selectbox("Plot type", list(name_to_spec.keys()))
spec = name_to_spec[plot_name]

st.markdown(f"**{spec.name}** — {spec.desc}")
if spec.notes:
    st.caption(spec.notes)

# ---- required columns + template ----------------------------------------
cols_df = pd.DataFrame(
    {"Column": [c.name for c in spec.columns],
     "Type": [c.kind for c in spec.columns],
     "Required": ["Required" if c.required else "Optional" for c in spec.columns],
     "What to enter": [c.help for c in spec.columns]}
)
tcol, dcol = st.columns([3, 1])
tcol.dataframe(cols_df, hide_index=True, width="stretch")
dcol.download_button(
    "⬇ Download Excel template",
    data=PS.template_bytes(spec),
    file_name=f"jarvis_plot_{spec.id}_template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    width="stretch",
)
dcol.caption("Fill the **Data** sheet, then upload it below.")

# ---- upload data ---------------------------------------------------------
st.markdown("#### Your data")
up = st.file_uploader("Upload the filled template (or your own .xlsx / .csv)",
                      type=["xlsx", "xls", "csv"], key=f"up_{spec.id}")


def _read(file) -> pd.DataFrame:
    if file.name.lower().endswith(".csv"):
        return pd.read_csv(file)
    xls = pd.ExcelFile(file)
    sheet = "Data" if "Data" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)


use_example = st.checkbox("Use the built-in example data instead (preview the plot)", value=False)

df = None
if use_example:
    df = pd.DataFrame({c.name: spec.example[c.name] for c in spec.columns if c.name in spec.example})
elif up is not None:
    try:
        df = _read(up)
    except Exception as e:
        st.error(f"Could not read the file: {e}")

if df is not None:
    with st.expander("Preview data", expanded=False):
        st.dataframe(df.head(20), width="stretch")

# ---- style controls ------------------------------------------------------
with st.expander("Style & labels", expanded=True):
    s1, s2, s3 = st.columns(3)
    title = s1.text_input("Title", value="")
    xlabel = s2.text_input("X-axis label", value="")
    ylabel = s3.text_input("Y-axis label", value="")
    s4, s5, s6 = st.columns(3)
    pal = s4.selectbox("Palette", list(PS.PALETTES.keys()))
    width = s5.slider("Width (in)", 5.0, 14.0, 8.0, 0.5)
    height = s6.slider("Height (in)", 3.0, 12.0, 5.0, 0.5)
    s7, s8, s9, s10 = st.columns(4)
    logx = s7.checkbox("Log X", value=False)
    logy = s8.checkbox("Log Y", value=False)
    grid = s9.checkbox("Grid", value=True)
    legend = s10.checkbox("Legend", value=True)
    s11, s12, s13 = st.columns(3)
    annotate = s11.checkbox("Value / stat labels", value=True)
    watermark = s12.checkbox("Jarvis Scholar watermark", value=True)
    dpi = s13.select_slider("Resolution (DPI)", options=[150, 200, 300, 600], value=300)

opt = PS.PlotOptions(title=title, xlabel=xlabel, ylabel=ylabel, palette=pal,
                     figsize=(width, height), dpi=int(dpi), logx=logx, logy=logy,
                     grid=grid, legend=legend, annotate=annotate, watermark=watermark)

# ---- generate ------------------------------------------------------------
if st.button("📊 Generate figure", type="primary", disabled=(df is None)):
    problems = PS.validate(spec, df)
    if problems:
        st.error("Please fix the data:\n\n- " + "\n- ".join(problems))
    else:
        try:
            with jarvis_spinner("Rendering your figure…"):
                fig = spec.render(df, opt)
                png = PS.fig_to_png(fig, dpi=int(dpi))
            st.session_state["ps_png"] = png
            st.session_state["ps_id"] = spec.id
            st.session_state["ps_ctx"] = f"{spec.name}: {title}" if title else spec.name
            try:
                st.session_state["ps_r"] = RX.plot_r_script(spec, df, opt)
            except Exception:
                st.session_state["ps_r"] = None
        except Exception as e:
            st.error(f"Could not render this plot with the data provided: {e}")
            st.caption("Tip: download the template above and match the column names/types exactly.")

# ---- show result + downloads + AI caption --------------------------------
if st.session_state.get("ps_png") and st.session_state.get("ps_id") == spec.id:
    png = st.session_state["ps_png"]
    st.image(png, caption=spec.name, width="stretch")
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇ Figure (PNG)", data=png,
                       file_name=f"jarvis_{spec.id}.png", mime="image/png",
                       width="stretch")
    if st.session_state.get("ps_r"):
        d2.download_button("⬇ R script (.R)", data=st.session_state["ps_r"].encode("utf-8"),
                           file_name=f"jarvis_{spec.id}.R", mime="text/plain",
                           width="stretch", help="Reproduce this exact figure in RStudio.")
    if d3.button("🤖 Interpret with AI", width="stretch"):
        try:
            from bibliometric_pipeline.ai import interpret_figure
            with jarvis_spinner("Interpreting…"):
                text = interpret_figure(png, context=st.session_state.get("ps_ctx", spec.name),
                                        filename=f"{spec.id}.png", mime="image/png")
            st.subheader("AI interpretation")
            st.write(text)
            st.caption("AI-generated — verify against the figure before quoting in a manuscript.")
        except Exception as e:
            st.error(f"AI interpretation unavailable: {e}")
    brand_footer()

# ---- how to use ----------------------------------------------------------
st.markdown("---")
how_to_use([
    ("🧭", "Pick your plot",
     "Choose a category and plot type. Read the description and the required-columns table."),
    ("⬇", "Download the Excel template",
     "It has a Data sheet with the exact columns to fill and an Instructions sheet explaining each one."),
    ("📤", "Fill & upload",
     "Enter your numbers under the labelled columns, save, and upload the file (or tick 'use example' to preview)."),
    ("🎨", "Style & generate",
     "Set title, labels, palette and size, then Generate. Download the high-res PNG — and optionally get an AI caption."),
])
st.caption("Publication-ready static figures rendered with matplotlib. Statistical plots use scipy / "
           "scikit-learn / statsmodels / lifelines under the hood — no setup needed on your side.")
