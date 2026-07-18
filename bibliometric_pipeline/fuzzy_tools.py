"""
fuzzy_tools.py
==============
Standalone fuzzy title-matching orchestration, reusing the ALREADY-HARDENED
matching primitives in text_utils (fuzzy_score + clean_for_match, including
the length-guard fix for the short-generic-candidate false positive).

Two modes:
  - cross_match(): two lists of titles -> best match in list B for each
    title in list A, above a threshold.
  - self_dedup(): one list -> clusters/pairs of near-duplicate titles within
    the same list.

Pure logic, no Streamlit dependency, so it can be unit-tested directly.
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .text_utils import fuzzy_score, clean_for_match


def _clean_series(values) -> List[str]:
    return [("" if v is None else str(v)) for v in values]


def cross_match(
    left_values,
    right_values,
    threshold: float = 85.0,
    left_ids: Optional[list] = None,
    right_ids: Optional[list] = None,
    label: str = "value",
) -> pd.DataFrame:
    """For each value in `left_values`, find its single best match in
    `right_values` and report the score. Works on ANY text field — titles,
    author names, affiliations, journals, DOIs, serial numbers, etc.

    Rows below `threshold` are still returned but marked unmatched (Matched =
    No) so the caller sees the full left list and what *didn't* match.

    Returns a DataFrame: A row, A <label>, Match row, Match <label>, Score, Matched.
    """
    lab = str(label).strip() or "value"
    left = _clean_series(left_values)
    right = _clean_series(right_values)
    left_ids = list(left_ids) if left_ids is not None else list(range(1, len(left) + 1))
    right_ids = list(right_ids) if right_ids is not None else list(range(1, len(right) + 1))

    # Pre-clean the right side once (not once per left value).
    right_clean = [clean_for_match(r) for r in right]

    rows = []
    for i, lt in enumerate(left):
        lt_clean = clean_for_match(lt)
        best_j, best_score = -1, -1.0
        if lt_clean:
            for j, rc in enumerate(right_clean):
                if not rc:
                    continue
                s = fuzzy_score(lt_clean, rc)
                if s > best_score:
                    best_score, best_j = s, j
        matched = best_j >= 0 and best_score >= threshold
        rows.append({
            "A row": left_ids[i],
            f"A {lab}": lt,
            "Match row": right_ids[best_j] if matched else "",
            f"Match {lab}": right[best_j] if matched else "",
            "Score": round(best_score, 1) if best_j >= 0 else 0.0,
            "Matched": "Yes" if matched else "No",
        })
    return pd.DataFrame(rows, columns=[
        "A row", f"A {lab}", "Match row", f"Match {lab}", "Score", "Matched"])


def self_dedup(values, threshold: float = 85.0, ids: Optional[list] = None,
               label: str = "value") -> pd.DataFrame:
    """Find near-duplicate pairs WITHIN a single list, on ANY text field.
    Compares every unique unordered pair once (i < j) and returns those
    scoring >= threshold, highest score first.

    Returns a DataFrame: A row, A <label>, B row, B <label>, Score.
    """
    lab = str(label).strip() or "value"
    vals = _clean_series(values)
    ids = list(ids) if ids is not None else list(range(1, len(vals) + 1))
    clean = [clean_for_match(v) for v in vals]

    rows = []
    n = len(vals)
    for i in range(n):
        if not clean[i]:
            continue
        for j in range(i + 1, n):
            if not clean[j]:
                continue
            s = fuzzy_score(clean[i], clean[j])
            if s >= threshold:
                rows.append({
                    "A row": ids[i], f"A {lab}": vals[i],
                    "B row": ids[j], f"B {lab}": vals[j],
                    "Score": round(s, 1),
                })
    df = pd.DataFrame(rows, columns=["A row", f"A {lab}", "B row", f"B {lab}", "Score"])
    if not df.empty:
        df = df.sort_values("Score", ascending=False, kind="stable").reset_index(drop=True)
    return df
