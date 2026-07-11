"""
sheet_merge.py
==============
Generic two-sheet merge by matched column(s). Exact-match join (standard
pandas.merge) is the guaranteed, well-tested path. The join columns in the
two sheets do NOT have to share a name.

Returns the merged DataFrame plus a small summary (row counts, how many rows
on each side found no match) so the UI can show what did and didn't join.
"""
from __future__ import annotations

from typing import List, Tuple

import pandas as pd

JOIN_TYPES = ["inner", "left", "right", "outer"]


def _norm_key_frame(df: pd.DataFrame, cols: List[str], case_insensitive: bool,
                    trim: bool) -> pd.DataFrame:
    """Return a copy of df with temporary normalised key columns added, so an
    exact join can optionally ignore surrounding whitespace / letter case
    without mutating the user's actual data (the original columns are what
    get carried into the output)."""
    out = df.copy()
    keycols = []
    for i, c in enumerate(cols):
        kc = f"__key_{i}__"
        s = out[c].astype(str)
        if trim:
            s = s.str.strip()
        if case_insensitive:
            s = s.str.lower()
        # treat pandas' string 'nan' (from NaN) as an empty, non-joining key
        s = s.replace({"nan": ""})
        out[kc] = s
        keycols.append(kc)
    return out, keycols


def merge_sheets(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_on: List[str],
    right_on: List[str],
    how: str = "inner",
    case_insensitive: bool = True,
    trim: bool = True,
    suffixes: Tuple[str, str] = (" (A)", " (B)"),
) -> Tuple[pd.DataFrame, dict]:
    """Exact-match merge of two sheets on one or more column pairs.

    left_on[i] is matched against right_on[i]. Column names may differ
    between the two sheets. Returns (merged_df, summary).
    """
    if how not in JOIN_TYPES:
        raise ValueError(f"how must be one of {JOIN_TYPES}, got {how!r}")
    if len(left_on) != len(right_on):
        raise ValueError("left_on and right_on must name the same number of columns")
    if not left_on:
        raise ValueError("pick at least one column pair to join on")

    for c in left_on:
        if c not in left.columns:
            raise ValueError(f"left join column {c!r} not in sheet A")
    for c in right_on:
        if c not in right.columns:
            raise ValueError(f"right join column {c!r} not in sheet B")

    lkeyed, lkeys = _norm_key_frame(left, left_on, case_insensitive, trim)
    rkeyed, rkeys = _norm_key_frame(right, right_on, case_insensitive, trim)

    # Use indicator to count unmatched rows on each side, then drop the temp
    # key + indicator columns so the output only contains the user's data.
    merged = lkeyed.merge(
        rkeyed,
        left_on=lkeys,
        right_on=rkeys,
        how=how,
        suffixes=suffixes,
        indicator="_merge_side",
    )

    n_left_only = int((merged["_merge_side"] == "left_only").sum())
    n_right_only = int((merged["_merge_side"] == "right_only").sum())
    n_both = int((merged["_merge_side"] == "both").sum())

    drop_cols = [c for c in (lkeys + rkeys + ["_merge_side"]) if c in merged.columns]
    merged = merged.drop(columns=drop_cols)

    # Rows in each source that never matched anything on the other side
    # (independent of join type, for a clear "what didn't join" report).
    left_key_tuples = set(map(tuple, lkeyed[lkeys].itertuples(index=False, name=None)))
    right_key_tuples = set(map(tuple, rkeyed[rkeys].itertuples(index=False, name=None)))
    unmatched_left = sum(1 for t in map(tuple, lkeyed[lkeys].itertuples(index=False, name=None))
                         if t not in right_key_tuples or all(x == "" for x in t))
    unmatched_right = sum(1 for t in map(tuple, rkeyed[rkeys].itertuples(index=False, name=None))
                          if t not in left_key_tuples or all(x == "" for x in t))

    summary = {
        "rows_out": len(merged),
        "rows_left": len(left),
        "rows_right": len(right),
        "matched_pairs": n_both,
        "left_only_in_output": n_left_only,
        "right_only_in_output": n_right_only,
        "left_rows_unmatched": unmatched_left,
        "right_rows_unmatched": unmatched_right,
        "how": how,
    }
    return merged, summary
