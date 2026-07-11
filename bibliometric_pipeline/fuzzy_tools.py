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
    left_titles,
    right_titles,
    threshold: float = 85.0,
    left_ids: Optional[list] = None,
    right_ids: Optional[list] = None,
) -> pd.DataFrame:
    """For each title in `left_titles`, find its single best match in
    `right_titles` and report the score. Rows below `threshold` are still
    returned but marked as unmatched (Best Match blank, Matched = No), so the
    caller sees the full left list and can see what *didn't* match.

    Returns a DataFrame: Left #, Left Title, Best Match #, Best Match Title,
    Score, Matched.
    """
    left = _clean_series(left_titles)
    right = _clean_series(right_titles)
    left_ids = list(left_ids) if left_ids is not None else list(range(1, len(left) + 1))
    right_ids = list(right_ids) if right_ids is not None else list(range(1, len(right) + 1))

    # Pre-clean the right side once (not once per left title).
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
            "Left #": left_ids[i],
            "Left Title": lt,
            "Best Match #": right_ids[best_j] if matched else "",
            "Best Match Title": right[best_j] if matched else "",
            "Score": round(best_score, 1) if best_j >= 0 else 0.0,
            "Matched": "Yes" if matched else "No",
        })
    return pd.DataFrame(rows, columns=[
        "Left #", "Left Title", "Best Match #", "Best Match Title", "Score", "Matched"])


def self_dedup(titles, threshold: float = 85.0, ids: Optional[list] = None) -> pd.DataFrame:
    """Find near-duplicate pairs WITHIN a single list. Compares every unique
    unordered pair once (i < j) and returns those scoring >= threshold,
    highest score first.

    Returns a DataFrame: A #, A Title, B #, B Title, Score.
    """
    vals = _clean_series(titles)
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
                    "A #": ids[i], "A Title": vals[i],
                    "B #": ids[j], "B Title": vals[j],
                    "Score": round(s, 1),
                })
    df = pd.DataFrame(rows, columns=["A #", "A Title", "B #", "B Title", "Score"])
    if not df.empty:
        df = df.sort_values("Score", ascending=False, kind="stable").reset_index(drop=True)
    return df
