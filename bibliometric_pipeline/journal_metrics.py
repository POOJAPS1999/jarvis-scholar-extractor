"""
journal_metrics.py
===================
Journal-level Impact Factor lookup, sourced from a real Clarivate Journal
Citation Reports (JCR) export Pooja provided (JCRI-mpact-Factors_2025.xlsx -
56,015 rows covering ~18,242 distinct journals by ISSN, deduplicated here
since JCR lists a journal once per subject category it's classified under -
confirmed the JIF/quartile are identical across a given journal's repeated
rows, so keeping the first is safe).

This is real data from Pooja's own JCR access, NOT scraped or estimated.

The reference CSV (journal_jif_reference.csv) lives at the project root, a
sibling of this bibliometric_pipeline package - see _REFERENCE_PATH below.
To refresh: replace that CSV with a new export (columns: ISSN, Journal_Name,
Publisher, JIF, Quartile) whenever Pooja gets an updated JCR file.
"""

import csv
import os
import sys
import threading

_REFERENCE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "journal_jif_reference.csv",
)

_lock = threading.Lock()
_cache = None  # dict: normalized ISSN -> (jif_str, quartile_str, journal_name)
_warned_missing = False


def _normalize_issn(s):
    if not s:
        return ""
    return str(s).strip().upper()


def _load():
    global _cache, _warned_missing
    with _lock:
        if _cache is not None:
            return _cache
        table = {}
        if not os.path.exists(_REFERENCE_PATH):
            if not _warned_missing:
                sys.stderr.write(
                    f"WARNING: journal_jif_reference.csv not found at {_REFERENCE_PATH} - "
                    f"Impact Factor / Quartile will be blank for every row. "
                    f"See journal_metrics.py docstring to restore it.\n"
                )
                _warned_missing = True
            _cache = table
            return _cache
        with open(_REFERENCE_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                issn = _normalize_issn(row.get("ISSN", ""))
                if not issn:
                    continue
                jif = (row.get("JIF") or "").strip()
                quartile = (row.get("Quartile") or "").strip()
                name = (row.get("Journal_Name") or "").strip()
                if issn not in table:
                    table[issn] = (jif, quartile, name)
        _cache = table
        return _cache


def lookup_jif(issn_field):
    """Given the pipeline's own 'ISSN' value for a row (a single ISSN, a
    semicolon-joined pair of print/online ISSNs, or blank), returns
    (jif_str, quartile_str) from the JCR reference table - tries each
    ISSN in the field in turn, returns the first match. Returns ("", "")
    if the field is blank or no ISSN in it matches the reference table -
    blank means "not found in this JCR export", never "confirmed no
    Impact Factor", consistent with this pipeline's blank convention
    throughout."""
    if not issn_field:
        return "", ""
    table = _load()
    if not table:
        return "", ""
    for raw in str(issn_field).split(";"):
        issn = _normalize_issn(raw)
        if issn in table:
            jif, quartile, _name = table[issn]
            return jif, quartile
    return "", ""
