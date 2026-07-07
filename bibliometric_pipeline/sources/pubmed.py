"""
sources/pubmed.py
==================
"""

import re
import sys
import xml.etree.ElementTree as ET

from .. import config
from ..http_utils import http_get, NCBI_LIMITER
from ..text_utils import clean_for_match, fuzzy_score, normalize_doi, uniq_keep_order, join_semicolon, is_icmr

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _ncbi_params(extra):
    p = dict(extra)
    p["tool"] = "bibliometric-extractor"
    p["email"] = config.CONTACT_EMAIL
    if config.NCBI_API_KEY:
        p["api_key"] = config.NCBI_API_KEY
    return p


def pubmed_esearch(term, retmax=None):
    retmax = retmax or config.TITLE_CANDIDATES
    params = _ncbi_params({"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json"})
    data = http_get(f"{EUTILS}/esearch.fcgi", params=params, expect="json", limiter=NCBI_LIMITER)
    if not data:
        return []
    return data.get("esearchresult", {}).get("idlist", []) or []


def pubmed_efetch_xml(pmids):
    if not pmids:
        return None
    if isinstance(pmids, (list, tuple)):
        pmids = ",".join(str(p) for p in pmids)
    params = _ncbi_params({"db": "pubmed", "id": pmids, "retmode": "xml", "rettype": "abstract"})
    return http_get(f"{EUTILS}/efetch.fcgi", params=params, expect="text", limiter=NCBI_LIMITER)


def _text(node):
    return "".join(node.itertext()).strip() if node is not None else ""


