"""
converters.py
=============
Bibliographic-format converters used by the standalone dashboard tools:

  - medline_to_dataframe(): PubMed .txt / .nbib (MEDLINE tag-per-line) -> DataFrame
  - ris_to_dataframe():      RIS (.ris / .txt) -> DataFrame

Both deliberately lean on well-tested third-party parsers rather than a
hand-rolled tag reader:
  - MEDLINE via Biopython's Bio.Medline.parse (handles PMID-, TI  -, AB  -,
    AU  -, multi-line continuation, repeated tags, etc.)
  - RIS via rispy.load (handles TY/TI/AU/PY/DO/ER and RIS's list-vs-scalar
    tag semantics)

Each returns TWO things bundled into one DataFrame's worth of columns:
  1. A rich set of human-readable bibliographic columns (PMID, Title,
     Authors, Year, Journal, DOI, Abstract, ...).
  2. The three pipeline-ready columns `Sno`, `Clean Title`, `DOI` up front,
     so the converted file can be fed straight into Jarvis Scholar's main
     enrichment pipeline with no manual column remapping.

These functions are import-safe (no Streamlit dependency) so they can be
unit-tested directly.
"""
from __future__ import annotations

import io
import re
from typing import List

import pandas as pd


# The three columns the main enrichment pipeline requires, in order.
PIPELINE_COLUMNS = ["Sno", "Clean Title", "DOI"]


