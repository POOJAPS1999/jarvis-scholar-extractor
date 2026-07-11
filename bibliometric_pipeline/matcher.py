"""
matcher.py
==========
Core per-record matching + merge logic.

CHANGES in this version:
  - The three sources are now queried CONCURRENTLY per record (was
    sequential) - this is the main speed fix.
  - Column schema reworked: a lean CORE set that's always present, plus
    optional "groups" (ICMR flags, journal metrics, etc.) turned on via
    BIBLIO_OPTIONAL_COLUMN_GROUPS in .env - similar to how a Scopus export
    has defaults + a pick-list.
  - New fields: EID (synthetic, for Biblioshiny import compatibility),
    Author(s) ID (synthetic), Corresponding Author / Email / Country,
    All Country / Country Count (single clean pair, replacing two
    overlapping pairs from the old schema), Grants, COI, Acknowledgment.
"""

import json
import concurrent.futures as cf

from . import config
from .http_utils import FetchError
from .sources import openalex, pubmed, crossref
from .text_utils import (
    normalize_doi, join_semicolon, uniq_keep_order, is_icmr, country_name,
    extract_email, generate_synthetic_eid, generate_synthetic_author_id,
    fuzzy_score, clean_for_match,
)
from .icmr_institutes import resolve_all_icmr_institutes
from .journal_metrics import lookup_jif


# ---------------------------------------------------------------------
# Column schema: core (always present) + optional groups (opt-in)
# ---------------------------------------------------------------------
CORE_COLUMNS = [
    "Sno.", "EID", "EID Type", "Author(s) ID (synthetic)",
    "Abstract", "TITLE", "Clean Title", "Article Type", "DOI",
    "Match Status", "Match Score", "Match Source", "Candidate Title (unverified)",
    "Source Link", "PMID",
    "Authors", "Number of Authors", "First Author", "Last Author",
    "Corresponding Author", "Corresponding Author Email ID", "Corresponding Author Country",
    "Corresponding Author Affiliation",
    "Affliation", "First Author Affiliation",
    "All Country", "Country Count", "Multi Institution",
    "Journal", "Publication Date", "YEAR",
    "Open Access", "OA Type", "Publisher", "ISSN",
    "Citations", "Reference Count", "References", "Citations per Year", "Year Gap",
    "MeSH Terms", "Author Keywords (Other Terms)", "Concepts",
    "Grants", "COI", "Acknowledgment",
    "Author_Affiliation_Map",
    "Reconciliation Notes",
    "Fetch Issues", "Retry Count",
]

OPTIONAL_COLUMN_GROUPS = {
    "icmr_flags": [
        "First Author from ICMR", "Corresponding Author from ICMR",
        "Any Author from ICMR", "Intramural/Extramural",
    ],
    "icmr_institute": [
        "ICMR Institute (Current Name)",
    ],
    "institution_details": [
        "INSTITUTE", "DIVISION", "Institution Type",
        "Collaboration Type (National/International)", "Collaborators",
    ],
    "journal_metrics": [
        # "Journal Impact Factor (JCR 2025)" and "WoS Quartile" are REAL,
        # populated from Pooja's own Clarivate JCR export (see
        # journal_metrics.py) - joined by ISSN. Everything else in this
        # group has no data source wired in yet and stays blank.
        "Journal Impact Factor (JCR 2025)", "5-Year IF", "CiteScore (2023)", "SJR", "SNIP",
        "WoS Indexing", "Scopus Indexed", "WoS Quartile", "Scopus Quartile",
        "Top 10% Paper", "Rank",
    ],
    "research_classification": [
        "HEALTH IMPACT", "Domains", "Micro Domains", "4Ds Framework",
    ],
    "extra_bibliometric": [
        "Country", "Subject Category",
    ],
    "qc_notes": [
        "Comments",
    ],
}


def _build_output_columns():
    cols = list(CORE_COLUMNS)
    requested = [g.strip() for g in (config.OPTIONAL_COLUMN_GROUPS or "").split(",") if g.strip()]
    unknown = [g for g in requested if g not in OPTIONAL_COLUMN_GROUPS]
    if unknown:
        import sys
        sys.stderr.write(f"WARNING: unknown column group(s) in BIBLIO_OPTIONAL_COLUMN_GROUPS: {unknown} "
                          f"(available: {list(OPTIONAL_COLUMN_GROUPS.keys())})\n")
    for g in requested:
        cols.extend(OPTIONAL_COLUMN_GROUPS.get(g, []))
    return cols


OUTPUT_COLUMNS = _build_output_columns()


