"""
export_scopus_csv.py
=====================
Standalone converter: takes the pipeline's internal output (.xlsx, whatever
the main matcher/pipeline produced) and writes a Scopus-CSV-FORMAT .csv file
that Biblioshiny (bibliometrix::convert2df(dbsource="scopus", format="csv"))
and VOSviewer's "Create map based on bibliographic data -> Scopus" reader can
both import directly.

WHY A SEPARATE SCRIPT: same reasoning as scopus_gap_filler.py - this is a new,
additive final stage (the "Biblioshiny/VOSviewer-ready Output" step from the
original pipeline design), not a change to the matching/fetching logic. It
only ever READS the already-produced output file and writes a new file next
to it; it never touches matcher.py, pipeline.py, or the sources/ package.

WHAT THIS DOES
--------------
The real Scopus CSV export (the format bibliometrix/VOSviewer parsers are
built around) has this exact 44-column header (confirmed against
bibliometrix's own reference sample dataset, bibliometrix.org/datasets/
scopus_csv.csv):

  Authors, Author(s) ID, Title, Year, Source title, Volume, Issue,
  Art. No., Page start, Page end, Page count, Cited by, DOI, Link,
  Affiliations, Authors with affiliations, Abstract, Author Keywords,
  Index Keywords, Molecular Sequence Numbers, Chemicals/CAS, Tradenames,
  Manufacturers, Funding Details, References, Correspondence Address,
  Editors, Sponsors, Publisher, Conference name, Conference date,
  Conference location, Conference code, ISSN, ISBN, CODEN, PubMed ID,
  Language of Original Document, Abbreviated Source Title, Document Type,
  Publication Stage, Access Type, Source, EID

Our pipeline's internal columns are named/shaped differently (e.g. full
author names semicolon-joined instead of "Surname Initial." comma-joined),
so this script remaps + reformats field-by-field. Fields we simply don't
collect (Volume, Issue, Page numbers, ISBN, CODEN, conference metadata,
Molecular Sequence Numbers, Chemicals/CAS, Tradenames, Manufacturers) are
left blank - bibliometrix tolerates blank cells in optional columns fine;
it only hard-requires a non-blank EID (Biblioshiny drops rows with a blank
EID) and works best with Authors/Title/Year/Source title/DOI/References/
Cited by populated, which this pipeline already provides.

The "Source" column is set to the literal string "Scopus" to exactly match
what a real Scopus export contains in that field (this is what both parsers
are built against) - this is a FORMAT-COMPATIBILITY choice, not a factual
claim: the true provenance of every record (OpenAlex/PubMed/Crossref, match
score, EID being synthetic, etc.) is preserved in full in the extra
"Jarvis_*" columns appended after the standard 44, which the Scopus/VOSviewer
parsers will simply ignore as unrecognized extra columns.

CAVEATS (read before trusting downstream analyses):
  - Author name -> "Surname Initial." conversion is a best-effort heuristic
    (last whitespace-separated token = surname). Works for typical Western/
    Indian "First [Middle] Last" name order as recorded by OpenAlex/PubMed/
    Crossref; will mis-split names that don't follow that order.
  - "Index Keywords" is filled from MeSH terms (PubMed's controlled
    vocabulary) as the closest available equivalent to Scopus's own
    Elsevier-assigned Index Keywords - not the same underlying vocabulary.
  - "Document Type" / "Access Type" / "Publication Stage" are normalized
    with a small best-effort mapping table, not Scopus's exact controlled
    vocabulary.
  - No R/bibliometrix install is available in this sandbox, so this script
    validates STRUCTURE (exact header match, EID coverage, CSV round-trip)
    rather than an actual biblioshiny import. Recommend a real import test
    on your machine before relying on this for a manuscript.
"""

import argparse
import csv
import json
import re
import sys

import pandas as pd

SCOPUS_COLUMNS = [
    "Authors", "Author(s) ID", "Title", "Year", "Source title", "Volume",
    "Issue", "Art. No.", "Page start", "Page end", "Page count", "Cited by",
    "DOI", "Link", "Affiliations", "Authors with affiliations", "Abstract",
    "Author Keywords", "Index Keywords", "Molecular Sequence Numbers",
    "Chemicals/CAS", "Tradenames", "Manufacturers", "Funding Details",
    "References", "Correspondence Address", "Editors", "Sponsors",
    "Publisher", "Conference name", "Conference date", "Conference location",
    "Conference code", "ISSN", "ISBN", "CODEN", "PubMed ID",
    "Language of Original Document", "Abbreviated Source Title",
    "Document Type", "Publication Stage", "Access Type", "Source", "EID",
]