def _as_text(file_or_bytes) -> str:
    """Accept a path, bytes, a file-like object, or a str and return text."""
    if isinstance(file_or_bytes, str) and "\n" not in file_or_bytes and len(file_or_bytes) < 1024:
        # Looks like a path
        try:
            with open(file_or_bytes, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except (OSError, ValueError):
            return file_or_bytes
    if isinstance(file_or_bytes, str):
        return file_or_bytes
    if isinstance(file_or_bytes, (bytes, bytearray)):
        return bytes(file_or_bytes).decode("utf-8", errors="replace")
    # file-like
    data = file_or_bytes.read()
    if isinstance(data, (bytes, bytearray)):
        return data.decode("utf-8", errors="replace")
    return data


# ---------------------------------------------------------------------
# MEDLINE (PubMed .txt / .nbib)
# ---------------------------------------------------------------------
_DOI_AID_RE = re.compile(r"^(?P<doi>10\.\S+)\s*\[doi\]\s*$", re.IGNORECASE)


def _doi_from_medline(rec: dict) -> str:
    """Pull a DOI out of a MEDLINE record. DOIs live in the AID (Article
    Identifier) tag, suffixed ' [doi]', and/or the LID (Location ID) tag.
    Both can be a single string or a list of strings depending on how many
    identifiers the record carries."""
    candidates: List[str] = []
    for key in ("AID", "LID"):
        val = rec.get(key)
        if not val:
            continue
        if isinstance(val, str):
            candidates.append(val)
        else:
            candidates.extend(val)
    for c in candidates:
        m = _DOI_AID_RE.match(c.strip())
        if m:
            return m.group("doi").strip()
    # Fallback: any '10.xxxx [doi]' fragment anywhere in the candidates
    for c in candidates:
        m = re.search(r"(10\.\S+?)\s*\[doi\]", c, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _authors_from_medline(rec: dict) -> str:
    au = rec.get("AU") or rec.get("FAU") or []
    if isinstance(au, str):
        au = [au]
    return "; ".join(a.strip() for a in au if a and a.strip())


def _parse_medline(text: str) -> List[dict]:
    """Pure-Python MEDLINE parser (no Biopython / no C extensions — Biopython
    was pulling native code that segfaulted the Streamlit Cloud container).

    MEDLINE format: each line is 'TAG - value' where TAG is left-justified in
    the first 4 columns and the separator '- ' sits at columns 4-5.
    Continuation lines for a long value are indented with spaces and carry no
    tag. A blank line ends a record. Repeated tags (AU, MH, AID, IS, ...)
    collect into a list, matching Biopython's Bio.Medline.parse output shape,
    so the downstream field-mapping is unchanged.
    """
    records: List[dict] = []
    cur: dict = {}
    last_key = None

    def _add(d, key, val):
        if key in d:
            if isinstance(d[key], list):
                d[key].append(val)
            else:
                d[key] = [d[key], val]
        else:
            d[key] = val

    for line in text.splitlines():
        if not line.strip():
            if cur:
                records.append(cur)
                cur, last_key = {}, None
            continue
        # A tag line has a non-blank 4-char tag and '- ' at columns 4-5.
        if len(line) >= 6 and line[4:6] == "- " and line[:4].strip():
            key = line[:4].strip()
            val = line[6:].strip()
            _add(cur, key, val)
            last_key = key
        elif last_key is not None:
            # continuation of the previous value
            add = line.strip()
            if isinstance(cur[last_key], list):
                cur[last_key][-1] = f"{cur[last_key][-1]} {add}".strip()
            else:
                cur[last_key] = f"{cur[last_key]} {add}".strip()
    if cur:
        records.append(cur)
    return records


def medline_to_dataframe(file_or_bytes) -> pd.DataFrame:
    """Parse a PubMed MEDLINE-format export into a DataFrame.

    Accepts a path, bytes, str, or file-like object. Returns a DataFrame
    with pipeline columns (Sno, Clean Title, DOI) first, then rich
    bibliographic columns.
    """
    text = _as_text(file_or_bytes)
    records = _parse_medline(text)

    rows = []
    for i, rec in enumerate(records, start=1):
        title = _scalar(rec.get("TI"))
        rows.append({
            "Sno": i,
            "Clean Title": title,
            "DOI": _doi_from_medline(rec),
            "PMID": _scalar(rec.get("PMID")),
            "Title": title,
            "Authors": _authors_from_medline(rec),
            "Journal": _scalar(rec.get("JT")) or _scalar(rec.get("TA")),
            "Year": _year_from_medline(rec),
            "Volume": _scalar(rec.get("VI")),
            "Issue": _scalar(rec.get("IP")),
            "Pages": _scalar(rec.get("PG")),
            "Abstract": _scalar(rec.get("AB")),
            "MeSH Terms": _join_list(rec.get("MH")),
            "Publication Type": _join_list(rec.get("PT")),
            "ISSN": _scalar(rec.get("IS")),
        })

    if not rows:
        return pd.DataFrame(columns=PIPELINE_COLUMNS + [
            "PMID", "Title", "Authors", "Journal", "Year", "Volume", "Issue",
            "Pages", "Abstract", "MeSH Terms", "Publication Type", "ISSN"])

    df = pd.DataFrame(rows)
    return _reorder_pipeline_first(df)


def _scalar(v) -> str:
    """Return a single stripped string from a MEDLINE field that may be a
    string, a list (repeated tag, e.g. multiple ISSNs), or None. Takes the
    first element of a list."""
    if v is None:
        return ""
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v).strip()


def _year_from_medline(rec: dict) -> str:
    # DP (Date of Publication), e.g. "2021 Mar 15" or "2021"; also try DEP/EDAT
    for key in ("DP", "DEP", "EDAT", "PHST"):
        val = rec.get(key)
        if not val:
            continue
        if isinstance(val, list):
            val = val[0]
        m = re.search(r"(19|20)\d{2}", str(val))
        if m:
            return m.group(0)
    return ""


def _join_list(val) -> str:
    if not val:
        return ""
    if isinstance(val, str):
        return val.strip()
    return "; ".join(str(v).strip() for v in val if str(v).strip())


# ---------------------------------------------------------------------
# RIS
# ---------------------------------------------------------------------
def _first(rec: dict, *keys) -> str:
    for k in keys:
        v = rec.get(k)
        if v:
            if isinstance(v, list):
                v = "; ".join(str(x).strip() for x in v if str(x).strip())
            return str(v).strip()
    return ""


def ris_to_dataframe(file_or_bytes) -> pd.DataFrame:
    """Parse an RIS-format export into a DataFrame.

    Accepts a path, bytes, str, or file-like object. Returns a DataFrame
    with pipeline columns (Sno, Clean Title, DOI) first, then rich
    bibliographic columns.
    """
    import rispy

    text = _as_text(file_or_bytes)
    try:
        entries = rispy.loads(text)
    except Exception:
        # rispy is occasionally strict about leading BOM/whitespace; retry cleaned
        entries = rispy.loads(text.lstrip("﻿ \r\n"))

    rows = []
    for i, rec in enumerate(entries, start=1):
        title = _first(rec, "title", "primary_title", "translated_title")
        authors = rec.get("authors") or rec.get("first_authors") or []
        if isinstance(authors, str):
            authors = [authors]
        rows.append({
            "Sno": i,
            "Clean Title": title,
            "DOI": _first(rec, "doi").replace("https://doi.org/", "").strip(),
            "Type": _first(rec, "type_of_reference"),
            "Title": title,
            "Authors": "; ".join(a.strip() for a in authors if a and a.strip()),
            "Journal": _first(rec, "journal_name", "secondary_title",
                              "alternate_title1", "alternate_title2", "alternate_title3"),
            "Year": _year_from_ris(rec),
            "Volume": _first(rec, "volume"),
            "Issue": _first(rec, "number", "issue"),
            "Pages": _pages_from_ris(rec),
            "Abstract": _first(rec, "abstract"),
            "Keywords": _join_list(rec.get("keywords")),
            "ISSN": _first(rec, "issn"),
            "URL": _first(rec, "urls", "url"),
        })

    cols = PIPELINE_COLUMNS + [
        "Type", "Title", "Authors", "Journal", "Year", "Volume", "Issue",
        "Pages", "Abstract", "Keywords", "ISSN", "URL"]
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows)
    return _reorder_pipeline_first(df)


def _year_from_ris(rec: dict) -> str:
    for key in ("year", "publication_year", "date"):
        v = rec.get(key)
        if v:
            m = re.search(r"(19|20)\d{2}", str(v))
            if m:
                return m.group(0)
    return ""


def _pages_from_ris(rec: dict) -> str:
    sp = _first(rec, "start_page")
    ep = _first(rec, "end_page")
    if sp and ep:
        return f"{sp}-{ep}"
    return sp or ep or ""


# ---------------------------------------------------------------------
def _reorder_pipeline_first(df: pd.DataFrame) -> pd.DataFrame:
    front = [c for c in PIPELINE_COLUMNS if c in df.columns]
    rest = [c for c in df.columns if c not in front]
    return df[front + rest]
