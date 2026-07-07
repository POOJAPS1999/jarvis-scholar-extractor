#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_extractor.py
=================
USAGE (macOS / Python 3):
    pip3 install -r requirements.txt
    cp .env.example .env        # then edit .env with your real email + NCBI key
    python3 run_extractor.py

All settings (input/output paths, thresholds, credentials) are now read from
.env instead of being hardcoded - see config.py and .env.example.
"""

from bibliometric_pipeline.pipeline import run

if __name__ == "__main__":
    run()
