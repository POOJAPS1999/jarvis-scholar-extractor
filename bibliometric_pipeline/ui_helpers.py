"""
ui_helpers.py
=============
Small Streamlit-side helpers shared across the dashboard tool pages
(converters, fuzzy match, sheet merge). Kept separate from the pure-logic
modules so those stay Streamlit-free and unit-testable.
"""
from __future__ import annotations

import io

import pandas as pd


def df_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, index=False, sheet_name=sheet_name[:31] or "Sheet1")
    return buf.getvalue()


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")  # BOM so Excel opens UTF-8 cleanly


def download_buttons(df: pd.DataFrame, stem: str, key_prefix: str, sheet_name: str = "Sheet1"):
    """Render side-by-side CSV + Excel download buttons for a DataFrame."""
    import streamlit as st

    c1, c2 = st.columns(2)
    c1.download_button(
        "Download CSV",
        data=df_to_csv_bytes(df),
        file_name=f"{stem}.csv",
        mime="text/csv",
        key=f"{key_prefix}_csv",
        width="stretch",
    )
    c2.download_button(
        "Download Excel",
        data=df_to_excel_bytes(df, sheet_name=sheet_name),
        file_name=f"{stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_xlsx",
        width="stretch",
    )


def read_tabular_upload(uploaded, sheet_name=0) -> pd.DataFrame:
    """Read an uploaded .xlsx/.xls/.csv/.tsv into a DataFrame."""
    name = (uploaded.name or "").lower()
    data = uploaded.getvalue()
    if name.endswith((".csv",)):
        return pd.read_csv(io.BytesIO(data))
    if name.endswith((".tsv", ".tab")):
        return pd.read_csv(io.BytesIO(data), sep="\t")
    return pd.read_excel(io.BytesIO(data), sheet_name=sheet_name)


def excel_sheet_names(uploaded) -> list:
    """Return sheet names for an uploaded Excel file, or [] for CSV/TSV."""
    name = (uploaded.name or "").lower()
    if name.endswith((".csv", ".tsv", ".tab")):
        return []
    xl = pd.ExcelFile(io.BytesIO(uploaded.getvalue()))
    return xl.sheet_names
