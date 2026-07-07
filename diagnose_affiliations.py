#!/usr/bin/env python3
"""
diagnose_affiliations.py
=========================
Run this LOCALLY (needs real internet - it won't work in a sandboxed
environment). It queries OpenAlex, Crossref, and PubMed directly for a
handful of DOIs that came back with a blank Affliation column, and prints:

  1. What our parser (parse_openalex / parse_crossref / pubmed XML parser)
     extracted for affiliations.
  2. The raw affiliation-shaped fields straight from each API's JSON/XML,
     so we can tell "the API genuinely has nothing" apart from "the API
     has it and our parser is missing it".

Usage:
    cd bibliometric_pipeline_project
    python3 diagnose_affiliations.py
"""
import json
import sys

from bibliometric_pipeline.sources import openalex, pubmed, crossref

# A representative spread: one very well-indexed journal (Lancet - should
# have institution data in OpenAlex if anything does) and a few smaller/
# regional journals (more likely to have genuine gaps).
DOIS = [
    "10.1016/s2213-8587(21)00349-1",   # Lancet Diabetes & Endocrinology
    "10.1016/s0140-6736(25)01037-2",   # The Lancet
    "10.1016/j.ihj.2026.01.001",       # Indian Heart Journal
    "10.38124/ijisrt/ijisrt24jun424",  # International Journal of Innovative...
    "10.55487/p45mdd72",               # International Journal of conve...
]


def check_openalex(doi):
    print(f"\n--- OpenAlex : {doi} ---")
    work = openalex.openalex_by_doi(doi)
    if not work:
        print("  No OpenAlex record for this DOI at all.")
        return
    parsed = openalex.parse_openalex(work)
    print(f"  parsed authors: {len(parsed.get('authors', []))}")
    print(f"  parsed affiliations: {parsed.get('affiliations')}")
    print(f"  parsed first_author_aff: {parsed.get('first_author_aff')!r}")

    authorships = work.get("authorships", []) or []
    print(f"  raw authorships count: {len(authorships)}")
    if authorships:
        a0 = authorships[0]
        print(f"  raw authorships[0] keys: {list(a0.keys())}")
        print(f"  raw authorships[0]['institutions']: {a0.get('institutions')}")
        print(f"  raw authorships[0]['raw_affiliation_strings']: {a0.get('raw_affiliation_strings')}")
        print(f"  raw authorships[0].get('raw_affiliation_string') [old singular field, if present]: "
              f"{a0.get('raw_affiliation_string')}")


def check_crossref(doi):
    print(f"\n--- Crossref : {doi} ---")
    item = crossref.crossref_by_doi(doi)
    if not item:
        print("  No Crossref record for this DOI at all.")
        return
    parsed = crossref.parse_crossref(item)
    print(f"  parsed authors: {len(parsed.get('authors', []))}")
    print(f"  parsed affiliations: {parsed.get('affiliations')}")
    au_list = item.get("author") or []
    if au_list:
        print(f"  raw author[0] keys: {list(au_list[0].keys())}")
        print(f"  raw author[0]['affiliation']: {au_list[0].get('affiliation')}")


def check_pubmed(doi):
    print(f"\n--- PubMed : {doi} ---")
    rec = pubmed.pubmed_by_doi(doi)
    if not rec:
        print("  No PubMed record for this DOI (not indexed in PubMed, or DOI lookup failed).")
        return
    print(f"  pmid: {rec.get('pmid')}  pmcid: {rec.get('pmcid')}")
    print(f"  parsed authors: {len(rec.get('authors', []))}")
    print(f"  parsed affiliations: {rec.get('affiliations')}")


def main():
    for doi in DOIS:
        print("=" * 70)
        print(f"DOI: {doi}")
        try:
            check_openalex(doi)
        except Exception as e:
            print(f"  [ERROR checking OpenAlex] {e}")
        try:
            check_crossref(doi)
        except Exception as e:
            print(f"  [ERROR checking Crossref] {e}")
        try:
            check_pubmed(doi)
        except Exception as e:
            print(f"  [ERROR checking PubMed] {e}")
    print("\nDone. Paste this whole output back so we can tell whether it's a genuine")
    print("data gap in the source APIs or a parsing bug on our side.")


if __name__ == "__main__":
    main()