def parse_pubmed_article(article):
    """Parse one <PubmedArticle> element into a dict."""
    out = {}

    out["pmid"] = _text(article.find(".//MedlineCitation/PMID"))
    out["title"] = _text(article.find(".//Article/ArticleTitle"))

    parts = []
    for ab in article.findall(".//Article/Abstract/AbstractText"):
        label = ab.get("Label")
        txt = _text(ab)
        if not txt:
            continue
        parts.append(f"{label}: {txt}" if label else txt)
    out["abstract"] = " ".join(parts)

    out["journal"] = _text(article.find(".//Journal/Title"))
    issns = [_text(e) for e in article.findall(".//Journal/ISSN")]
    out["issn"] = join_semicolon(issns)

    doi = ""
    pmcid = ""
    for aid in article.findall(".//ArticleIdList/ArticleId"):
        idtype = aid.get("IdType")
        if idtype == "doi" and not doi:
            doi = _text(aid)
        elif idtype == "pmc" and not pmcid:
            pmcid = _text(aid)
    out["doi"] = doi
    out["pmcid"] = pmcid

    pub_date, year = "", None
    adate = article.find(".//Article/ArticleDate")
    if adate is not None:
        y = _text(adate.find("Year"))
        m = _text(adate.find("Month"))
        d = _text(adate.find("Day"))
        pub_date = "-".join([p for p in (y, m, d) if p])
        year = int(y) if y.isdigit() else None
    if not pub_date:
        pd_node = article.find(".//Journal/JournalIssue/PubDate")
        if pd_node is not None:
            y = _text(pd_node.find("Year"))
            m = _text(pd_node.find("Month"))
            d = _text(pd_node.find("Day"))
            medline = _text(pd_node.find("MedlineDate"))
            if y:
                pub_date = "-".join([p for p in (y, m, d) if p])
                year = int(y) if y.isdigit() else None
            elif medline:
                pub_date = medline
                mt = re.search(r"\d{4}", medline)
                year = int(mt.group()) if mt else None
    out["publication_date"] = pub_date
    out["year"] = year

    ptypes = [_text(p) for p in article.findall(".//PublicationTypeList/PublicationType")]
    out["pub_types"] = uniq_keep_order(ptypes)

    authors, affiliations, aff_map = [], [], {}
    first_author = last_author = first_author_aff = ""
    any_icmr = first_icmr = False

    auth_nodes = article.findall(".//AuthorList/Author")
    for idx, a in enumerate(auth_nodes):
        collective = _text(a.find("CollectiveName"))
        if collective:
            name = collective
        else:
            last = _text(a.find("LastName"))
            fore = _text(a.find("ForeName")) or _text(a.find("Initials"))
            name = (fore + " " + last).strip()
        if not name:
            continue
        authors.append(name)

        affs = [_text(af) for af in a.findall(".//AffiliationInfo/Affiliation")]
        affs = [x for x in affs if x]
        aff_text = "; ".join(uniq_keep_order(affs))
        if aff_text:
            aff_map[name] = aff_text
            affiliations.extend(affs)

        icmr_here = is_icmr(aff_text)
        any_icmr = any_icmr or icmr_here
        if idx == 0:
            first_author = name
            first_author_aff = aff_text
            first_icmr = icmr_here

    if authors:
        last_author = authors[-1]

    out["authors"] = authors
    out["affiliations"] = uniq_keep_order(affiliations)
    out["first_author"] = first_author
    out["last_author"] = last_author
    out["first_author_aff"] = first_author_aff
    out["aff_map"] = aff_map
    out["any_icmr"] = any_icmr
    out["first_icmr"] = first_icmr

    # Corresponding-author heuristic: PubMed doesn't flag this explicitly.
    # Convention: "Electronic address: ..." appears in the affiliation of
    # the corresponding author (usually senior/last author).
    corresponding_authors = [name for name, aff in aff_map.items()
                              if "electronic address" in aff.lower()]
    out["corresponding_authors"] = corresponding_authors

    mesh = [_text(m) for m in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName")]
    out["mesh"] = uniq_keep_order(mesh)
    kws = [_text(k) for k in article.findall(".//KeywordList/Keyword")]
    out["keywords"] = uniq_keep_order(kws)

    # Grants
    grants = []
    for g in article.findall(".//GrantList/Grant"):
        gid = _text(g.find("GrantID"))
        agency = _text(g.find("Agency"))
        label = " ".join(x for x in [agency, f"({gid})" if gid else ""] if x).strip()
        if label:
            grants.append(label)
    out["grants"] = uniq_keep_order(grants)

    # Conflict of interest statement (only source that reliably has this)
    out["coi"] = _text(article.find(".//CoiStatement"))

    return out


def pubmed_fetch_parsed(pmids):
    xml_text = pubmed_efetch_xml(pmids)
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        sys.stderr.write(f"   [pubmed] XML parse error: {e}\n")
        return []
    return [parse_pubmed_article(art) for art in root.findall(".//PubmedArticle")]


def pmc_fetch_acknowledgment(pmcid):
    """Best-effort: pull the Acknowledgment section out of the PMC full-text
    XML for a given PMCID.

    IMPORTANT CAVEAT: acknowledgments are NOT part of Crossref/OpenAlex/
    PubMed's abstract-level metadata - they only exist in full text. This
    only works for the subset of articles that (a) have a PMCID at all, and
    (b) are in PMC's open-access full-text subset. A PMCID being present is
    not a guarantee the full text (or its Acknowledgment section) is
    available - many subscription articles have a PMCID with only the
    abstract deposited. So an empty result here is normal/expected for most
    records, not a bug.
    """
    if not pmcid:
        return ""
    pmcid_num = re.sub(r"(?i)^pmc", "", str(pmcid).strip())
    if not pmcid_num:
        return ""
    params = _ncbi_params({"db": "pmc", "id": pmcid_num, "retmode": "xml"})
    xml_text = http_get(f"{EUTILS}/efetch.fcgi", params=params, expect="text", limiter=NCBI_LIMITER)
    if not xml_text:
        return ""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""
    parts = []
    for ack in root.findall(".//ack"):
        txt = _text(ack)
        if txt:
            parts.append(txt)
    if not parts:
        # some PMC XML tags the section as <sec sec-type="acknowledgment">
        # instead of a top-level <ack>
        for sec in root.findall(".//sec"):
            if (sec.get("sec-type") or "").lower().startswith("ack"):
                txt = _text(sec)
                if txt:
                    parts.append(txt)
    return " ".join(parts).strip()


def pubmed_by_doi(doi):
    doi = normalize_doi(doi)
    if not doi:
        return None
    # IMPORTANT: quote the DOI. Unquoted, PubMed's esearch query parser can
    # tokenize on characters like '_' and '/' instead of treating the DOI
    # as one literal identifier - observed concretely with DOIs like
    # '10.4103/indianjpsychiatry_752_24' (embedded journal name + article
    # number), where the unquoted search silently matched an unrelated
    # article from the same journal instead of returning a clean "not
    # found". Quoting forces an exact-phrase match.
    pmids = pubmed_esearch(f'"{doi}"[AID]', retmax=2)
    if not pmids:
        pmids = pubmed_esearch(f'"{doi}"[DOI]', retmax=2)
    if not pmids:
        return None
    parsed = pubmed_fetch_parsed(pmids[:1])
    if not parsed:
        return None
    result = parsed[0]
    # Defense in depth: even with quoting, never trust a DOI-keyed lookup
    # without checking the record we got back actually carries the DOI we
    # asked for. If it doesn't, treat it as "not found" rather than risk
    # silently returning a different paper's data.
    got_doi = normalize_doi(result.get("doi") or "")
    if got_doi and got_doi != doi:
        sys.stderr.write(f"   [pubmed] DOI mismatch: asked for {doi}, got {got_doi} back - discarding\n")
        return None
    return result


def pubmed_by_pmid(pmid):
    if not pmid:
        return None
    parsed = pubmed_fetch_parsed([pmid])
    return parsed[0] if parsed else None


def pubmed_by_title(title):
    """Returns (best_candidate, score) - always, even below threshold."""
    if not title:
        return None, 0.0
    pmids = pubmed_esearch(f"{title}[Title]", retmax=config.TITLE_CANDIDATES)
    if not pmids:
        pmids = pubmed_esearch(title, retmax=config.TITLE_CANDIDATES)
    if not pmids:
        return None, 0.0
    parsed = pubmed_fetch_parsed(pmids)
    target = clean_for_match(title)
    best, best_score = None, -1.0
    for rec in parsed:
        score = fuzzy_score(target, clean_for_match(rec.get("title", "")))
        if score > best_score:
            best, best_score = rec, score
    if best is not None:
        best["match_score"] = round(best_score, 1)
        return best, round(best_score, 1)
    return None, 0.0
