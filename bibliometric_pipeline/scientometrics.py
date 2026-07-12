"""
scientometrics.py
=================
Pure-logic scientometric analysis over an enriched bibliometric dataset —
the engine behind the "Scientometrics Visualization" tool. Biblioshiny /
VOSviewer-style tables and the numbers behind the charts.

Design goals:
  - GENERIC: works on any Jarvis Scholar enriched output by auto-detecting
    the relevant columns (journal, year, citations, authors, references,
    countries, keywords). ICMR-specific columns are used only when present.
  - No Streamlit / plotting imports here — everything returns plain pandas
    objects so it's unit-testable and the UI layer decides how to render.

Phase 1 covers: dataset overview, missing-data, annual production, annual
citations, Bradford's law, most-relevant sources, sources by h-index,
top-cited records, most locally-cited references.
"""
from __future__ import annotations

import re
from typing import List, Optional

import pandas as pd


# ---------------------------------------------------------------------
# Column resolution — map many possible header names to one logical field
# ---------------------------------------------------------------------
_COLUMN_ALIASES = {
    "year": ["YEAR", "Year", "Publication Year", "PY"],
    "journal": ["Journal name", "Journal", "Source title", "Source", "JT"],
    "citations": ["Citations", "Cited by", "Times Cited", "TC"],
    "n_authors": ["Number of Authors", "Author Count", "Num Authors"],
    "authors": ["Authors", "Author(s)", "AU"],
    "ref_count": ["Reference Count", "Number of References", "NR"],
    "references": ["References", "Cited References", "CR"],
    "countries": ["All Country", "Countries", "Country", "Corresponding Author Country"],
    "oa": ["Open Access", "OA", "Access Type"],
    "article_type": ["Article Type", "Document Type", "PRISMA Type Classification", "DT"],
    "multi_inst": ["Multi Institution", "Multi-Institution", "Multi Institutional"],
    "collab_type": ["Collaboration Type (National/International)",
                    "Collaboration Type", "International Collaboration"],
    "author_keywords": ["Author Keywords (Other Terms)", "Author Keywords", "DE"],
    "mesh": ["MeSH Terms", "Index Keywords", "ID"],
    "title": ["TITLE", "Title", "Clean Title", "TI"],
    "doi": ["DOI", "doi"],
    "grants": ["Grants", "Funding Details", "Funding"],
}