# Extra provenance columns appended AFTER the standard 44 - real Scopus/
# VOSviewer parsers ignore unrecognized trailing columns, so this is safe
# to include and keeps this file self-auditing.
PROVENANCE_COLUMNS = [
    "Jarvis_Clean_Title_Input", "Jarvis_Match_Status", "Jarvis_Match_Score",
    "Jarvis_Match_Source", "Jarvis_EID_Is_Synthetic", "Jarvis_Fetch_Issues",
    "Jarvis_Reconciliation_Notes",
]

DOCTYPE_MAP = {
    "article": "Article", "journal-article": "Article",
    "review": "Review", "review-article": "Review",
    "posted-content": "Article", "preprint": "Article",
    "proceedings-article": "Conference Paper",
    "book-chapter": "Book Chapter", "letter": "Letter",
    "editorial": "Editorial", "case-report": "Article",
    "erratum": "Erratum",
}


def _is_initials_blob(tok):
    """True if tok is an all-caps 1-4 letter chunk like 'R', 'CN', 'VR' - i.e.
    it's an initials group, never a real (properly-cased) surname."""
    letters = tok.replace(".", "")
    return 1 <= len(letters) <= 4 and letters.isalpha() and letters.isupper()


def _scopus_author_name(full_name):
    """Best-effort 'Surname I.I.' formatter. Handles TWO input conventions
    that both show up in this pipeline's data:
      1. This pipeline's own convention (OpenAlex/Crossref/PubMed-API fetch,
         via matcher.py): 'Forename(s) Surname', e.g. 'Jane Ann Doe' -> surname
         is the LAST token.
      2. Legacy/pre-existing citation-style data carried over unmodified from
         the user's original merged sheet (never re-fetched through this
         pipeline - e.g. copy-pasted PubMed citation author lists): 'Surname
         Initials', e.g. 'Asadollahi R' or 'de Kruiff CC' -> surname is
         EVERYTHING EXCEPT the last token, which is an initials blob.
    Detected per-name via whether the first or last token looks like an
    initials blob (all-caps, <=4 letters - a real properly-cased surname
    never matches this)."""
    parts = [p for p in str(full_name).strip().split() if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if _is_initials_blob(parts[-1]) and not _is_initials_blob(parts[0]):
        # Citation-style: surname first, initials blob last.
        surname = " ".join(parts[:-1])
        initials = ".".join(list(parts[-1].replace(".", ""))) + "."
        return f"{surname} {initials}"
    # Our pipeline's own convention: forename(s) first, surname last.
    surname = parts[-1]
    initials = "".join(p[0].upper() + "." for p in parts[:-1])
    return f"{surname} {initials}"


def _split_names(joined):
    """Our own pipeline joins names with '; '. Some rows carry legacy/
    pre-existing data (never re-fetched through this pipeline) that's
    comma-joined instead - e.g. 'Asadollahi R, Ahmad A, Boonsawat P, ...'.
    Splitting a 100+-author comma-joined string on ';' (finding none) used to
    silently return the WHOLE string as a single 'name', which then got
    mangled beyond recognition by _scopus_author_name. Detect and split on
    whichever delimiter is actually present."""
    if not joined or (isinstance(joined, float)):
        return []
    s = str(joined)
    if ";" in s:
        return [n.strip() for n in s.split(";") if n.strip()]
    if "," in s:
        return [n.strip() for n in s.split(",") if n.strip()]
    return [s.strip()] if s.strip() else []


def _scopus_authors_field(authors_joined):
    names = _split_names(authors_joined)
    return ", ".join(_scopus_author_name(n) for n in names)


def _scopus_author_ids_field(ids_joined):
    ids = _split_names(ids_joined)
    return ";".join(ids) + (";" if ids else "")


def _authors_with_affiliations(authors_joined, aff_map_json):
    """Scopus format: 'Surname I., Affiliation string; Surname I., Affiliation string; ...'"""
    names = _split_names(authors_joined)
    if not names:
        return ""
    aff_map = {}
    if aff_map_json and not (isinstance(aff_map_json, float)):
        try:
            aff_map = json.loads(aff_map_json)
        except (json.JSONDecodeError, TypeError):
            aff_map = {}
    parts = []
    for name in names:
        aff = aff_map.get(name, "")
        scopus_name = _scopus_author_name(name)
        parts.append(f"{scopus_name}, {aff}" if aff else scopus_name)
    return "; ".join(parts)


# MeSH "check tags" - a well-known NLM concept: broad demographic/species/
# study-design headings that indexers apply to nearly EVERY biomedical
# record regardless of actual topic (sex, age bracket, common lab species,
# "Humans" itself, basic study-design descriptors). They carry essentially
# zero discriminating power for a THEMATIC keyword analysis - real-world
# confirmation from this pipeline's own merged output: "Humans" appeared on
# 1,325 of 2,632 records, "Female" on 786, "Animals" on 470, "Mice" on 181 -
# and Biblioshiny's thematic map was consequently clustering papers into
# meaningless buckets like "humans/female/medicine" and "animals/mice/
# chemistry" instead of actual research themes. Excluded here so the
# merged keyword pool stays genuinely topical.
_MESH_CHECK_TAGS = {
    # species/organism check tags
    "humans", "animals", "mice", "rats", "rabbits", "dogs", "cats",
    "guinea pigs", "cattle", "swine", "sheep", "chickens", "zebrafish",
    "drosophila melanogaster", "drosophila", "caenorhabditis elegans",
    "mice, inbred c57bl",
    # sex/age check tags
    "male", "female", "adult", "aged", "aged, 80 and over", "child",
    "child, preschool", "adolescent", "infant", "infant, newborn",
    "middle aged", "young adult",
    # broad study-design/methodology headings (useful for a methods
    # breakdown, but pure noise for a THEMATIC/topic keyword map)
    "cross-sectional studies", "retrospective studies", "prospective studies",
    "cohort studies", "follow-up studies", "case-control studies",
    "randomized controlled trial", "comparative study", "time factors",
    "reproducibility of results", "risk factors", "treatment outcome",
    "cell line, tumor", "cell line", "disease models, animal",
    # geographic descriptors - real information, but not a "theme", and in
    # a single-country-focused dataset (e.g. all-India) it just floods
    # every record identically
    "india", "india/epidemiology",
}

# OpenAlex's ~19 top-level ("Level 0") Concept fields - the broadest
# possible field classification (e.g. every biomedical paper gets tagged
# "Medicine" or "Biology"). Same problem as MeSH check tags: real signal
# lives in the more specific concepts alongside them, not in these.
_OPENALEX_TOP_LEVEL_CONCEPTS = {
    "medicine", "biology", "chemistry", "computer science", "physics",
    "materials science", "engineering", "environmental science", "geology",
    "political science", "economics", "psychology", "sociology", "business",
    "history", "geography", "art", "philosophy", "mathematics",
}


def _merge_keywords(author_kw, mesh_terms, concepts):
    """Biblioshiny's per-field diagnostic showed Author Keywords (~25% missing)
    and Index Keywords/MeSH (~32% missing) both flagged 'Poor' individually,
    even though nearly every record has AT LEAST one of {Author Keywords,
    MeSH Terms, Concepts} populated. Per user's decision: merge all three
    into one deduped keyword pool and use it for BOTH the Author Keywords
    (DE) and Index Keywords (ID) Scopus columns, maximizing coverage for
    keyword co-occurrence / trend-topic analyses at the cost of DE and ID no
    longer being distinct vocabularies.
    - Author Keywords / Concepts are already '; '-joined / ', '-joined lists.
    - MeSH terms carry a leading '*' for NLM 'major topic' entries and often
      a '/subheading' suffix (e.g. '*Neurodevelopmental Disorders/genetics') -
      strip only the leading '*' (cosmetic), keep the rest as-is.
    - MeSH check tags and OpenAlex top-level Concept fields are filtered out
      (see _MESH_CHECK_TAGS / _OPENALEX_TOP_LEVEL_CONCEPTS above) - matched
      on the part before any '/subheading', case-insensitive - so genuinely
      topical MeSH descriptors (e.g. 'Neurodevelopmental Disorders/genetics')
      are kept even though check tags sharing the same field are dropped.
    Case-insensitive de-dup, first-seen casing kept, semicolon-joined output.
    """
    tokens = []

    def _add_all(raw, seps, exclude=None):
        s = str(raw or "").strip()
        if not s or s.lower() == "nan":
            return
        parts = [s]
        for sep in seps:
            parts = [p for part in parts for p in part.split(sep)]
        for p in parts:
            p = p.strip().lstrip("*").strip()
            if not p:
                continue
            if exclude:
                base = p.split("/")[0].strip().lower()
                if base in exclude or p.lower() in exclude:
                    continue
            tokens.append(p)

    _add_all(author_kw, [";"])
    _add_all(mesh_terms, [";"], exclude=_MESH_CHECK_TAGS)
    _add_all(concepts, [",", ";"], exclude=_OPENALEX_TOP_LEVEL_CONCEPTS)

    seen = set()
    merged = []
    for t in tokens:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            merged.append(t)
    return "; ".join(merged)


def _correspondence_address(corr_author, corr_email, aff_map_json):
    if not corr_author or (isinstance(corr_author, float)):
        return ""
    first_corr = _split_names(corr_author)
    if not first_corr:
        return ""
    name = first_corr[0]
    aff_map = {}
    if aff_map_json and not (isinstance(aff_map_json, float)):
        try:
            aff_map = json.loads(aff_map_json)
        except (json.JSONDecodeError, TypeError):
            aff_map = {}
    aff = aff_map.get(name, "")
    scopus_name = _scopus_author_name(name)
    pieces = [scopus_name]
    if aff:
        pieces.append(aff)
    if corr_email and not isinstance(corr_email, float) and str(corr_email).strip():
        pieces.append(f"email: {corr_email}")
    return "; ".join(pieces)


def _clean_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _map_document_type(article_type):
    v = _clean_str(article_type)
    if not v:
        return ""
    first = v.split(";")[0].strip().lower()
    return DOCTYPE_MAP.get(first, first.title() if first else "")


def _map_access_type(open_access):
    v = _clean_str(open_access)
    return "Open Access" if v == "Yes" else ""


def convert_row(row):
    aff_map_json = row.get("Author_Affiliation_Map", "")
    authors_joined = row.get("Authors", "")

    out = {
        "Authors": _scopus_authors_field(authors_joined),
        "Author(s) ID": _scopus_author_ids_field(row.get("Author(s) ID (synthetic)", "")),
        "Title": _clean_str(row.get("TITLE", "")),
        "Year": _clean_str(row.get("YEAR", "")),
        "Source title": _clean_str(row.get("Journal", "")),
        "Volume": "",
        "Issue": "",
        "Art. No.": "",
        "Page start": "",
        "Page end": "",
        "Page count": "",
        "Cited by": _clean_str(row.get("Citations", "")),
        "DOI": _clean_str(row.get("DOI", "")),
        "Link": _clean_str(row.get("Source Link", "")),
        "Affiliations": _clean_str(row.get("Affliation", "")),
        "Authors with affiliations": _authors_with_affiliations(authors_joined, aff_map_json),
        "Abstract": _clean_str(row.get("Abstract", "")),
        "Author Keywords": _merge_keywords(
            row.get("Author Keywords (Other Terms)", ""), row.get("MeSH Terms", ""), row.get("Concepts", "")),
        "Index Keywords": _merge_keywords(
            row.get("Author Keywords (Other Terms)", ""), row.get("MeSH Terms", ""), row.get("Concepts", "")),
        "Molecular Sequence Numbers": "",
        "Chemicals/CAS": "",
        "Tradenames": "",
        "Manufacturers": "",
        "Funding Details": _clean_str(row.get("Grants", "")),
        "References": _clean_str(row.get("References", "")),
        "Correspondence Address": _correspondence_address(
            row.get("Corresponding Author", ""),
            row.get("Corresponding Author Email ID", ""),
            aff_map_json),
        "Editors": "",
        "Sponsors": "",
        "Publisher": _clean_str(row.get("Publisher", "")),
        "Conference name": "",
        "Conference date": "",
        "Conference location": "",
        "Conference code": "",
        "ISSN": _clean_str(row.get("ISSN", "")),
        "ISBN": "",
        "CODEN": "",
        "PubMed ID": _clean_str(row.get("PMID", "")),
        "Language of Original Document": "",
        "Abbreviated Source Title": "",
        "Document Type": _map_document_type(row.get("Article Type", "")),
        "Publication Stage": "Final",
        "Access Type": _map_access_type(row.get("Open Access", "")),
        "Source": "Scopus",
        "EID": _clean_str(row.get("EID", "")),
        # ---- provenance (extra columns, ignored by Scopus/VOSviewer parsers) ----
        "Jarvis_Clean_Title_Input": _clean_str(row.get("Clean Title", "")),
        "Jarvis_Match_Status": _clean_str(row.get("Match Status", "")),
        "Jarvis_Match_Score": _clean_str(row.get("Match Score", "")),
        "Jarvis_Match_Source": _clean_str(row.get("Match Source", "")),
        "Jarvis_EID_Is_Synthetic": "Yes" if _clean_str(row.get("EID", "")) else "No",
        "Jarvis_Fetch_Issues": _clean_str(row.get("Fetch Issues", "")),
        "Jarvis_Reconciliation_Notes": _clean_str(row.get("Reconciliation Notes", "")),
    }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to the pipeline's internal output .xlsx")
    ap.add_argument("--output", required=True, help="Path to write the Scopus-CSV-format .csv")
    args = ap.parse_args()

    df = pd.read_excel(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    if "Dedup Status" in df.columns:
        is_dup = df["Dedup Status"].astype(str).str.startswith("Duplicate")
        n_skipped = int(is_dup.sum())
        if n_skipped:
            print(f"Skipping {n_skipped} row(s) flagged as secondary duplicates by deduplicate_output.py "
                  f"(same DOI as another row - see 'Dedup Status' column)")
        df = df[~is_dup]

    out_rows = [convert_row(row) for _, row in df.iterrows()]
    out_df = pd.DataFrame(out_rows, columns=SCOPUS_COLUMNS + PROVENANCE_COLUMNS)

    # utf-8-sig gives the BOM real Scopus exports include - harmless either
    # way, but matches the reference format exactly.
    out_df.to_csv(args.output, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)
    print(f"Wrote {len(out_df)} rows to {args.output}")

    # ---- structural validation / coverage report ----
    blank_eid = (out_df["EID"] == "").sum()
    blank_doi = (out_df["DOI"] == "").sum()
    blank_authors = (out_df["Authors"] == "").sum()
    blank_title = (out_df["Title"] == "").sum()
    blank_year = (out_df["Year"] == "").sum()
    blank_source = (out_df["Source title"] == "").sum()
    blank_affil = (out_df["Affiliations"] == "").sum()
    blank_refs = (out_df["References"] == "").sum()
    blank_de = (out_df["Author Keywords"] == "").sum()
    blank_id = (out_df["Index Keywords"] == "").sum()

    print("\n--- Coverage report (blank = would weaken/break that analysis in Biblioshiny) ---")
    print(f"  EID (Biblioshiny drops rows with blank EID) : {len(out_df) - blank_eid}/{len(out_df)} present")
    print(f"  DOI                                          : {len(out_df) - blank_doi}/{len(out_df)} present")
    print(f"  Authors                                      : {len(out_df) - blank_authors}/{len(out_df)} present")
    print(f"  Title                                        : {len(out_df) - blank_title}/{len(out_df)} present")
    print(f"  Year                                         : {len(out_df) - blank_year}/{len(out_df)} present")
    print(f"  Source title (Journal)                       : {len(out_df) - blank_source}/{len(out_df)} present")
    print(f"  Affiliations                                 : {len(out_df) - blank_affil}/{len(out_df)} present")
    print(f"  References (needed for citation/co-citation) : {len(out_df) - blank_refs}/{len(out_df)} present")
    print(f"  Author Keywords (DE, merged w/ MeSH+Concepts): {len(out_df) - blank_de}/{len(out_df)} present")
    print(f"  Index Keywords (ID, merged w/ MeSH+Concepts) : {len(out_df) - blank_id}/{len(out_df)} present")
    if blank_eid:
        print(f"  WARNING: {blank_eid} row(s) will be DROPPED by Biblioshiny's Scopus importer (blank EID).")


if __name__ == "__main__":
    main()
