"""
ICMR Institute Tagger
=====================
Dashboard tool: upload any sheet that has affiliation text and tag each row
with which of ICMR's 28 constituent institutes it refers to (current
official name), even when the affiliation uses an old name or a bare
acronym. A single row can be tagged with multiple institutes
(semicolon-joined) for real multi-site collaborations.

This reuses the exact same battle-tested matching logic
(bibliometric_pipeline.icmr_institutes) that the main pipeline's "ICMR mode"
uses, and the same per-segment + Author_Affiliation_Map handling as the
standalone icmr_institute_tagger.py CLI script — so a post-hoc tag here and
a fresh pipeline run always agree.
"""
import json
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.icmr_institutes import resolve_all_icmr_institutes
from bibliometric_pipeline import icmr_tables as it
from bibliometric_pipeline.ui_helpers import download_buttons, read_tabular_upload
from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, jarvis_spinner, how_to_use, brand_footer, icmr_tagger_template_bytes, icmr_tagger_preview

st.set_page_config(page_title="Jarvis Scholar - ICMR Tagger", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()
st.title("ICMR institute tagger")
st.caption(
    "Upload a sheet with affiliation columns and tag each row with its ICMR "
    "institute(s). Handles former names, bare acronyms, multi-institute rows, "
    "and (if present) a per-author `Author_Affiliation_Map` column."
)

with st.expander("📋 Required format — download a blank template", expanded=False):
    st.markdown(
        "This tool scans affiliation columns — `Affliation`, `First Author Affiliation`, "
        "`Corresponding Author Affiliation`, and (optionally) `Author_Affiliation_Map`. "
        "Download the template, paste your rows in, and upload it. (To also generate the "
        "ICMR analysis tables, use an *enriched* sheet that additionally has `Citations` etc.)"
    )
    st.download_button(
        "⬇ Download blank ICMR-tagger template (.xlsx)",
        data=icmr_tagger_template_bytes(),
        file_name="jarvis_scholar_icmr_tagger_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

_CCOE_LABEL = "ICMR Collaborating Centre of Excellence (external partner institution, not one of the 28 core institutes)"
_HQ_LABEL = "ICMR Headquarters, New Delhi (not a constituent institute)"
_PSEUDO_LABELS = {_CCOE_LABEL, _HQ_LABEL}

# Affiliation columns the pipeline normally emits; used as smart defaults.
_DEFAULT_AFF_COLS = ["Affliation", "First Author Affiliation", "Corresponding Author Affiliation"]
_TAG_COL = "ICMR Institute (Current Name)"


def _split_segments(text):
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return [s.strip() for s in str(text).split(";") if s.strip()]


def _per_author_texts(raw_json):
    if raw_json is None or (isinstance(raw_json, float) and pd.isna(raw_json)):
        return []
    try:
        amap = json.loads(raw_json)
    except (TypeError, ValueError):
        return []
    return list(amap.values()) if isinstance(amap, dict) else []


uploaded = st.file_uploader(
    "Upload a sheet (.xlsx / .csv)", type=["xlsx", "xls", "csv"],
    help="Typically a pipeline output or a curated Included_studies file.",
)

if uploaded is None:
    st.info("Upload a sheet to begin.")
    st.stop()

try:
    df = read_tabular_upload(uploaded)
except Exception as e:
    st.error(f"Could not read that file: {e}")
    st.stop()

st.write(f"**{len(df)}** rows, **{len(df.columns)}** columns.")

candidate_defaults = [c for c in _DEFAULT_AFF_COLS if c in df.columns]
aff_cols = st.multiselect(
    "Which column(s) hold affiliation text?",
    options=list(df.columns),
    default=candidate_defaults,
    help="Every selected column is scanned. Each semicolon-separated entry is "
         "matched on its own to avoid cross-author false positives.",
)

has_aff_map = "Author_Affiliation_Map" in df.columns
use_aff_map = False
if has_aff_map:
    use_aff_map = st.checkbox(
        "Also scan the per-author `Author_Affiliation_Map` column (recommended)",
        value=True,
    )

if not aff_cols:
    st.warning("Select at least one affiliation column to tag.")
    st.stop()

if st.button("Tag ICMR institutes", type="primary"):
    def resolve_row(row):
        texts = []
        for col in aff_cols:
            texts.extend(_split_segments(row.get(col, "")))
        if use_aff_map:
            texts.extend(_per_author_texts(row.get("Author_Affiliation_Map")))
        return resolve_all_icmr_institutes(*texts)

    _loader = st.empty()
    _loader.markdown(reactor_loader_html("JARVIS is tagging ICMR institutes…"), unsafe_allow_html=True)
    out = df.copy()
    with jarvis_spinner("Resolving affiliations to ICMR institutes…"):
        out[_TAG_COL] = out.apply(resolve_row, axis=1)
    _loader.empty()

    # Summary stats (same accounting as the CLI script)
    col = out[_TAG_COL]
    exploded = col[col != ""].str.split("; ").explode()
    is_pseudo = exploded.isin(_PSEUDO_LABELS)
    is_real = ~is_pseudo
    n_specific = int(is_real.groupby(level=0).any().sum()) if len(exploded) else 0
    n_multi = int(exploded[is_real].groupby(level=0).size().gt(1).sum()) if is_real.any() else 0
    n_hq = int((exploded == _HQ_LABEL).sum())
    n_ccoe = int((exploded == _CCOE_LABEL).sum())

    st.success(f"Tagged {len(out)} rows.")
    m = st.columns(4)
    m[0].metric("Rows with an institute", n_specific)
    m[1].metric("Multi-institute rows", n_multi)
    m[2].metric("HQ mentions", n_hq)
    m[3].metric("CCoE mentions", n_ccoe)

    if is_real.any():
        st.subheader("Breakdown by institute")
        counts = exploded[is_real].value_counts().rename_axis("Institute").reset_index(name="Rows")
        st.dataframe(counts, use_container_width=True, hide_index=True)

    st.subheader("Preview (tagged column last)")
    preview_cols = aff_cols[:1] + [_TAG_COL]
    st.dataframe(out[preview_cols].head(50), use_container_width=True, hide_index=True)

    stem = os.path.splitext(uploaded.name)[0] + "_icmr_tagged"
    download_buttons(out, stem=stem, key_prefix="icmr", sheet_name="ICMR Tagged")

    # ---- Auto-generated ICMR bibliometric tables (3, 4, 5, 8, 10) ----
    st.markdown("---")
    st.subheader("ICMR bibliometric tables")
    if not it.has_required(out):
        st.info(
            "To auto-generate the ICMR analysis tables (institute benchmarking, "
            "divisions, leadership, mandate fidelity, international partners), upload "
            "an **enriched** dataset that also has a `Citations` column (and ideally "
            "Open Access, Collaboration Type, author-from-ICMR flags, All Country, "
            "keywords). This affiliation-only sheet doesn't have them.",
            icon="ℹ️",
        )
    else:
        _l = st.empty()
        _l.markdown(reactor_loader_html("JARVIS is building the ICMR tables…"), unsafe_allow_html=True)
        with jarvis_spinner("Computing institute-level bibliometrics…"):
            t3 = it.institute_benchmarking(out)
            t4_summary, t4_ref = it.division_summary(out)
            t5, t5_overall = it.leadership_vs_contribution(out)
            t8 = it.mandate_fidelity(out)
            t10 = it.international_partners_by_institute(out)
        _l.empty()

        st.markdown("**Table 3 · Institute-level bibliometric benchmarking** (top 15 by volume)")
        st.dataframe(t3, use_container_width=True, hide_index=True)
        download_buttons(t3, stem=stem + "_T3_benchmarking", key_prefix="t3", sheet_name="Table 3")

        st.markdown("**Table 4 · Publications by inferred ICMR HQ scientific division**")
        st.dataframe(t4_summary, use_container_width=True, hide_index=True)
        download_buttons(t4_summary, stem=stem + "_T4_divisions", key_prefix="t4", sheet_name="Table 4")

        st.markdown("**Table 5 · Leadership vs. contribution, by institute** (top 15 by volume)")
        if t5.empty:
            st.caption("Needs ‘Corresponding Author from ICMR’ and ‘Any Author from ICMR’ columns.")
        else:
            st.caption(f"Corpus-wide: " + ", ".join(f"{k} — {v}" for k, v in t5_overall.items()))
            st.dataframe(t5, use_container_width=True, hide_index=True)
            download_buttons(t5, stem=stem + "_T5_leadership", key_prefix="t5", sheet_name="Table 5")

        st.markdown("**Table 8 · Mandate fidelity, by institute** (top 15 by fidelity %)")
        if t8.empty:
            st.caption("No institute-vision matches found for this dataset.")
        else:
            st.dataframe(t8, use_container_width=True, hide_index=True)
            download_buttons(t8, stem=stem + "_T8_mandate", key_prefix="t8", sheet_name="Table 8")

        st.markdown("**Table 10 · Leading international partner countries, by disease-focus institute**")
        if t10.empty:
            st.caption("Needs an ‘All Country’ column to compute partner countries.")
        else:
            st.dataframe(t10, use_container_width=True, hide_index=True)
            download_buttons(t10, stem=stem + "_T10_partners", key_prefix="t10", sheet_name="Table 10")

    brand_footer()

st.markdown("---")
how_to_use([
    ("📤", "Upload a sheet with affiliations",
     "Any .xlsx/.csv that has affiliation text — usually a pipeline output or a curated Included_studies file."),
    ("🏷", "Pick the affiliation column(s)",
     "Select which columns hold affiliation text. If the file has an Author_Affiliation_Map column, keep that box ticked for best coverage."),
    ("▶️", "Run the tagging",
     "Click ‘Tag ICMR institutes’. The loader shows while affiliations are resolved to current institute names (handling former names & acronyms)."),
    ("📊", "Read the summary",
     "See how many rows have an institute, how many mention 2+, and the per-institute breakdown."),
    ("⬇️", "Download the tagged sheet",
     "A new ‘ICMR Institute (Current Name)’ column is added; download as CSV or Excel. "
     "If your sheet is enriched (has Citations etc.), Tables 3/4/5/8/10 appear above too."),
], preview_image=icmr_tagger_preview(),
   preview_caption="Affiliation columns this tool scans (download the template above)")
