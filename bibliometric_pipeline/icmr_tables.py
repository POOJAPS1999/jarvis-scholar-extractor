"""
icmr_tables.py
==============
Auto-generate the ICMR-specific bibliometric tables from a tagged + enriched
dataset — the same tables in Pooja's ICMR Bibliometric Results document:

  Table 3  institute_benchmarking()          institute-level metrics
  Table 4  division_summary()                 publications by inferred HQ division
  Table 5  leadership_vs_contribution()       led vs contributed, by institute
  Table 8  mandate_fidelity()                 topic alignment to institute vision
  Table 10 international_partners_by_institute()  top partner countries by focus area

Ported (and de-coupled from matplotlib/docx) from the ICMR fork's
generate_icmr_impact_report.py, so the logic is the exact same as the one
that produced the reference document. Returns plain pandas DataFrames.

Requires an input dataset that has an ICMR institute column (produced by the
ICMR Institute Tagger) PLUS the usual enriched columns (Citations, Open
Access, Collaboration Type, Corresponding/Any Author from ICMR, All Country,
MeSH/keywords). Columns that aren't present are simply skipped.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

import pandas as pd

from .icmr_institute_reference_data import (
    VISIONS, DISEASE_FOCUS_KEYWORDS, INSTITUTE_DIVISION,
)

HQ_LABEL = "ICMR Headquarters, New Delhi (not a constituent institute)"
CCOE_LABEL = "ICMR Collaborating Centre of Excellence (external partner institution, not one of the 28 core institutes)"

_INSTITUTE_COLS = [
    "ICMR Institute (Current Name)", "ICMR Institute (Current Name) (New)",
    "ICMR Institute", "INSTITUTE",
]


# ---------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------
def _blank(v):
    return (v is None or (isinstance(v, float) and pd.isna(v))
            or str(v).strip() == "" or str(v).strip().lower() == "nan")


def _split_institutes(cell):
    if _blank(cell):
        return []
    return [s.strip() for s in str(cell).split(";") if s.strip()]


def _short_name(full):
    if full == HQ_LABEL:
        return "ICMR HQ"
    if full == CCOE_LABEL:
        return "ICMR CCoE"
    m = re.match(r"ICMR-?(.*?),\s*([A-Za-z .']+)$", str(full))
    if not m:
        return full
    rest, city = m.groups()
    words = [w for w in re.split(r"[\s\-]", rest) if w and w.lower() not in ("of", "and", "for", "the", "in", "on")]
    acr = "".join(w[0].upper() for w in words if w[0].isalpha())
    return f"ICMR-{acr}, {city.strip()}"


def _parse_aff_map(raw):
    if _blank(raw):
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _institute_col(df):
    for c in _INSTITUTE_COLS:
        if c in df.columns:
            return c
    return None


def has_required(df) -> bool:
    """True if the dataset can produce ICMR tables (institute col + citations)."""
    return _institute_col(df) is not None and "Citations" in df.columns


# ---------------------------------------------------------------------
# JIF lookup (optional — journal_jif_reference.csv at the project root)
# ---------------------------------------------------------------------
_JIF_TABLE = None
_JIF_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "journal_jif_reference.csv")


def _load_jif_table():
    global _JIF_TABLE
    if _JIF_TABLE is not None:
        return _JIF_TABLE
    if not os.path.exists(_JIF_PATH):
        _JIF_TABLE = {}
        return _JIF_TABLE
    try:
        ref = pd.read_csv(_JIF_PATH)
        ref["ISSN"] = ref["ISSN"].astype(str).str.strip().str.upper()
        _JIF_TABLE = {r.ISSN: r.JIF for r in ref.itertuples() if r.ISSN and r.ISSN != "NAN"}
    except Exception:
        _JIF_TABLE = {}
    return _JIF_TABLE


def _lookup_jif(issn_field):
    if _blank(issn_field):
        return float("nan")
    table = _load_jif_table()
    for raw in str(issn_field).split(";"):
        key = raw.strip().upper()
        if key in table:
            try:
                return float(table[key])
            except (TypeError, ValueError):
                return float("nan")
    return float("nan")


# ---------------------------------------------------------------------
# Country cleaning (for Table 10) — ported verbatim in behaviour
# ---------------------------------------------------------------------
try:
    import pycountry
    _COUNTRY_LOOKUP = {}
    for _c in pycountry.countries:
        for _nm in filter(None, [getattr(_c, "name", None), getattr(_c, "common_name", None),
                                 getattr(_c, "official_name", None)]):
            _COUNTRY_LOOKUP[_nm.strip().lower()] = _nm
    _HAVE_PYCOUNTRY = True
except Exception:
    pycountry = None
    _COUNTRY_LOOKUP = {}
    _HAVE_PYCOUNTRY = False

_ALIASES = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "south korea": "South Korea", "korea, republic of": "South Korea", "republic of korea": "South Korea",
    "russia": "Russia", "russian federation": "Russia",
    "turkiye": "Turkiye", "turkey": "Turkiye", "türkiye": "Turkiye",
    "vietnam": "Vietnam", "viet nam": "Vietnam", "iran": "Iran", "iran, islamic republic of": "Iran",
    "czechia": "Czechia", "czech republic": "Czechia", "hong kong": "Hong Kong",
    "taiwan": "Taiwan", "taiwan, province of china": "Taiwan",
    "democratic republic of the congo": "DR Congo", "burma": "Myanmar", "myanmar": "Myanmar",
    "syria": "Syria", "syrian arab republic": "Syria", "laos": "Laos",
    "tanzania": "Tanzania", "tanzania, united republic of": "Tanzania",
    "moldova": "Moldova", "moldova, republic of": "Moldova",
    "bolivia": "Bolivia", "venezuela": "Venezuela",
    "north macedonia": "North Macedonia", "macedonia": "North Macedonia",
    "eswatini": "Eswatini", "swaziland": "Eswatini",
    "cape verde": "Cabo Verde", "cabo verde": "Cabo Verde",
    "ivory coast": "Ivory Coast", "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "brunei": "Brunei", "brunei darussalam": "Brunei",
    "palestine": "Palestine", "palestine, state of": "Palestine",
    "bosnia": "Bosnia and Herzegovina", "bosnia and herzegovina": "Bosnia and Herzegovina",
}
for _k, _v in _ALIASES.items():
    _COUNTRY_LOOKUP.setdefault(_k, _v)
_SORTED_KEYS = sorted(_COUNTRY_LOOKUP.keys(), key=len, reverse=True)


def _resolve_country_token(t):
    tt = t.strip()
    key = tt.lower().rstrip(".")
    if key in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[key]
    bare = tt.rstrip(".")
    if len(bare) == 2 and bare.isalpha() and _HAVE_PYCOUNTRY:
        c = pycountry.countries.get(alpha_2=bare.upper())
        if c:
            return _ALIASES.get(c.name.strip().lower(), c.name)
    lead = tt.split(".")[0].strip().lower()
    if lead in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[lead]
    low = " " + re.sub(r"[^a-z0-9 ]", " ", tt.lower()) + " "
    for k in _SORTED_KEYS:
        if len(k) < 3:
            continue
        if f" {k} " in low:
            return _COUNTRY_LOOKUP[k]
    return None


def clean_country_cell(cell):
    if _blank(cell):
        return []
    out = []
    for t in [x.strip() for x in str(cell).split(";") if x.strip()]:
        r = _resolve_country_token(t)
        if r and r not in out:
            out.append(r)
    return out


# ---------------------------------------------------------------------
# Prepare + explode
# ---------------------------------------------------------------------
def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    icol = _institute_col(df)
    if icol is None:
        raise ValueError("No ICMR institute column found — run the ICMR Institute Tagger first.")
    df["Citations"] = pd.to_numeric(df.get("Citations"), errors="coerce")
    df["_inst_list"] = df[icol].apply(_split_institutes)
    if "ISSN" in df.columns:
        df["_jif"] = df["ISSN"].apply(_lookup_jif)
    else:
        df["_jif"] = float("nan")
    return df


def _exploded(df, include_hq_ccoe=True):
    ex = df.explode("_inst_list")
    ex = ex[ex["_inst_list"].notna() & (ex["_inst_list"] != "")]
    if include_hq_ccoe:
        return ex.copy()
    return ex[~ex["_inst_list"].isin([HQ_LABEL, CCOE_LABEL])].copy()


def _h_index(cits):
    s = sorted((c for c in cits if pd.notna(c)), reverse=True)
    h = 0
    for i, c in enumerate(s, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


# ---------------------------------------------------------------------
# Table 3 — institute benchmarking
# ---------------------------------------------------------------------
def institute_benchmarking(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    df = prepare(df)
    ex = _exploded(df, include_hq_ccoe=True)
    if not len(ex):
        return pd.DataFrame()

    has_oa = "Open Access" in df.columns
    has_collab = "Collaboration Type (National/International)" in df.columns

    rows = []
    for inst, g in ex.groupby("_inst_list"):
        c = g["Citations"]
        row = {
            "ICMR Institute": inst,
            "Short Name": _short_name(inst),
            "Publications": len(g),
            "Total Citations": int(c.fillna(0).sum()),
            "Mean Citations": round(c.mean(), 2) if c.notna().any() else 0.0,
            "Median Citations": c.median() if c.notna().any() else 0.0,
            "Highly Cited (≥10)": int((c >= 10).sum()),
            "h-index": _h_index(c.tolist()),
        }
        if has_oa:
            oa = g["Open Access"].dropna().astype(str)
            row["OA Share %"] = round((oa.str.lower() == "yes").mean() * 100, 1) if len(oa) else 0.0
        if has_collab:
            cl = g["Collaboration Type (National/International)"].dropna().astype(str)
            row["International %"] = round((cl.str.lower() == "international").mean() * 100, 1) if len(cl) else 0.0
        if g["_jif"].notna().any():
            row["Mean JIF"] = round(g["_jif"].mean(), 2)
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("Publications", ascending=False).head(top_n).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------
# Table 4 — publications by inferred ICMR HQ scientific division
# ---------------------------------------------------------------------
def division_summary(df: pd.DataFrame):
    bench = institute_benchmarking(df, top_n=10_000)
    pub_by_inst = dict(zip(bench["ICMR Institute"], bench["Publications"])) if len(bench) else {}
    ref_rows = []
    for inst, val in INSTITUTE_DIVISION.items():
        division = val[0] if isinstance(val, (list, tuple)) else val
        rationale = val[1] if isinstance(val, (list, tuple)) and len(val) > 1 else ""
        ref_rows.append({
            "Institute": inst, "Short Name": _short_name(inst),
            "Inferred HQ Division": division,
            "Publications": int(pub_by_inst.get(inst, 0)),
            "Rationale": rationale,
        })
    ref = pd.DataFrame(ref_rows).sort_values("Publications", ascending=False).reset_index(drop=True)
    summary = ref.groupby("Inferred HQ Division").agg(
        Publications=("Publications", "sum"), Institutes=("Institute", "count")
    ).reset_index().sort_values("Publications", ascending=False).reset_index(drop=True)
    return summary, ref


# ---------------------------------------------------------------------
# Table 5 — leadership vs contribution
# ---------------------------------------------------------------------
def leadership_vs_contribution(df: pd.DataFrame, top_n: int = 15):
    if "Corresponding Author from ICMR" not in df.columns or "Any Author from ICMR" not in df.columns:
        return pd.DataFrame(), {}
    df = prepare(df)
    ex = _exploded(df, include_hq_ccoe=True)
    if not len(ex):
        return pd.DataFrame(), {}

    def led_status(row):
        if str(row.get("Corresponding Author from ICMR", "")).strip() == "Yes":
            return "Led (ICMR corresponding author)"
        if str(row.get("Any Author from ICMR", "")).strip() == "Yes":
            return "Contributed (ICMR co-author only)"
        return "Unclear/blank"

    ex["_led"] = ex.apply(led_status, axis=1)
    overall = ex["_led"].value_counts().to_dict()
    by = ex.groupby("_inst_list")["_led"].value_counts().unstack(fill_value=0)
    by["Total"] = by.sum(axis=1)
    led_col = "Led (ICMR corresponding author)"
    by["Led %"] = (by.get(led_col, 0) / by["Total"] * 100).round(1)
    by = by.reset_index().rename(columns={"_inst_list": "ICMR Institute"})
    by["Short Name"] = by["ICMR Institute"].apply(_short_name)
    by = by.sort_values("Total", ascending=False).head(top_n).reset_index(drop=True)
    return by, overall


# ---------------------------------------------------------------------
# Table 8 — mandate fidelity
# ---------------------------------------------------------------------
_STOPWORDS = set("""a an the of and or to for in on with by from as is are be being been at into
that this these those it its their our your his her which who whom research health india national
public disease diseases centre center institute institutes excellence including through across""".split())


def _vocab_from_vision(text):
    return set(w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in _STOPWORDS)


def mandate_fidelity(df: pd.DataFrame, top_n: int = 15) -> pd.DataFrame:
    df = prepare(df)

    def topic_blob(row):
        parts = []
        for col in ("MeSH Terms", "Author Keywords (Other Terms)", "Concepts", "TITLE", "Abstract"):
            v = row.get(col, "")
            if not _blank(v):
                parts.append(str(v))
        return " ".join(parts).lower()

    df["_topic_blob"] = df.apply(topic_blob, axis=1)
    rows = []
    for inst, vision in VISIONS.items():
        mask = df["_inst_list"].apply(lambda l: inst in l)
        n = int(mask.sum())
        if n == 0:
            continue
        vocab = _vocab_from_vision(vision)
        sub = df.loc[mask]
        matched = int(sub["_topic_blob"].apply(lambda t: any(w in t for w in vocab)).sum())
        rows.append({
            "Institute": inst, "Short Name": _short_name(inst), "Papers": n,
            "Vision Vocabulary Size": len(vocab), "Mandate-Aligned Papers": matched,
            "Mandate Fidelity %": round(matched / n * 100, 1),
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Mandate Fidelity %", ascending=False).head(top_n).reset_index(drop=True)


# ---------------------------------------------------------------------
# Table 10 — leading international partner countries, by disease-focus institute
# ---------------------------------------------------------------------
def international_partners_by_institute(df: pd.DataFrame, per_institute: int = 6) -> pd.DataFrame:
    if "All Country" not in df.columns:
        return pd.DataFrame(columns=["Focus Area", "Institute", "Partner Country", "Papers"])
    df = prepare(df)
    df["_clean_countries"] = df["All Country"].apply(clean_country_cell)
    df["_n_countries"] = df["_clean_countries"].apply(lambda l: len(set(l)))
    typical = df[df["_n_countries"] <= 15]  # drop mega-consortium papers

    rows = []
    for label, spec in DISEASE_FOCUS_KEYWORDS.items():
        inst = spec[0] if isinstance(spec, (list, tuple)) else spec
        mask = df["_inst_list"].apply(lambda l: inst in l)
        idx = typical.index.intersection(df[mask].index)
        countries = []
        for lst in typical.loc[idx, "_clean_countries"]:
            countries.extend([c for c in lst if c != "India"])
        if not countries:
            continue
        for country, cnt in Counter(countries).most_common(per_institute):
            rows.append({
                "Focus Area": label, "Institute": _short_name(inst),
                "Partner Country": country, "Papers": int(cnt),
            })
    return pd.DataFrame(rows, columns=["Focus Area", "Institute", "Partner Country", "Papers"])
