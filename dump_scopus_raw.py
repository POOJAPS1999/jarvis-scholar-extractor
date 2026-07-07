#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump_scopus_raw.py
====================
Standalone debug helper - separate from scopus_gap_filler.py and the main
pipeline. Dumps the raw Scopus JSON for a few specific DOIs (the ones that
came back "Scopus record found but no affiliation fields extracted") so we
can see the actual field names Scopus is using and fix the parser to match.

Uses the same .env.scopus as scopus_gap_filler.py - no separate setup needed.

Usage:
    cd bibliometric_pipeline_project
    python3 dump_scopus_raw.py
"""
import json
import os
import sys

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_SCOPUS_PATH = os.path.join(SCRIPT_DIR, ".env.scopus")
if load_dotenv is not None and os.path.exists(ENV_SCOPUS_PATH):
    load_dotenv(ENV_SCOPUS_PATH)

SCOPUS_API_KEY = os.environ.get("SCOPUS_API_KEY", "").strip()
SCOPUS_INST_TOKEN = os.environ.get("SCOPUS_INST_TOKEN", "").strip()

# The DOIs that came back "Scopus record found but no target fields
# extracted" in the Included_studies gap-fill run (now checking Abstract +
# Corresponding Author extraction, not just affiliations).
DOIS = [
    "10.25259/IJMR_1246_2025",   # Sno 125
    "10.25259/IJMR_1546_2025",   # Sno 127
    "10.1186/s12911-025-03092-7",  # Sno 153
    "10.25259/IJMR_2157_2024",   # Sno 157
]

OUT_DIR = os.path.join(SCRIPT_DIR, "scopus_raw_dumps")


def main():
    if not SCOPUS_API_KEY:
        sys.exit("ERROR: no SCOPUS_API_KEY in .env.scopus")
    os.makedirs(OUT_DIR, exist_ok=True)

    headers = {"X-ELS-APIKey": SCOPUS_API_KEY, "Accept": "application/json"}
    if SCOPUS_INST_TOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INST_TOKEN

    for doi in DOIS:
        url = f"https://api.elsevier.com/content/abstract/doi/{doi}"
        r = requests.get(url, headers=headers, params={"httpAccept": "application/json", "view": "FULL"}, timeout=25)
        print(f"{doi} -> HTTP {r.status_code} (view=FULL)")
        if r.status_code in (401, 403):
            r = requests.get(url, headers=headers, params={"httpAccept": "application/json"}, timeout=25)
            print(f"  view=FULL not entitled, retried with default view -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"  body: {r.text[:300]}")
            continue
        data = r.json()
        safe_name = doi.replace("/", "_").replace("(", "").replace(")", "")
        out_path = os.path.join(OUT_DIR, f"{safe_name}.json")
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  saved raw response -> {out_path}")

        # Quick peek at the shape, so you can eyeball it right in the terminal too
        root = data.get("abstracts-retrieval-response", {})
        print(f"  top-level keys: {list(root.keys())}")
        print(f"  has 'affiliation'? {'affiliation' in root}  -> {root.get('affiliation')}")
        coredata = root.get("coredata") or {}
        print(f"  coredata keys: {list(coredata.keys())}")
        desc = coredata.get("dc:description")
        print(f"  coredata['dc:description'] present? {desc is not None}  -> {str(desc)[:200]!r}")
        head = ((root.get("item") or {}).get("bibrecord") or {}).get("head") or {}
        print(f"  head keys: {list(head.keys())}")
        print(f"  has author-group? {'author-group' in head}")
        print(f"  has correspondence? {'correspondence' in head}  -> {head.get('correspondence')}")
        print()

    print(f"Done. Share the files in {OUT_DIR}/ (or paste their contents) so the parser can be fixed.")


if __name__ == "__main__":
    main()
