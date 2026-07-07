"""
sources/crossref.py
====================
"""

import re

from .. import config
from ..http_utils import http_get, CROSSREF_LIMITER
from ..text_utils import clean_for_match, fuzzy_score, uniq_keep_order, join_semicolon, is_icmr, normalize_doi

BASE = "https://api.crossref.org/works"


def crossref_by_doi(doi):
    doi = normalize_doi(doi)
    if not doi:
        return None
    url = f"{BASE}/{doi}"
    data = http_get(url, params={"mailto": config.CONTACT_EMAIL}, expect="json", limiter=CROSSREF_LIMITER)
    if not data:
        return None
    return data.get("message")


def crossref_by_title(title):
    """Returns (best_candidate, score) - always, even below threshold."""
    if not title:
        return None, 0.0
    params = {
        "query.bibliographic": title,
        "rows": config.TITLE_CANDIDATES,
        "mailto": config.CONTACT_EMAIL,
    }
    data = http_get(BASE, params=params, expect="json", limiter=CROSSREF_LIMITER)
    items = ((data or {}).get("message", {}) or {}).get("items", []) or []
    if not items:
        return None, 0.0

    target = clean_for_match(title)
    best, best_score = None, -1.0
    for item in items:
        titles = item.get("title") or []
        cand_title = titles[0] if titles else ""
        score = fuzzy_score(target, clean_for_match(cand_title))
        if score > best_score:
            best, best_score = item, score
    if best is not None:
        best["_match_score"] = round(best_score, 1)
        return best, round(best_score, 1)
    return None, 0.0


def _strip_jats(text):
    if not text:
        return ""
    return re.sub(r"</?jats:[^>]+>", "", text).strip()


def _format_reference(ref):
    """One Crossref 'reference' entry -> 'Author, Year, Title, Journal, DOI'
    (matches the Scopus-style reference-list format used downstream).

    Crossref's per-reference metadata is only as good as what the publisher
    deposited: some references arrive fully structured (author/year/
    article-title/journal-title/DOI all present), others only as a single
    'unstructured' citation string. We use whichever is available."""
    author = (ref.get("author") or "").strip()
    year = str(ref.get("year") or "").strip()
    title = (ref.get("article-title") or ref.get("volume-title") or "").strip()
    journal = (ref.get("journal-title") or "").strip()
    doi = (ref.get("DOI") or "").strip()

    if author or title or journal or doi:
        parts = [p for p in [author, year, title, journal, doi] if p]
        return ", ".join(parts)

    # Nothing structured at all - fall back to the raw citation string.
    return (ref.get("unstructured") or "").strip()


def parse_references(item):
    """Full reference list for one Crossref work, one formatted string per
    reference, ready to be semicolon-joined into a single cell.

    NOTE: Crossref only exposes this when the publisher deposited reference
    metadata with the DOI - not every DOI has it (many publishers, e.g. some
    society/regional journals, don't deposit references at all). An empty
    list here means "not deposited", not a parsing failure."""
    refs = item.get("reference") or []
    out = []
    for r in refs:
        formatted = _format_reference(r)
        if formatted:
            out.append(formatted)
    return out


def _crossref_date(item, *keys):
    for k in keys:
        node = item.get(k)
        if node and node.get("date-parts"):
            parts = node["date-parts"][0]
            parts = [str(p) for p in parts if p is not None]
            if parts:
                year = int(parts[0]) if parts[0].isdigit() else None
                return "-".join(parts), year
    return "", None


def parse_crossref(item):
    """Pull the fields we care about out of a Crossref work item."""
    if not item:
        return {}

    out = {}
    titles = item.get("title") or []
    out["title"] = titles[0] if titles else ""
    out["doi"] = (item.get("DOI") or "").lower()
    out["type"] = item.get("type") or ""

    pub_date, year = _crossref_date(item, "published", "published-print", "published-online", "issued")
    out["publication_date"] = pub_date
    out["year"] = year

    out["abstract"] = _strip_jats(item.get("abstract", ""))
    out["journal"] = (item.get("container-title") or [""])[0]
    out["publisher"] = item.get("publisher", "")
    out["issn"] = join_semicolon(item.get("ISSN") or [])
    out["citations"] = item.get("is-referenced-by-count")
    out["match_score"] = item.get("_match_score")

    out["references"] = parse_references(item)
    out["reference_count"] = item.get("reference-count") or len(out["references"]) or None

    # Funding
    grants = []
    for f in (item.get("funder") or []):
        name = f.get("name") or ""
        awards = f.get("award") or [None]
        for a in awards:
            label = " ".join(x for x in [name, f"({a})" if a else ""] if x).strip()
            if label:
                grants.append(label)
    out["grants"] = uniq_keep_order(grants)

    authors, aff_map = [], {}
    first_author = last_author = first_author_aff = ""
    any_icmr = first_icmr = False

    au_list = item.get("author") or []
    for idx, au in enumerate(au_list):
        name = " ".join(x for x in [au.get("given", ""), au.get("family", "")] if x).strip()
        if not name:
            continue
        authors.append(name)

        affs = [a.get("name") for a in (au.get("affiliation") or []) if a.get("name")]
        aff_text = "; ".join(uniq_keep_order(affs))
        if aff_text:
            aff_map[name] = aff_text

        icmr_here = is_icmr(aff_text)
        any_icmr = any_icmr or icmr_here
        if idx == 0:
            first_author, first_author_aff, first_icmr = name, aff_text, icmr_here

    if authors:
        last_author = authors[-1]

    out["authors"] = authors
    out["affiliations"] = uniq_keep_order(list(aff_map.values()))
    out["first_author"] = first_author
    out["last_author"] = last_author
    out["first_author_aff"] = first_author_aff
    out["aff_map"] = aff_map
    out["any_icmr"] = any_icmr
    out["first_icmr"] = first_icmr
    return out
