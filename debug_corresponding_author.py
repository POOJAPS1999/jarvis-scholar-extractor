"""
debug_corresponding_author.py
==============================
Tiny, single-DOI diagnostic. Corresponding Author has a 0/238 fill rate so
far in the Included_studies gap-fill run - before waiting hours for the
full run, this checks whether that's a genuine OpenAlex/PubMed data-
coverage limit or an actual bug in our parsing.

Prints the RAW is_corresponding flag per author from OpenAlex, and the raw
PubMed affiliation text (for the "Electronic address" heuristic), for one
DOI you pick - ideally one where you've confirmed online that a
corresponding author IS clearly marked on the publisher's page.

Usage:
  python3 debug_corresponding_author.py 10.1128/spectrum.03247-24
"""
import sys

sys.path.insert(0, ".")
from bibliometric_pipeline.sources import openalex, pubmed  # noqa: E402
from bibliometric_pipeline.text_utils import normalize_doi  # noqa: E402

if len(sys.argv) < 2:
    print("Usage: python3 debug_corresponding_author.py <DOI>")
    sys.exit(1)

doi = normalize_doi(sys.argv[1])
print(f"Checking DOI: {doi}\n")

print("=== OpenAlex ===")
oa_raw = openalex.openalex_by_doi(doi)
if not oa_raw:
    print("  No OpenAlex record found for this DOI.")
else:
    authorships = oa_raw.get("authorships", [])
    print(f"  {len(authorships)} authorship(s) found. is_corresponding per author:")
    any_true = False
    for a in authorships:
        name = (a.get("author") or {}).get("display_name", "?")
        flag = a.get("is_corresponding")
        if flag:
            any_true = True
        print(f"    {name}: is_corresponding={flag}")
    if not any_true:
        print("  -> OpenAlex has NO author flagged is_corresponding=True for this record.")
        print("     This is the real limitation: OpenAlex only has this if the publisher")
        print("     submitted contributor-role data to Crossref - many journals don't.")

print("\n=== PubMed ===")
pm_raw = pubmed.pubmed_by_doi(doi)
if not pm_raw:
    print("  No PubMed record found for this DOI (not every paper is PubMed-indexed).")
else:
    aff_map = pm_raw.get("aff_map", {})
    if not aff_map:
        print("  PubMed record found but no per-author affiliation text at all.")
    else:
        print("  Affiliation text per author (heuristic looks for 'electronic address' in here):")
        any_ea = False
        for name, aff in aff_map.items():
            has_ea = "electronic address" in aff.lower()
            if has_ea:
                any_ea = True
            marker = " <-- MATCHES heuristic" if has_ea else ""
            print(f"    {name}: {aff[:150]}{marker}")
        if not any_ea:
            print("  -> No author's affiliation text contains 'Electronic address' - the")
            print("     PubMed heuristic has nothing to key off for this paper.")
