"""
sources/openalex.py
====================
"""

from .. import config
from ..http_utils import http_get, OPENALEX_LIMITER
from ..text_utils import clean_for_match, fuzzy_score, normalize_doi, uniq_keep_order, join_semicolon, is_icmr, country_name

BASE = "https://api.openalex.org/works"


def _openalex_params(extra):
    """OpenAlex now runs on a daily usage budget rather than the old
    mailto-based 'polite pool' - an api_key gives 10x the free daily
    budget. mailto is kept too (harmless, still used for the contact-info
    convention); the real lever here is api_key."""
    p = dict(extra)
    p["mailto"] = config.CONTACT_EMAIL
    if config.OPENALEX_API_KEY:
        p["api_key"] = config.OPENALEX_API_KEY
    return p


def openalex_by_doi(doi):
    doi = normalize_doi(doi)
    if not doi:
        return None
    url = f"{BASE}/https://doi.org/{doi}"
    return http_get(url, params=_openalex_params({}), expect="json", limiter=OPENALEX_LIMITER)


def openalex_by_title(title):
    """Returns (best_candidate, score) - always, even below threshold."""
    if not title:
        return None, 0.0
    params = _openalex_params({"search": title, "per-page": config.TITLE_CANDIDATES})
    data = http_get(BASE, params=params, expect="json", limiter=OPENALEX_LIMITER)
    if not data or not data.get("results"):
        return None, 0.0
    target = clean_for_match(title)
    best, best_score = None, -1.0
    for work in data["results"]:
        cand_title = work.get("display_name") or work.get("title") or ""
        score = fuzzy_score(target, clean_for_match(cand_title))
        if score > best_score:
            best, best_score = work, score
    if best is not None:
        best["_match_score"] = round(best_score, 1)
        return best, round(best_score, 1)
    return None, 0.0


def openalex_reconstruct_abstract(inverted_index):
    if not inverted_index:
        return ""
    positions = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in positions)


def parse_openalex(work):
    """Pull the fields we care about out of an OpenAlex work object."""
    if not work:
        return {}

    out = {}
    out["title"] = work.get("display_name") or work.get("title") or ""
    out["doi"] = (work.get("doi") or "").replace("https://doi.org/", "")
    out["type"] = work.get("type") or ""
    out["publication_date"] = work.get("publication_date") or ""
    out["year"] = work.get("publication_year")
    out["abstract"] = openalex_reconstruct_abstract(work.get("abstract_inverted_index"))
    out["cited_by_count"] = work.get("cited_by_count")
    out["referenced_works_count"] = (
        work.get("referenced_works_count")
        or len(work.get("referenced_works", []) or []))
    out["match_score"] = work.get("_match_score")

    ids = work.get("ids", {}) or {}
    pmid = ids.get("pmid")
    if pmid:
        pmid = pmid.rstrip("/").split("/")[-1]
    out["pmid"] = pmid

    oa = work.get("open_access", {}) or {}
    out["is_oa"] = oa.get("is_oa")
    out["oa_status"] = oa.get("oa_status")
    out["oa_url"] = oa.get("oa_url")

    ploc = work.get("primary_location", {}) or {}
    src = ploc.get("source", {}) or {}
    out["journal"] = src.get("display_name") or ""
    out["publisher"] = src.get("host_organization_name") or ""
    out["source_country"] = src.get("country_code") or ""
    issns = []
    if src.get("issn_l"):
        issns.append(src["issn_l"])
    for s in (src.get("issn") or []):
        issns.append(s)
    out["issn"] = join_semicolon(issns)
    out["landing_page_url"] = ploc.get("landing_page_url") or ""

    primary_topic = work.get("primary_topic") or {}
    out["subject_category"] = (primary_topic.get("display_name") or "")

    # OpenAlex deprecated 'concepts' in favor of 'topics' - the legacy field
    # is still present in the API but is no longer maintained/updated, so
    # newer works (most of what this pipeline processes) often have it
    # empty even when well-matched. 'topics' is the actively-maintained
    # replacement; fall back to the legacy 'concepts' field only if a work
    # genuinely has no topics data at all (older/edge-case records).
    topics = work.get("topics", []) or []
    topic_names = [t.get("display_name") for t in topics[:8] if t.get("display_name")]
    legacy_concepts = work.get("concepts", []) or []
    legacy_names = [c.get("display_name") for c in legacy_concepts[:8] if c.get("display_name")]
    out["concepts"] = join_semicolon(topic_names or legacy_names)

    # Grants / funding
    grants = []
    for g in (work.get("grants") or []):
        name = g.get("funder_display_name") or ""
        award = g.get("award_id") or ""
        label = " ".join(x for x in [name, f"({award})" if award else ""] if x).strip()
        if label:
            grants.append(label)
    out["grants"] = uniq_keep_order(grants)

    authors, affiliations, countries = [], [], []
    first_author = last_author = ""
    first_author_aff = ""
    corresponding_authors = []
    aff_map = {}
    author_country_map = {}
    any_icmr = first_icmr = corr_icmr = False

    authorships = work.get("authorships", []) or []
    for idx, au in enumerate(authorships):
        a = au.get("author", {}) or {}
        name = a.get("display_name") or ""
        if not name:
            continue
        authors.append(name)

        insts = [i.get("display_name") for i in au.get("institutions", []) if i.get("display_name")]
        raw_affs = au.get("raw_affiliation_strings", []) or []
        aff_text = "; ".join(uniq_keep_order(raw_affs or insts))
        if aff_text:
            aff_map[name] = aff_text
            affiliations.extend(insts or raw_affs)

        c_here = list(au.get("countries", []) or [])
        if not c_here:
            c_here = [i.get("country_code") for i in au.get("institutions", []) if i.get("country_code")]
        c_here = [c for c in c_here if c]
        countries.extend(c_here)
        if c_here and name not in author_country_map:
            author_country_map[name] = country_name(c_here[0])

        icmr_here = is_icmr(aff_text)
        any_icmr = any_icmr or icmr_here

        pos = au.get("author_position")
        if pos == "first" or idx == 0:
            first_author = first_author or name
            first_author_aff = first_author_aff or aff_text
            first_icmr = first_icmr or icmr_here
        if pos == "last":
            last_author = name
        if au.get("is_corresponding"):
            corresponding_authors.append(name)
            corr_icmr = corr_icmr or icmr_here

    if authors and not last_author:
        last_author = authors[-1]

    out["authors"] = authors
    out["affiliations"] = uniq_keep_order(affiliations)
    out["countries"] = uniq_keep_order(countries)
    out["first_author"] = first_author
    out["last_author"] = last_author
    out["first_author_aff"] = first_author_aff
    out["corresponding_authors"] = corresponding_authors
    out["aff_map"] = aff_map
    out["author_country_map"] = author_country_map
    out["any_icmr"] = any_icmr
    out["first_icmr"] = first_icmr
    out["corr_icmr"] = corr_icmr
    return out