def build_output_columns(groups=None):
    """Build an output-column list for an EXPLICIT list of optional group
    names, independent of the process-wide BIBLIO_OPTIONAL_COLUMN_GROUPS env
    var. Used for per-job overrides (e.g. an "ICMR mode" request on a single
    job) so one job's choice never leaks into another running in the same
    long-lived worker process. Unknown group names are ignored. All the
    optional-group VALUES are always computed by build_row() regardless; this
    only controls which of them survive into the final projected output."""
    cols = list(CORE_COLUMNS)
    for g in (groups or []):
        cols.extend(OPTIONAL_COLUMN_GROUPS.get(g, []))
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def first_nonempty(*vals):
    for v in vals:
        if v is None:
            continue
        if isinstance(v, (list, tuple, dict)):
            if len(v) > 0:
                return v
        elif str(v).strip() != "":
            return v
    return ""


def _check_reconciliation(oa, pm, cr):
    """Cross-source agreement check for key fields, run whenever 2+ sources
    both returned data for this record.

    This is NOT the same thing as the DOI-mismatch safety net in
    process_record() - that one discards data it can't trust. This one
    doesn't discard or pick a winner (the normal first-non-empty merge
    order in build_row() still decides what actually ends up in the row);
    it only surfaces cases where two sources answered but DISAGREE, so a
    reviewer can spot-check without re-deriving it by hand the way this
    used to be done in Sheets. An empty return means either only one
    source had data (nothing to compare) or all sources that answered
    agreed - not a guarantee the row is fully correct.
    """
    notes = []

    # ---- Title: fuzzy-compare every pair of non-empty candidate titles ----
    titles = {"PubMed": pm.get("title", ""), "OpenAlex": oa.get("title", ""), "Crossref": cr.get("title", "")}
    titles = {k: v for k, v in titles.items() if v}
    names = list(titles.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            score = fuzzy_score(clean_for_match(titles[a]), clean_for_match(titles[b]))
            if score < 90:
                notes.append(f"Title disagreement ({score:.0f}% similar): "
                             f"{a}='{titles[a][:80]}' vs {b}='{titles[b][:80]}'")

    # ---- Year: any two non-empty values that don't match exactly ----
    years = {"PubMed": pm.get("year"), "OpenAlex": oa.get("year"), "Crossref": cr.get("year")}
    years = {k: v for k, v in years.items() if v}
    yn = list(years.keys())
    for i in range(len(yn)):
        for j in range(i + 1, len(yn)):
            a, b = yn[i], yn[j]
            if years[a] != years[b]:
                notes.append(f"Year disagreement: {a}={years[a]} vs {b}={years[b]}")

    # ---- Journal: fuzzy-compare, looser threshold (abbreviations vary a lot
    # between databases, e.g. 'J Clin Invest' vs 'Journal of Clinical
    # Investigation' - a strict threshold here would just be noisy) ----
    journals = {"OpenAlex": oa.get("journal", ""), "PubMed": pm.get("journal", ""), "Crossref": cr.get("journal", "")}
    journals = {k: v for k, v in journals.items() if v}
    jn = list(journals.keys())
    for i in range(len(jn)):
        for j in range(i + 1, len(jn)):
            a, b = jn[i], jn[j]
            score = fuzzy_score(clean_for_match(journals[a]), clean_for_match(journals[b]))
            if score < 70:
                notes.append(f"Journal disagreement ({score:.0f}% similar): "
                             f"{a}='{journals[a]}' vs {b}='{journals[b]}'")

    # ---- Citations: OpenAlex and Crossref count citations differently
    # (different coverage/lag), so use a tolerance rather than exact match -
    # only flag a meaningfully large relative gap. ----
    oa_cites, cr_cites = oa.get("cited_by_count"), cr.get("citations")
    if isinstance(oa_cites, (int, float)) and isinstance(cr_cites, (int, float)):
        hi, lo = max(oa_cites, cr_cites), min(oa_cites, cr_cites)
        if hi > 0 and (hi - lo) / hi > 0.5:
            notes.append(f"Citation count disagreement: OpenAlex={oa_cites} vs Crossref={cr_cites}")

    return notes


def build_row(sno, input_clean_title, input_doi, oa, pm, cr, notes,
              match_status="No match", match_score=0.0, match_source="",
              candidate_title="", fetch_errors=None, retry_count=0,
              acknowledgment=""):
    oa = oa or {}
    pm = pm or {}
    cr = cr or {}

    reconciliation_notes = _check_reconciliation(oa, pm, cr)

    doi = first_nonempty(oa.get("doi"), pm.get("doi"), cr.get("doi"), normalize_doi(input_doi))
    title = first_nonempty(pm.get("title"), oa.get("title"), cr.get("title"))
    abstract = first_nonempty(pm.get("abstract"), oa.get("abstract"), cr.get("abstract"))
    pmid = first_nonempty(oa.get("pmid"), pm.get("pmid"))

    if oa.get("authors"):
        authors = oa["authors"]
        first_author = oa.get("first_author", "")
        last_author = oa.get("last_author", "")
        first_author_aff = oa.get("first_author_aff", "")
        aff_map = dict(oa.get("aff_map", {}))
        affiliations = list(oa.get("affiliations", []))
    elif pm.get("authors"):
        authors = pm["authors"]
        first_author = pm.get("first_author", "")
        last_author = pm.get("last_author", "")
        first_author_aff = pm.get("first_author_aff", "")
        aff_map = dict(pm.get("aff_map", {}))
        affiliations = list(pm.get("affiliations", []))
    else:
        authors = cr.get("authors", [])
        first_author = cr.get("first_author", "")
        last_author = cr.get("last_author", "")
        first_author_aff = cr.get("first_author_aff", "")
        aff_map = dict(cr.get("aff_map", {}))
        affiliations = list(cr.get("affiliations", []))

    for other in (pm, cr):
        for name, aff in (other.get("aff_map") or {}).items():
            if name not in aff_map or not aff_map.get(name):
                aff_map[name] = aff
    if not affiliations:
        affiliations = pm.get("affiliations") or cr.get("affiliations") or []
    if not first_author_aff:
        first_author_aff = first_nonempty(pm.get("first_author_aff"), cr.get("first_author_aff"))

    n_authors = len(authors)

    # --- corresponding author (prefer OpenAlex's explicit flag; fall back
    # to the PubMed "Electronic address" heuristic) ---
    corresponding_authors = oa.get("corresponding_authors") or pm.get("corresponding_authors") or []
    corresponding_author = join_semicolon(corresponding_authors)

    corresponding_email = ""
    for name in corresponding_authors:
        e = extract_email(aff_map.get(name, ""))
        if e:
            corresponding_email = e
            break
    if not corresponding_email:
        for v in aff_map.values():
            e = extract_email(v)
            if e:
                corresponding_email = e
                break

    corresponding_country = ""
    author_country_map = oa.get("author_country_map", {}) or {}
    for name in corresponding_authors:
        if author_country_map.get(name):
            corresponding_country = author_country_map[name]
            break

    # --- corresponding author's own affiliation (previously not surfaced as
    # its own column - only the FIRST author's affiliation and the full
    # institute list were - even though the data was already sitting in
    # aff_map, keyed by author name, same as the email/country lookups above) ---
    corresponding_affiliation = ""
    for name in corresponding_authors:
        if aff_map.get(name):
            corresponding_affiliation = aff_map[name]
            break

    # --- countries (single clean pair) ---
    countries_codes = oa.get("countries", []) or []
    countries_named = uniq_keep_order([country_name(c) for c in countries_codes])
    country_count = len(countries_named)

    any_icmr = bool(oa.get("any_icmr") or pm.get("any_icmr") or cr.get("any_icmr"))
    first_icmr = bool(oa.get("first_icmr") or pm.get("first_icmr") or cr.get("first_icmr"))
    corr_icmr = bool(oa.get("corr_icmr"))
    if not any_icmr:
        any_icmr = any(is_icmr(v) for v in aff_map.values())

    institutes = uniq_keep_order(affiliations)
    multi_institution = "Yes" if len(institutes) > 1 else ("No" if institutes else "")

    # --- which ICMR institute(s) (current official name), if any - checked
    # against EACH individual institutes-list entry, first/corresponding
    # author affiliation, AND every individual author's own raw affiliation
    # text (aff_map.values()) - each passed as its OWN argument, not joined
    # into one combined blob first. This matters for two reasons:
    #   1. OpenAlex's "affiliations" list can prefer its own normalized
    #      institution name over the paper's raw affiliation text (see
    #      sources/openalex.py) - for a body with many differently-named
    #      constituent institutes like ICMR, that normalized name can
    #      collapse to just the parent organization, losing the specific-
    #      institute detail. aff_map (used elsewhere in this function, e.g.
    #      the any_icmr fallback a few lines up) already keeps the raw text
    #      per author regardless, so checking it here catches a co-author
    #      from a specific institute even when they're neither first nor
    #      corresponding author.
    #   2. Passing each entry SEPARATELY (rather than one joined string)
    #      keeps every AND-logic/acronym check scoped to a single author's
    #      own text - joining first let a signal from one co-author's
    #      segment (e.g. a bare "ICMR" mention) wrongly validate an
    #      unrelated match found only in a DIFFERENT co-author's segment
    #      (confirmed false positive on real data: an unrelated "NIMS
    #      University" co-author got matched to ICMR's National Institute
    #      for Research in Digital Health only because a different
    #      co-author's segment separately mentioned "ICMR-DHR").
    # A record can list co-authors from more than one ICMR institute
    # (multi-site collaboration), so this returns ALL distinct institutes
    # found, semicolon-joined, not just the first one. ---
    icmr_institute_name = resolve_all_icmr_institutes(
        *institutes, first_author_aff, corresponding_affiliation,
        *aff_map.values(),
    )
    collab_type = ""
    if country_count >= 2:
        collab_type = "International"
    elif country_count == 1:
        collab_type = "National"

    journal = first_nonempty(oa.get("journal"), pm.get("journal"), cr.get("journal"))
    issn = first_nonempty(oa.get("issn"), pm.get("issn"), cr.get("issn"))
    jif_value, jif_quartile = lookup_jif(issn)
    publisher = first_nonempty(oa.get("publisher"), cr.get("publisher"))
    source_link = first_nonempty(
        oa.get("landing_page_url"),
        f"https://doi.org/{doi}" if doi else "",
        f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "")

    publication_date = first_nonempty(oa.get("publication_date"), pm.get("publication_date"), cr.get("publication_date"))
    year = first_nonempty(oa.get("year"), pm.get("year"), cr.get("year"))
    try:
        year_int = int(year)
    except (ValueError, TypeError):
        year_int = None

    citations = first_nonempty(oa.get("cited_by_count"), cr.get("citations"))
    # Crossref is the source that actually carries the formatted reference
    # list (Author, Year, Title, Journal, DOI per entry) - OpenAlex only
    # gives referenced-work IDs, not the citation text, so its count is a
    # fallback for when Crossref has no deposited reference list.
    references_list = cr.get("references") or []
    references_joined = "; ".join(references_list)
    ref_count = first_nonempty(cr.get("reference_count"), oa.get("referenced_works_count"))
    citations_per_year = ""
    year_gap = ""
    if year_int:
        span = max(1, config.CURRENT_YEAR - year_int + 1)
        year_gap = config.CURRENT_YEAR - year_int
        if isinstance(citations, (int, float)):
            citations_per_year = round(citations / span, 2)

    article_type = first_nonempty(oa.get("type"), join_semicolon(pm.get("pub_types", [])), cr.get("type"))

    is_oa = oa.get("is_oa")
    open_access = ("Yes" if is_oa else "No") if is_oa is not None else ""
    oa_type = oa.get("oa_status", "")

    mesh = join_semicolon(pm.get("mesh", []))
    keywords = join_semicolon(pm.get("keywords", []))
    concepts = oa.get("concepts", "")
    subject_category = oa.get("subject_category", "")

    grants = join_semicolon(
        (pm.get("grants") or []) + (oa.get("grants") or []) + (cr.get("grants") or []))
    coi = first_nonempty(pm.get("coi"))  # only PubMed reliably has this
    # acknowledgment: passed in by process_record - see pmc_fetch_acknowledgment.
    # Empty by default unless BIBLIO_FETCH_ACKNOWLEDGMENT=true AND this record
    # has a PMCID in PMC's open-access full-text subset.

    aff_map_json = json.dumps(aff_map, ensure_ascii=False) if aff_map else ""

    # --- synthetic identifiers (see text_utils for the important caveat) ---
    eid_seed = doi or pmid or f"{sno}-{input_clean_title}"
    eid = generate_synthetic_eid(eid_seed) if eid_seed else ""
    eid_type = "Synthetic placeholder (NOT a real Scopus ID) - for Biblioshiny import only" if eid else ""
    author_ids = join_semicolon([generate_synthetic_author_id(a) for a in authors]) if authors else ""

    row = {
        "Sno.": sno,
        "EID": eid,
        "EID Type": eid_type,
        "Author(s) ID (synthetic)": author_ids,
        "Abstract": abstract,
        "TITLE": title,
        "Clean Title": input_clean_title,
        "Article Type": article_type,
        "DOI": doi,
        "Match Status": match_status,
        "Match Score": match_score,
        "Match Source": match_source,
        "Candidate Title (unverified)": candidate_title if match_status in ("Needs manual review", "No match") else "",
        "Source Link": source_link,
        "PMID": pmid,
        "Authors": join_semicolon(authors),
        "Number of Authors": n_authors if authors else "",
        "First Author": first_author,
        "Last Author": last_author,
        "Corresponding Author": corresponding_author,
        "Corresponding Author Email ID": corresponding_email,
        "Corresponding Author Country": corresponding_country,
        "Corresponding Author Affiliation": corresponding_affiliation,
        "Affliation": join_semicolon(institutes),
        "First Author Affiliation": first_author_aff,
        "All Country": join_semicolon(countries_named),
        "Country Count": country_count if countries_named else "",
        "Multi Institution": multi_institution,
        "Journal": journal,
        "Publication Date": publication_date,
        "YEAR": year_int if year_int else "",
        "Open Access": open_access,
        "OA Type": oa_type,
        "Publisher": publisher,
        "ISSN": issn,
        "Citations": citations if citations is not None and citations != "" else "",
        "Reference Count": ref_count if ref_count else "",
        "References": references_joined,
        "Citations per Year": citations_per_year,
        "Year Gap": year_gap,
        "MeSH Terms": mesh,
        "Author Keywords (Other Terms)": keywords,
        "Concepts": concepts,
        "Grants": grants,
        "COI": coi,
        "Acknowledgment": acknowledgment,
        "Author_Affiliation_Map": aff_map_json,
        "Reconciliation Notes": "; ".join(reconciliation_notes),
        "Fetch Issues": join_semicolon(fetch_errors or []),
        "Retry Count": retry_count,
        # ---- optional-group fields (only shown if that group is enabled) ----
        "INSTITUTE": join_semicolon(institutes),
        "DIVISION": "",
        "Institution Type": "",
        "Collaboration Type (National/International)": collab_type,
        "Collaborators": join_semicolon([a for a in authors if a != first_author]),
        "First Author from ICMR": "Yes" if first_icmr else ("No" if authors else ""),
        "Corresponding Author from ICMR": "Yes" if corr_icmr else "",
        "Any Author from ICMR": "Yes" if any_icmr else ("No" if authors else ""),
        "Intramural/Extramural": "",
        "ICMR Institute (Current Name)": icmr_institute_name,
        "Journal Impact Factor (JCR 2025)": jif_value, "5-Year IF": "", "CiteScore (2023)": "",
        "SJR": "", "SNIP": "", "WoS Indexing": ("Yes" if jif_value else ""), "Scopus Indexed": "",
        "WoS Quartile": jif_quartile, "Scopus Quartile": "", "Top 10% Paper": "", "Rank": "",
        "HEALTH IMPACT": "", "Domains": "", "Micro Domains": "", "4Ds Framework": "",
        "Country": country_name(oa.get("source_country", "")),
        "Subject Category": subject_category,
        "Comments": "; ".join(notes),
    }
    for c in OUTPUT_COLUMNS:
        row.setdefault(c, "")
    return row


def _doi_mismatch(requested_doi, parsed):
    """Defense in depth for every DOI-keyed lookup (OpenAlex, PubMed,
    Crossref): a source's DOI endpoint should always return a record whose
    own DOI matches what was requested. If it doesn't, something upstream
    mis-resolved (concretely observed: PubMed's esearch mis-tokenizing DOIs
    that contain underscores/embedded text, e.g.
    '10.4103/indianjpsychiatry_752_24', silently returning an unrelated
    article instead of a clean "not found"). Discarding a result we can't
    verify is far safer than trusting it under a high-confidence status -
    this is a last-resort safety net even after fixing the known root cause
    in sources/pubmed.py, in case another source misbehaves the same way.
    requested_doi is assumed already normalized."""
    if not parsed:
        return False
    got = normalize_doi(parsed.get("doi") or "")
    return bool(got) and got != requested_doi


def _safe_result(future, name):
    """Unwrap a future, turning a FetchError into (None, <source name>) so
    the caller can tell 'this source failed transiently, retry later' apart
    from 'this source returned nothing' (a clean, final 404)."""
    try:
        return future.result(), None
    except FetchError:
        return None, name
    except Exception as e:  # don't let one weird bug kill the whole record
        return None, f"{name} (unexpected: {e})"


def _safe_pair(future, name):
    try:
        return future.result(), None
    except FetchError:
        return (None, 0.0), name
    except Exception as e:
        return (None, 0.0), f"{name} (unexpected: {e})"


def _fetch_doi_all(doi):
    """Query all three sources concurrently by DOI. Returns
    (oa_raw, pm_raw, cr_raw, fetch_errors) - fetch_errors lists sources that
    failed transiently (timeout/rate-limit/5xx), NOT sources that cleanly
    returned 'not found'."""
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        f_oa = ex.submit(openalex.openalex_by_doi, doi)
        f_pm = ex.submit(pubmed.pubmed_by_doi, doi)
        f_cr = ex.submit(crossref.crossref_by_doi, doi)
        oa_raw, oa_err = _safe_result(f_oa, "OpenAlex")
        pm_raw, pm_err = _safe_result(f_pm, "PubMed")
        cr_raw, cr_err = _safe_result(f_cr, "Crossref")
    return oa_raw, pm_raw, cr_raw, [e for e in (oa_err, pm_err, cr_err) if e]


def _fetch_title_openalex_pubmed(title):
    """Query OpenAlex + PubMed concurrently by title. Each returns
    (candidate, score); also returns a list of sources that failed
    transiently (see _fetch_doi_all).

    Crossref is deliberately NOT included here - it's queried separately,
    first, in process_record's title-fallback (see _crossref_first_cascade
    notes there). Crossref has no usage budget and is purpose-built for
    title->DOI resolution, so it's tried alone first; OpenAlex/PubMed are
    only brought in by title search if Crossref alone isn't confident -
    this keeps OpenAlex's budget-limited Search calls off the common case."""
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        f_oa = ex.submit(openalex.openalex_by_title, title)
        f_pm = ex.submit(pubmed.pubmed_by_title, title)
        oa_pair, oa_err = _safe_pair(f_oa, "OpenAlex")
        pm_pair, pm_err = _safe_pair(f_pm, "PubMed")
    return oa_pair, pm_pair, [e for e in (oa_err, pm_err) if e]


def process_record(sno, clean_title, doi_raw, retry_count=0):
    """Returns (row, matched_by, match_status, incomplete).

    incomplete=True means one or more sources failed transiently (timeout/
    rate-limit/5xx) rather than cleanly returning "not found" - the caller
    (pipeline.py) should NOT checkpoint this record as permanently done, so
    it gets retried on a later run instead of silently locking in partial
    data (e.g. a record with no affiliations only because OpenAlex - the
    main affiliation source - happened to time out)."""
    notes = []
    fetch_errors = []
    doi = normalize_doi(doi_raw)

    # FIX: a blank Excel cell comes through as pandas' float NaN, and
    # `str(float('nan'))` is the literal 3-character string "nan" - which is
    # truthy and looks like real title text. Without this guard, a record
    # with no title at all would get searched for the literal word "nan"
    # and silently auto-matched (100% confidence) to any real paper whose
    # title happens to contain "nan" (e.g. a false match onto "Nan Goldin"
    # was observed in testing) instead of being correctly flagged as having
    # no usable title. normalize_doi() already had this exact guard for the
    # DOI side (see text_utils.normalize_doi's `d.lower() == "nan"` check);
    # this brings the title side in line with it.
    is_blank_title = (
        clean_title is None
        or (isinstance(clean_title, float) and clean_title != clean_title)  # NaN
        or str(clean_title).strip().lower() in ("", "nan", "none")
    )
    clean_title = "" if is_blank_title else str(clean_title).strip()

    oa_parsed, pm_parsed, cr_parsed = {}, {}, {}
    matched_by = None
    match_status = "No match"
    overall_score = 0.0
    candidate_title = ""
    candidate_source = ""

    # ---------- 1) DOI path: all three sources concurrently ----------
    if doi:
        oa_raw, pm_raw, cr_raw, errs = _fetch_doi_all(doi)
        fetch_errors.extend(errs)
        failed_sources = set(e.split(" ")[0] for e in errs)

        if oa_raw:
            oa_parsed = openalex.parse_openalex(oa_raw)
            if _doi_mismatch(doi, oa_parsed):
                notes.append(f"DISCARDED OpenAlex DOI result: returned DOI {oa_parsed.get('doi')} != requested {doi}")
                oa_parsed, oa_raw = {}, None
        if pm_raw:
            pm_parsed = pm_raw
            if _doi_mismatch(doi, pm_parsed):
                notes.append(f"DISCARDED PubMed DOI result: returned DOI {pm_parsed.get('doi')} != requested {doi}")
                pm_parsed, pm_raw = {}, None
        if cr_raw:
            cr_parsed = crossref.parse_crossref(cr_raw)
            if _doi_mismatch(doi, cr_parsed):
                notes.append(f"DISCARDED Crossref DOI result: returned DOI {cr_parsed.get('doi')} != requested {doi}")
                cr_parsed, cr_raw = {}, None

        if oa_raw or pm_raw or cr_raw:
            matched_by = "DOI"
            match_status = "Auto-accepted (DOI)"
            overall_score = 100.0
            # Only report a source as "not found" if it cleanly 404'd -
            # a source that failed transiently is reported separately below,
            # not conflated with "this DOI genuinely isn't in that database".
            missing = [n for n, v in (("OpenAlex", oa_raw), ("PubMed", pm_raw), ("Crossref", cr_raw))
                       if not v and n not in failed_sources]
            if missing:
                notes.append(f"DOI not found in: {', '.join(missing)}")
        elif errs:
            # Nothing came back positive, AND at least one source failed
            # transiently rather than confirming a clean 404 - we genuinely
            # don't know yet whether this DOI exists in any source. Do NOT
            # fall through to fuzzy title-matching below: this record
            # already has a specific, verifiable identity (the DOI), and a
            # transient network blip shouldn't cause it to get matched
            # against a DIFFERENT paper via fuzzy title search. Wait for
            # the retry instead.
            matched_by = "DOI_PENDING"
            match_status = "Pending retry (DOI fetch error)"
            notes.append(f"DOI lookup inconclusive (fetch error on: {', '.join(errs)}) - "
                          f"skipping title fallback this run to avoid a wrong match; will retry the DOI directly.")
        else:
            notes.append("DOI not found in: OpenAlex, PubMed, Crossref")
        if errs:
            notes.append(f"FETCH ERROR (will retry): {', '.join(errs)}")

    # ---------- 2) Title fallback: Crossref FIRST (free/unlimited, and
    # purpose-built for title->DOI resolution), then enrich via the
    # resolved DOI - which is an unlimited "single entity" OpenAlex call,
    # even without an OpenAlex key. Only if Crossref alone isn't confident
    # do we spend OpenAlex's budget-limited Search calls by also trying
    # OpenAlex/PubMed title search. This mirrors the original intended
    # design (title -> DOI resolution via Crossref -> enrichment) instead
    # of hitting all three sources' title search on every no-DOI record. ----------
    if matched_by is None and clean_title:
        notes.append("DOI missing or not found - resolving via Crossref title search first (free/unlimited)")

        cr_title_err = None
        try:
            cr_cand, cr_score = crossref.crossref_by_title(clean_title)
        except FetchError:
            cr_cand, cr_score = None, 0.0
            cr_title_err = "Crossref"
            fetch_errors.append(cr_title_err)

        cr_title_parsed = crossref.parse_crossref(cr_cand) if cr_cand else {}
        resolved_doi = normalize_doi(cr_title_parsed.get("doi", "")) if cr_title_parsed else ""

        if cr_score >= config.FUZZY_REVIEW_MIN and resolved_doi:
            # Confident Crossref match with a usable DOI - enrich via the
            # DOI-lookup path (unlimited on OpenAlex) instead of a Search call.
            notes.append(f"Crossref title match ({cr_score}%) resolved DOI {resolved_doi} - "
                          f"enriching via DOI lookup (OpenAlex/PubMed/Crossref)")
            oa_raw2, pm_raw2, cr_raw2, errs3 = _fetch_doi_all(resolved_doi)
            fetch_errors.extend(errs3)
            if errs3:
                notes.append(f"FETCH ERROR (DOI enrichment after Crossref match, will retry): {', '.join(errs3)}")

            if oa_raw2:
                oa_parsed = openalex.parse_openalex(oa_raw2)
                if _doi_mismatch(resolved_doi, oa_parsed):
                    notes.append(f"DISCARDED OpenAlex DOI-enrichment result: returned DOI {oa_parsed.get('doi')} != resolved {resolved_doi}")
                    oa_parsed = {}
            if pm_raw2:
                pm_parsed = pm_raw2
                if _doi_mismatch(resolved_doi, pm_parsed):
                    notes.append(f"DISCARDED PubMed DOI-enrichment result: returned DOI {pm_parsed.get('doi')} != resolved {resolved_doi}")
                    pm_parsed = {}
            cr_parsed = crossref.parse_crossref(cr_raw2) if cr_raw2 else cr_title_parsed
            if cr_raw2 and _doi_mismatch(resolved_doi, cr_parsed):
                notes.append(f"DISCARDED Crossref DOI-enrichment result: returned DOI {cr_parsed.get('doi')} != resolved {resolved_doi}")
                cr_parsed = cr_title_parsed  # fall back to the already-trusted title-search match

            matched_by = "TITLE"
            overall_score = cr_score
            candidate_title = cr_title_parsed.get("title", "")
            candidate_source = "Crossref"
            match_status = ("Auto-accepted (Title)" if cr_score >= config.FUZZY_AUTO_ACCEPT
                             else "Needs manual review")
            notes.append(f"Best title match: Crossref ({cr_score}%)")
        else:
            # Crossref alone wasn't confident (or errored) - give OpenAlex
            # and PubMed a shot by title too. Still costs OpenAlex Search
            # budget, but now only for the harder cases Crossref couldn't
            # resolve, not every single no-DOI record.
            if cr_score > 0:
                notes.append(f"Crossref title match only {cr_score}% - trying OpenAlex/PubMed title search too")
            else:
                notes.append("No confident Crossref title match - trying OpenAlex/PubMed title search")

            (oa_cand, oa_score), (pm_cand, pm_score), errs2 = _fetch_title_openalex_pubmed(clean_title)
            fetch_errors.extend(errs2)
            if errs2:
                notes.append(f"FETCH ERROR (title search, will retry): {', '.join(errs2)}")
            all_errs = errs2 + ([cr_title_err] if cr_title_err else [])

            scored = [
                ("OpenAlex", oa_score, openalex.parse_openalex(oa_cand) if oa_cand else {}),
                ("PubMed", pm_score, pm_cand or {}),
                ("Crossref", cr_score, cr_title_parsed),
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            best_source, best_score, best_parsed = scored[0]
            overall_score = best_score
            candidate_title = best_parsed.get("title", "") if best_parsed else ""
            candidate_source = best_source

            if best_score >= config.FUZZY_REVIEW_MIN:
                for name, score, parsed in scored:
                    if score >= config.FUZZY_REVIEW_MIN and parsed:
                        if name == "OpenAlex":
                            oa_parsed = parsed
                        elif name == "PubMed":
                            pm_parsed = parsed
                        elif name == "Crossref":
                            cr_parsed = parsed
                matched_by = "TITLE"
                match_status = ("Auto-accepted (Title)" if best_score >= config.FUZZY_AUTO_ACCEPT
                                 else "Needs manual review")
                notes.append(f"Best title match: {best_source} ({best_score}%)")
            elif best_score > 0:
                match_status = "No match"
                notes.append(f"Best title candidate only {best_score}% ({best_source}) - below review floor "
                              f"({config.FUZZY_REVIEW_MIN}%)")
            elif all_errs:
                # All scores are 0, but at least one source never actually
                # answered (transient failure) - "no candidates found in any
                # source" would be a false claim, since that source never got
                # a fair shot. Mark this as pending rather than a confirmed
                # no-match; fetch_errors already ensures it gets retried.
                match_status = "Pending retry (title fetch error)"
                notes.append(f"No candidates found in the source(s) that responded - {', '.join(all_errs)} "
                              f"failed to respond this attempt, will retry")
            else:
                match_status = "No match"
                notes.append("No candidates found in any source")

    if not doi and not clean_title:
        notes.append("No DOI and no title provided")
        match_status = "No match"

    # ---------- 3) Best-effort acknowledgment (opt-in, PMC full text only) ----------
    acknowledgment = ""
    pmcid = pm_parsed.get("pmcid") if pm_parsed else ""
    if config.FETCH_ACKNOWLEDGMENT and pmcid:
        try:
            acknowledgment = pubmed.pmc_fetch_acknowledgment(pmcid)
            if not acknowledgment:
                notes.append("Acknowledgment: PMCID present but no PMC full-text Acknowledgment section found")
        except FetchError:
            fetch_errors.append("PMC-Acknowledgment")
            notes.append("FETCH ERROR (PMC acknowledgment, will retry)")

    incomplete = bool(fetch_errors) and retry_count < config.MAX_FETCH_RETRIES
    if fetch_errors and not incomplete:
        notes.append(f"Gave up retrying after {retry_count} attempt(s) - flagged for manual review")
        if match_status not in ("Auto-accepted (DOI)",):
            match_status = "Needs manual review"

    row = build_row(sno, clean_title, doi_raw, oa_parsed, pm_parsed, cr_parsed, notes,
                     match_status=match_status, match_score=overall_score,
                     match_source=(matched_by or candidate_source or ""),
                     candidate_title=candidate_title, fetch_errors=fetch_errors,
                     retry_count=retry_count, acknowledgment=acknowledgment)
    return row, matched_by, match_status, incomplete