def find_col(df: pd.DataFrame, logical: str) -> Optional[str]:
    """Return the actual column name in df for a logical field, or None."""
    cands = _COLUMN_ALIASES.get(logical, [logical])
    for c in cands:
        if c in df.columns:
            return c
    low = {str(x).strip().lower(): x for x in df.columns}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def _num(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _nonblank(series) -> pd.Series:
    s = series.astype(str).str.strip()
    return s[(s != "") & (s.str.lower() != "nan")]


def _year_series(df) -> pd.Series:
    col = find_col(df, "year")
    if not col:
        return pd.Series([], dtype="float64")
    # pull a 4-digit year out of whatever's in the cell
    yr = df[col].astype(str).str.extract(r"((?:19|20)\d{2})")[0]
    return _num(yr)


def _yes(series) -> pd.Series:
    """Boolean mask for 'Yes'/'True'/'Y'/'1'-style cells."""
    s = series.astype(str).str.strip().str.lower()
    return s.isin(["yes", "y", "true", "1", "open", "gold", "green", "hybrid", "bronze"])


# ---------------------------------------------------------------------
# 1. Dataset overview  (Biblioshiny "Main information" / your Table 1)
# ---------------------------------------------------------------------
def dataset_overview(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    rows = []

    def add(desc, val):
        rows.append({"Description": desc, "Value": val})

    def pct(k):
        return f"{k:,} ({(k / n * 100):.1f}%)" if n else "0"

    years = _year_series(df).dropna()
    if len(years):
        add("Timespan", f"{int(years.min())}–{int(years.max())}")

    jcol = find_col(df, "journal")
    if jcol:
        add("Journals / sources", f"{_nonblank(df[jcol]).nunique():,}")

    add("Documents", f"{n:,}")

    ccol = find_col(df, "citations")
    if ccol:
        cits = _num(df[ccol]).fillna(0)
        add("Average citations per document", f"{(cits.sum() / n):.2f}" if n else "0")
        add("Total citations", f"{int(cits.sum()):,}")

    rcol = find_col(df, "ref_count")
    if rcol:
        add("References cited", f"{int(_num(df[rcol]).fillna(0).sum()):,}")

    acol = find_col(df, "n_authors")
    if acol:
        na = _num(df[acol]).dropna()
        if len(na):
            add("Mean authors per document", f"{na.mean():.1f} (median {na.median():.0f})")
            add("Single-authored documents", pct(int((na == 1).sum())))

    mcol = find_col(df, "multi_inst")
    if mcol:
        add("Multi-institutional documents", pct(int(_yes(df[mcol]).sum())))

    colc = find_col(df, "collab_type")
    if colc:
        classified = _nonblank(df[colc])
        intl = classified.astype(str).str.contains("international", case=False).sum()
        if len(classified):
            add("International co-authorship",
                f"{int(intl):,} / {len(classified):,} classified ({intl / len(classified) * 100:.1f}%)")

    ocol = find_col(df, "oa")
    if ocol:
        add("Open access documents", pct(int(_yes(df[ocol]).sum())))

    atcol = find_col(df, "article_type")
    if atcol:
        at = df[atcol].astype(str).str.lower()
        orig = at.str.contains("article|original|research").sum()
        add("Original research articles", pct(int(orig)))

    return pd.DataFrame(rows, columns=["Description", "Value"])


# ---------------------------------------------------------------------
# 2. Missing-data table (Biblioshiny "Missing Data")
# ---------------------------------------------------------------------
def missing_data(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    fields = [
        ("DOI", "doi"), ("Title", "title"), ("Authors", "authors"),
        ("Journal / source", "journal"), ("Publication year", "year"),
        ("Citations", "citations"), ("References", "references"),
        ("Author keywords", "author_keywords"), ("Index/MeSH keywords", "mesh"),
        ("Country", "countries"), ("Article type", "article_type"),
    ]
    rows = []
    for label, logical in fields:
        col = find_col(df, logical)
        if not col:
            missing = n
        else:
            present = len(_nonblank(df[col]))
            missing = n - present
        status = "Excellent" if missing == 0 else (
            "Good" if missing / n <= 0.10 else (
                "Acceptable" if missing / n <= 0.50 else "Poor")) if n else "—"
        rows.append({
            "Field": label,
            "Missing": f"{missing:,}",
            "Missing %": f"{(missing / n * 100):.1f}%" if n else "—",
            "Status": status,
        })
    return pd.DataFrame(rows, columns=["Field", "Missing", "Missing %", "Status"])


# ---------------------------------------------------------------------
# 3 & 4. Annual production and annual citations
# ---------------------------------------------------------------------
def annual_production(df: pd.DataFrame) -> pd.DataFrame:
    years = _year_series(df).dropna().astype(int)
    if not len(years):
        return pd.DataFrame(columns=["Year", "Documents"])
    out = years.value_counts().sort_index().rename_axis("Year").reset_index(name="Documents")
    return out


def annual_citations(df: pd.DataFrame) -> pd.DataFrame:
    ycol = find_col(df, "year")
    ccol = find_col(df, "citations")
    if not (ycol and ccol):
        return pd.DataFrame(columns=["Year", "Total Citations", "Mean Citations"])
    tmp = pd.DataFrame({"Year": _year_series(df), "Cites": _num(df[ccol]).fillna(0)}).dropna(subset=["Year"])
    tmp["Year"] = tmp["Year"].astype(int)
    g = tmp.groupby("Year")["Cites"]
    out = pd.DataFrame({"Total Citations": g.sum().astype(int), "Mean Citations": g.mean().round(2)})
    return out.reset_index()


# ---------------------------------------------------------------------
# 5. Most relevant sources
# ---------------------------------------------------------------------
def most_relevant_sources(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    jcol = find_col(df, "journal")
    if not jcol:
        return pd.DataFrame(columns=["Source", "Documents"])
    s = _nonblank(df[jcol])
    out = s.value_counts().head(n).rename_axis("Source").reset_index(name="Documents")
    return out


# ---------------------------------------------------------------------
# 6. Bradford's law of scattering
# ---------------------------------------------------------------------
def bradford(df: pd.DataFrame) -> pd.DataFrame:
    jcol = find_col(df, "journal")
    if not jcol:
        return pd.DataFrame(columns=["Rank", "Source", "Documents", "Cumulative", "Zone"])
    counts = _nonblank(df[jcol]).value_counts()
    total = int(counts.sum())
    third = total / 3.0 if total else 0
    rows, cum = [], 0
    for rank, (src, docs) in enumerate(counts.items(), start=1):
        cum += int(docs)
        zone = 1 if cum <= third else (2 if cum <= 2 * third else 3)
        rows.append({"Rank": rank, "Source": src, "Documents": int(docs),
                     "Cumulative": cum, "Zone": f"Zone {zone}"})
    return pd.DataFrame(rows, columns=["Rank", "Source", "Documents", "Cumulative", "Zone"])


# ---------------------------------------------------------------------
# 7. Sources — local impact by h-index
# ---------------------------------------------------------------------
def _h_index(citations: List[int]) -> int:
    cs = sorted((int(c) for c in citations), reverse=True)
    h = 0
    for i, c in enumerate(cs, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def sources_h_index(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    jcol = find_col(df, "journal")
    ccol = find_col(df, "citations")
    if not (jcol and ccol):
        return pd.DataFrame(columns=["Source", "h-index", "Documents", "Total Citations"])
    cols = ["Source", "h-index", "Documents", "Total Citations"]
    tmp = pd.DataFrame({"J": df[jcol].astype(str).str.strip(), "C": _num(df[ccol]).fillna(0)})
    tmp = tmp[(tmp["J"] != "") & (tmp["J"].str.lower() != "nan")]
    rows = []
    for src, grp in tmp.groupby("J"):
        rows.append({
            "Source": src,
            "h-index": _h_index(grp["C"].tolist()),
            "Documents": len(grp),
            "Total Citations": int(grp["C"].sum()),
        })
    if not rows:
        return pd.DataFrame(columns=cols)
    out = pd.DataFrame(rows).sort_values(
        ["h-index", "Total Citations"], ascending=False).head(n).reset_index(drop=True)
    return out


# ---------------------------------------------------------------------
# 8. Top-cited individual records
# ---------------------------------------------------------------------
def top_cited(df: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    ccol = find_col(df, "citations")
    tcol = find_col(df, "title")
    jcol = find_col(df, "journal")
    if not ccol:
        return pd.DataFrame(columns=["Title", "Journal", "Year", "Citations", "DOI"])
    if not len(df):
        return pd.DataFrame(columns=["Title", "Journal", "Year", "Citations", "DOI"])
    out = pd.DataFrame({
        "Title": df[tcol].astype(str) if tcol else "",
        "Journal": df[jcol].astype(str) if jcol else "",
        "Year": _year_series(df).astype("Int64"),
        "Citations": _num(df[ccol]).fillna(0).astype(int),
        "DOI": df[find_col(df, "doi")].astype(str) if find_col(df, "doi") else "",
    })
    return out.sort_values("Citations", ascending=False).head(n).reset_index(drop=True)


# ---------------------------------------------------------------------
# 9. Most locally-cited references
# ---------------------------------------------------------------------
def _normalize_reference(ref: str) -> str:
    r = re.sub(r"\s+", " ", str(ref).strip()).strip(" .;,")
    return r


def most_local_cited_references(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    rcol = find_col(df, "references")
    if not rcol:
        return pd.DataFrame(columns=["Reference", "Local Citations"])
    from collections import Counter
    ctr: Counter = Counter()
    for cell in df[rcol].dropna():
        for ref in str(cell).split(";"):
            ref = _normalize_reference(ref)
            if len(ref) >= 8:  # skip junk fragments
                ctr[ref] += 1
    if not ctr:
        return pd.DataFrame(columns=["Reference", "Local Citations"])
    out = pd.DataFrame(ctr.most_common(n), columns=["Reference", "Local Citations"])
    return out
