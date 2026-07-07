"""
review_logic.py
================
Pure manual-review decision logic, shared between the Phase 0 Streamlit app
and the Phase 1 FastAPI backend, so there's exactly one implementation of
"what does Accept/Reject/Retry-with-corrected-DOI actually do to the
checkpoint" instead of two copies drifting apart.

No Streamlit or FastAPI imports here on purpose - this only touches
pandas DataFrames, so it's usable (and unit-testable) from either.
"""
import pandas as pd


def apply_review_decisions(ckpt_df: pd.DataFrame, edited_df: pd.DataFrame, overrides: dict):
    """
    ckpt_df    - the full checkpoint DataFrame (all rows, any status)
    edited_df  - the reviewer's edited subset, with 'Decision' and
                 'Corrected DOI' columns added (one row per record under
                 review, 'Sno.' identifies which checkpoint row it maps to)
    overrides  - existing {sno: corrected_doi} dict to update in place

    Returns (new_ckpt_df, overrides, counts_dict, warnings_list).

    Decisions:
      - "Accept candidate"          -> Match Status set to "Confirmed (manual review)"
      - "Reject (exclude)"          -> Match Status set to "Rejected (manual review)"
      - "Retry with corrected DOI"  -> row dropped from checkpoint (so the
                                        next run's done-set no longer skips
                                        it) and the corrected DOI recorded
                                        in `overrides` for the caller to
                                        apply to the input DataFrame before
                                        the next run.
      - anything else (e.g. "Keep as-is") -> no change.
    """
    ckpt_df = ckpt_df.copy()
    n_accept = n_reject = n_retry = 0
    warnings = []
    for _, r in edited_df.iterrows():
        sno = str(r["Sno."])
        decision = r["Decision"]
        row_mask = ckpt_df["Sno."].astype(str) == sno
        if decision == "Accept candidate":
            ckpt_df.loc[row_mask, "Match Status"] = "Confirmed (manual review)"
            n_accept += 1
        elif decision == "Reject (exclude)":
            ckpt_df.loc[row_mask, "Match Status"] = "Rejected (manual review)"
            n_reject += 1
        elif decision == "Retry with corrected DOI":
            corrected = str(r.get("Corrected DOI") or "").strip()
            if not corrected:
                warnings.append(f"Sno {sno}: 'Retry with corrected DOI' needs a DOI - skipped.")
                continue
            overrides[sno] = corrected
            ckpt_df = ckpt_df[~row_mask]
            n_retry += 1
    counts = {"accept": n_accept, "reject": n_reject, "retry": n_retry}
    return ckpt_df, overrides, counts, warnings
