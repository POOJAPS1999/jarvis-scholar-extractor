"""
ai.py
=====
Frontend client for the AI figure-interpretation endpoint. The vision-model
call happens on the backend (which holds the ANTHROPIC_API_KEY); this just
POSTs an image + optional context and returns the interpretation text.
"""
from __future__ import annotations

import os

import requests

try:
    import streamlit as st
    _secret_url = None
    try:
        _secret_url = st.secrets.get("API_BASE_URL")
    except Exception:
        _secret_url = None
except Exception:
    _secret_url = None

API_BASE_URL = (
    _secret_url
    or os.environ.get("JARVIS_API_URL")
    or "https://jarvis-scholar-extractor-production.up.railway.app"
).rstrip("/")


def interpret_figure(image_bytes: bytes, context: str = "", filename: str = "figure.png",
                     mime: str = "image/png") -> str:
    """Send a figure to the backend for AI interpretation; return the text.
    Raises RuntimeError with a readable message on failure."""
    try:
        r = requests.post(
            f"{API_BASE_URL}/ai/interpret-figure",
            files={"file": (filename, image_bytes, mime)},
            data={"context": context or ""},
            timeout=120,
        )
    except Exception as e:
        raise RuntimeError(f"Could not reach the server: {e}")
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(detail)
    return r.json().get("interpretation", "")
