"""
networks.py
===========
Generic co-occurrence / collaboration network builders for the
Scientometrics Visualization tool (Phase 2). Ported from the ICMR fork's
generate_vosviewer_exports.py (same validated harmonization: country
cleaning, keyword thesaurus, institution extraction), decoupled from file
I/O so the same networks can be rendered interactively AND exported as
VOSviewer .map/.net files.

Every builder returns a Network:
    items:  {id: label}
    edges:  {(id_a, id_b): weight}
    extra:  {id: {"weight<...>": w, "score<...>": s}}
which feeds both the Plotly renderer (charts.network_figure) and the
VOSviewer exporter (vosviewer_bytes) below.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Dict, Tuple

import pandas as pd

MAX_INSTITUTIONS_PER_PAPER = 30
MAX_COUNTRIES_PER_PAPER = 20
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s;,]+")


# ---------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------
def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _fix_text(s):
    return str(s)


def _norm_name(n):
    return re.sub(r"\s+", " ", _fix_text(n)).strip().strip(".,;")


def _split_list(cell, sep=";"):
    if _blank(cell):
        return []
    return [s.strip() for s in str(cell).split(sep) if s.strip()]


def _clean_mesh_term(t):
    t = t.strip().lstrip("*").strip()
    if "/" in t:
        t = t.split("/")[0].strip()
    return t


# ---------------------------------------------------------------------
# Country cleaning (canonical names, prefer common_name)
# ---------------------------------------------------------------------
try:
    import pycountry
    _COUNTRY_LOOKUP = {}
    for _c in pycountry.countries:
        _canonical = getattr(_c, "common_name", None) or getattr(_c, "name", None)
        if not _canonical:
            continue
        for _nm in filter(None, [getattr(_c, "name", None), getattr(_c, "common_name", None),
                                 getattr(_c, "official_name", None)]):
            _COUNTRY_LOOKUP[_nm.strip().lower()] = _canonical
    _HAVE_PYCOUNTRY = True
except Exception:
    pycountry = None
    _COUNTRY_LOOKUP = {}
    _HAVE_PYCOUNTRY = False

_ALIASES = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "south korea": "South Korea", "korea, republic of": "South Korea", "republic of korea": "South Korea",
    "russia": "Russia", "russian federation": "Russia",
    "turkiye": "Turkiye", "turkey": "Turkiye", "türkiye": "Turkiye",
    "vietnam": "Vietnam", "viet nam": "Vietnam", "iran": "Iran", "iran, islamic republic of": "Iran",
    "syria": "Syria", "laos": "Laos", "czechia": "Czechia", "czech republic": "Czechia",
    "ivory coast": "Ivory Coast", "cote d'ivoire": "Ivory Coast", "côte d'ivoire": "Ivory Coast",
    "hong kong": "Hong Kong", "taiwan": "Taiwan", "taiwan, province of china": "Taiwan",
    "moldova": "Moldova", "moldova, republic of": "Moldova",
    "tanzania": "Tanzania", "tanzania, united republic of": "Tanzania",
    "bolivia": "Bolivia", "venezuela": "Venezuela",
    "north macedonia": "North Macedonia", "macedonia": "North Macedonia",
    "eswatini": "Eswatini", "swaziland": "Eswatini", "cape verde": "Cabo Verde", "cabo verde": "Cabo Verde",
    "democratic republic of the congo": "DR Congo", "burma": "Myanmar", "myanmar": "Myanmar",
    "palestine": "Palestine", "palestine, state of": "Palestine",
    "bosnia": "Bosnia and Herzegovina", "bosnia and herzegovina": "Bosnia and Herzegovina",
}
for _k, _v in _ALIASES.items():
    _COUNTRY_LOOKUP.setdefault(_k, _v)
_SORTED_KEYS = sorted(_COUNTRY_LOOKUP.keys(), key=len, reverse=True)


def _resolve_country_token(t):
    tt = t.strip()
    key = tt.lower().rstrip(".")
    if key in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[key]
    bare = tt.rstrip(".")
    if len(bare) == 2 and bare.isalpha() and _HAVE_PYCOUNTRY:
        c = pycountry.countries.get(alpha_2=bare.upper())
        if c:
            nm = getattr(c, "common_name", None) or c.name
            return _ALIASES.get(nm.strip().lower(), nm)
    lead = tt.split(".")[0].strip().lower()
    if lead in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[lead]
    low = " " + re.sub(r"[^a-z0-9 ]", " ", tt.lower()) + " "
    for k in _SORTED_KEYS:
        if len(k) < 3:
            continue
        if f" {k} " in low:
            return _COUNTRY_LOOKUP[k]
    return None


def clean_country_cell(cell):
    if _blank(cell):
        return []
    out = []
    for t in [x.strip() for x in str(cell).split(";") if x.strip()]:
        r = _resolve_country_token(t)
        if r and r not in out:
            out.append(r)
    return out


# ---------------------------------------------------------------------
# Keyword thesaurus
# ---------------------------------------------------------------------
MESH_STOPWORDS = {
    "humans", "human", "animals", "animal", "male", "female", "adult", "adolescent",
    "aged", "aged, 80 and over", "middle aged", "young adult", "child", "child, preschool",
    "infant", "infant, newborn", "pregnancy", "mice", "rats", "rabbits", "dogs", "cats",
    "cross-sectional studies", "retrospective studies", "prospective studies", "cohort studies",
    "case-control studies", "follow-up studies", "longitudinal studies", "risk factors",
    "prevalence", "incidence", "surveys and questionnaires", "reproducibility of results",
    "india", "china", "united states", "socioeconomic factors", "age factors", "sex factors",
    "time factors", "treatment outcome", "severity of illness index", "disease models, animal",
    "sensitivity and specificity", "cell line, tumor", "predictive value of tests", "case reports",
    "comorbidity", "logistic models", "computer simulation", "questionnaires", "data collection",
    "cell line", "models, biological", "models, animal",
}
KEYWORD_SYNONYMS = {
    "preeclampsia": "pre-eclampsia", "alzheimer's disease": "alzheimer disease",
    "alzheimer’s disease": "alzheimer disease", "non-communicable diseases": "noncommunicable diseases",
    "biomarker": "biomarkers", "biofilms": "biofilm",
    "whole-genome sequencing": "whole genome sequencing", "cardiovascular disease": "cardiovascular diseases",
    "md simulations": "md simulation", "covid19": "covid-19", "sars-cov-2": "covid-19",
    "coronavirus disease 2019": "covid-19",
}


# ---------------------------------------------------------------------
# Institution extraction
# ---------------------------------------------------------------------
INSTITUTION_KEYWORDS = re.compile(
    r"\b(university|institute|college|hospital|centre|center|academy|school of|"
    r"foundation|council|corporation|laborator|icmr[- ]|medical college|research institute)\b",
    re.IGNORECASE)
_TRAILING_ACRONYM_RE = re.compile(r"\s*\(([A-Za-z&]{2,8})\)\s*$")
_LEADING_ARTICLE_RE = re.compile(r"^(the)\s+", re.IGNORECASE)
INSTITUTION_ALIASES = {"all india institute of medical science": "All India Institute of Medical Sciences"}


def _strip_redundant_acronym(name):
    name = _TRAILING_ACRONYM_RE.sub("", name).strip()
    name = _LEADING_ARTICLE_RE.sub("", name).strip()
    return INSTITUTION_ALIASES.get(name.lower(), name)


def _extract_institutions_from_affiliation(aff_string):
    out = []
    for aff in _fix_text(aff_string).split(";"):
        aff = re.sub(r"\S+@\S+", "", aff)
        segs = [s.strip(" .") for s in aff.split(",") if s.strip(" .")]
        matches = [s for s in segs if INSTITUTION_KEYWORDS.search(s)]
        if matches:
            out.append(matches[-1])
        elif segs:
            out.append(segs[0])
    return [_strip_redundant_acronym(o) for o in out if o and len(o) > 3]


def _parse_author_affiliation_map(raw):
    if _blank(raw):
        return []
    raw = str(raw).strip()
    insts = []
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            for aff in d.values():
                insts.extend(_extract_institutions_from_affiliation(str(aff)))
            return insts
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
    if "|" in raw or "(" in raw:
        for part in raw.split("|"):
            m = re.search(r"\((.*)\)\s*$", part.strip())
            if m:
                insts.extend(_extract_institutions_from_affiliation(m.group(1)))
        if insts:
            return insts
    return _extract_institutions_from_affiliation(raw)


ICMR_HQ_LABEL = "ICMR Headquarters, New Delhi (not a constituent institute)"
ICMR_CCOE_LABEL = "ICMR Collaborating Centre of Excellence (external partner institution, not one of the 28 core institutes)"
ICMR_ACRONYM = {
    "ICMR-National JALMA Institute for Leprosy & Other Mycobacterial Diseases, Agra": "NJILOMD",
    "ICMR-National Institute of Occupational Health Research, Ahmedabad": "NIOHR",
    "ICMR-National Institute of Traditional Medicine, Belagavi": "NITM",
    "ICMR-National Institute of NCDs Epidemiology, Bengaluru": "NINE",
    "ICMR-Bhopal Memorial Hospital & Research Centre, Bhopal": "BMHRC",
    "ICMR-National Institute for Research in Environmental Health, Bhopal": "NIREH",
    "ICMR-National Institute of Health Research, Bhubaneswar": "NIHR",
    "ICMR-National Institute for Research in Tuberculosis, Chennai": "NIRT",
    "ICMR-National Institute of Epidemiology, Chennai": "NIE",
    "ICMR-National Institute of Malaria Research, Delhi": "NIMR",
    "ICMR-National Institute for Research in Digital Health, Delhi": "NIRDH",
    "ICMR-National Institute of Child Health Research, Delhi": "NICHR",
    "ICMR-National Institute of Health Research, Dibrugarh": "NIHR",
    "ICMR-National Institute of Health Research, Gorakhpur": "NIHR",
    "ICMR-National Institute of Nutrition, Hyderabad": "NIN",
    "ICMR-National Institute for Pre-Clinical Research, Hyderabad": "NIPCR",
    "ICMR-National Institute for Tribal Health Research, Jabalpur": "NITHR",
    "ICMR-National Institute of Health Research, Jodhpur": "NIHR",
    "ICMR-National Institute for Research in Bacterial Infections, Kolkata": "NIRBI",
    "ICMR-National Institute of One Health, Nagpur": "NIOH (Nagpur)",
    "ICMR-National Institute for Research on Blood and Immune Disorders, Mumbai": "NIRBID",
    "ICMR-National Institute for Research on Women's Health, Mumbai": "NIRWoH",
    "ICMR-National Institute of Cancer Prevention and Research, Noida": "NICPR",
    "ICMR-Rajendra Memorial National Institute of Health Research, Patna": "RM NIHR",
    "ICMR-National Institute of Vector Control Research, Puducherry": "NIVCR",
    "ICMR-National Institute of Virology, Pune": "NIV",
    "ICMR-National Institute of Translational Virology and AIDS Research, Pune": "NITVAR",
    "ICMR-Regional Medical Research Centre, Sri Vijaya Puram": "RMRCSVP",
}
_ICMR_MARKERS = ["icmr", "indian council of medical research", "regional medical research",
                 "national institute of", "national jalma", "jalma institute"]


def _icmr_short_label(current_name):
    if current_name == ICMR_HQ_LABEL:
        return "ICMR HQ"
    if current_name == ICMR_CCOE_LABEL:
        return "ICMR CCoE"
    acronym = ICMR_ACRONYM.get(current_name)
    if not acronym:
        return current_name
    city = current_name.rsplit(",", 1)[-1].strip()
    return f"ICMR-{acronym}, {city}"


def _looks_icmr(name):
    low = name.lower()
    return any(m in low for m in _ICMR_MARKERS)


# ---------------------------------------------------------------------
# Common id/label assembly
# ---------------------------------------------------------------------
def _assemble(doc_count, cite_sum, pair_weight, weight_label="Documents", min_docs=1, keep=None):
    names = sorted(n for n in doc_count if (keep is None or n in keep) and doc_count[n] >= min_docs)
    id_of = {n: str(i + 1) for i, n in enumerate(names)}
    keepset = set(names)
    items = {id_of[n]: n for n in names}
    extra = {id_of[n]: {f"weight<{weight_label}>": doc_count[n], "score<Citations>": round(cite_sum[n], 1)}
             for n in names}
    edges = {}
    for (a, b), w in pair_weight.items():
        if a in keepset and b in keepset:
            edges[(id_of[a], id_of[b])] = w
    return items, edges, extra


# ---------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------
def author_collab(df):
    pair, docs, cites = Counter(), Counter(), Counter()
    for _, row in df.iterrows():
        names = set()
        for col in ("First Author", "Last Author"):
            if not _blank(row.get(col)):
                names.add(_norm_name(row[col]))
        for c in _split_list(row.get("Corresponding Author")):
            names.add(_norm_name(c))
        names.discard("")
        cv = float(row.get("Citations")) if not _blank(row.get("Citations")) else 0.0
        for n in names:
            docs[n] += 1
            cites[n] += cv
        for a, b in combinations(sorted(names), 2):
            pair[(a, b)] += 1
    return _assemble(docs, cites, pair, "Documents")


def institution_collab(df, icmr_mode=False, min_docs=2):
    pair, docs, cites = Counter(), Counter(), Counter()
    for _, row in df.iterrows():
        insts = set()
        if icmr_mode:
            for col in ("ICMR Institute (Current Name)", "ICMR Institute (Current Name) (New)"):
                if col in df.columns:
                    insts |= {_icmr_short_label(x) for x in _split_list(row.get(col))}
        ext = set(_parse_author_affiliation_map(row.get("Author_Affiliation_Map")))
        if not ext and not _blank(row.get("Affliation")):
            ext = set(_extract_institutions_from_affiliation(str(row.get("Affliation"))))
        if icmr_mode:
            ext = {i for i in ext if i and not _looks_icmr(i)}
        insts |= {i for i in ext if i}
        insts = {i for i in insts if i}
        if len(insts) > MAX_INSTITUTIONS_PER_PAPER:
            continue
        cv = float(row.get("Citations")) if not _blank(row.get("Citations")) else 0.0
        for i in insts:
            docs[i] += 1
            cites[i] += cv
        for a, b in combinations(sorted(insts), 2):
            pair[(a, b)] += 1
    return _assemble(docs, cites, pair, "Documents", min_docs=min_docs,
                     keep={i for i, c in docs.items() if c >= min_docs})


def country_collab(df, exclude_india=False):
    pair, docs, cites = Counter(), Counter(), Counter()
    for _, row in df.iterrows():
        countries = set(clean_country_cell(row.get("All Country")))
        if exclude_india:
            countries.discard("India")
        if len(countries) > MAX_COUNTRIES_PER_PAPER or len(countries) < 1:
            continue
        cv = float(row.get("Citations")) if not _blank(row.get("Citations")) else 0.0
        for c in countries:
            docs[c] += 1
            cites[c] += cv
        for a, b in combinations(sorted(countries), 2):
            pair[(a, b)] += 1
    return _assemble(docs, cites, pair, "Documents")


def keyword_cooccurrence(df, min_occurrence=5):
    doc_terms, display = [], {}
    for _, row in df.iterrows():
        terms = set()
        raw_kws = _split_list(row.get("Author Keywords (Other Terms)")) + \
            [_clean_mesh_term(m) for m in _split_list(row.get("MeSH Terms"))]
        for kw in raw_kws:
            k = kw.strip().lower()
            k = KEYWORD_SYNONYMS.get(k, k)
            if k and k not in MESH_STOPWORDS and len(k) > 2:
                terms.add(k)
                display.setdefault(k, kw.strip())
        doc_terms.append(terms)
    doc_count = Counter()
    for terms in doc_terms:
        for t in terms:
            doc_count[t] += 1
    kept = {t for t, c in doc_count.items() if c >= min_occurrence}
    pair = Counter()
    for terms in doc_terms:
        for a, b in combinations(sorted(terms & kept), 2):
            pair[(a, b)] += 1
    names = sorted(kept)
    id_of = {t: str(i + 1) for i, t in enumerate(names)}
    items = {id_of[t]: display.get(t, t) for t in names}
    extra = {id_of[t]: {"weight<Occurrences>": doc_count[t], "score<Occurrences>": doc_count[t]} for t in names}
    edges = {(id_of[a], id_of[b]): w for (a, b), w in pair.items() if w > 0}
    return items, edges, extra


def bibliographic_coupling(df, min_shared_refs=2):
    doi_to_papers = defaultdict(set)
    label, cites, refcount = {}, {}, {}
    for idx, row in df.iterrows():
        sno = str(row.get("Sno.", idx))
        title = _fix_text(row.get("TITLE", "")).strip()
        fa = _fix_text(row.get("First Author", "")).strip()
        yr = row.get("YEAR", "")
        yr = str(int(yr)) if not _blank(yr) and str(yr).replace(".0", "").isdigit() else str(yr)
        ts = (title[:60].rsplit(" ", 1)[0] + "…") if len(title) > 63 else title
        label[sno] = (f"{fa} {yr} - {ts}".strip(" -")) or f"Paper {sno}"
        cites[sno] = float(row.get("Citations")) if not _blank(row.get("Citations")) else 0.0
        dois = set()
        if not _blank(row.get("References")):
            dois = {m.group(0).rstrip(".,;)").lower() for m in DOI_RE.finditer(str(row.get("References")))}
        refcount[sno] = len(dois)
        for d in dois:
            doi_to_papers[d].add(sno)
    pair = Counter()
    for papers in doi_to_papers.values():
        if len(papers) < 2:
            continue
        for a, b in combinations(sorted(papers), 2):
            pair[(a, b)] += 1
    kept_edges = {p: w for p, w in pair.items() if w >= min_shared_refs}
    connected = {n for pr in kept_edges for n in pr}
    items = {sno: label[sno] for sno in connected}
    extra = {sno: {"weight<References>": refcount[sno], "score<Citations>": round(cites[sno], 1)} for sno in connected}
    return items, dict(kept_edges), extra


# ---------------------------------------------------------------------
# VOSviewer export (in-memory) — VOSviewer .map + .net text
# ---------------------------------------------------------------------
def vosviewer_bytes(items: Dict[str, str], edges: Dict[Tuple[str, str], int],
                    extra: Dict[str, dict] = None):
    extra = extra or {}
    extra_cols = sorted({c for v in extra.values() for c in v.keys()})
    lines = ["\t".join(["id", "label"] + extra_cols)]
    for iid, lbl in items.items():
        out = str(lbl).replace("\t", " ").replace('"', "'")
        if "," in out or ";" in out:
            out = '"' + out + '"'
        row = [str(iid), out] + [str(extra.get(iid, {}).get(c, 0)) for c in extra_cols]
        lines.append("\t".join(row))
    map_txt = "\n".join(lines) + "\n"
    net_txt = "".join(f"{a}\t{b}\t{w}\n" for (a, b), w in edges.items())
    return map_txt.encode("utf-8"), net_txt.encode("utf-8")
