"""
icmr_institutes.py
===================
Shared matching logic for tagging an affiliation string with which of
ICMR's 28 constituent institutes it refers to (current official name),
even when the text uses an old/former name or a bare acronym.

This module is the single source of truth for the institute list and
matching rules. It's imported from two places:
  - matcher.py, so every NEW pipeline run tags this automatically as part
    of build_row() (opt-in via the "icmr_institute" column group).
  - icmr_institute_tagger.py, the standalone script, for tagging files
    that never went through the pipeline (e.g. a manually-curated,
    already-final Included_studies.xlsx).

MULTIPLE INSTITUTES IN ONE ROW
-------------------------------
A single record can list co-authors from more than one ICMR institute (real
multi-site collaborations - confirmed in 144/2632 rows of one real
dataset). match_all_icmr_institutes()/resolve_all_icmr_institutes() return
EVERY distinct institute found, semicolon-joined, not just the first one.
match_icmr_institute() is kept as a single-result convenience wrapper for
callers that only need one.

SOURCE OF THE INSTITUTE LIST
-----------------------------
Pulled directly from https://www.icmr.gov.in/institutes (official ICMR
website) on 2026-07-05 - all 28 institutes currently listed, along with
their former names where the site documents a rename (several institutes
have been renamed in just the last few years, e.g. NICED -> NIRBI, NARI ->
NITVAR, VCRC -> NIVCR, Jodhpur's DMRC -> NIIRNCD (2019) -> NIHR (2026)).
Matching checks BOTH current and former names/acronyms, but always TAGS
the row with the CURRENT name.

A NOTE ON THE "NIOH" ACRONYM COLLISION
----------------------------------------
ICMR now has TWO institutes that could plausibly be abbreviated "NIOH":
  - National Institute of Occupational Health Research, Ahmedabad (the long-
    established one, officially NIOHR, but very commonly still just called
    "NIOH" in older papers and even on some ICMR pages)
  - National Institute of One Health, Nagpur (newly established, 2026)
Since virtually every paper in a real dataset predates the brand-new Nagpur
institute, a bare "NIOH" (without "Nagpur"/"One Health" nearby) is resolved
to the Ahmedabad Occupational Health institute. If "one health" or "nagpur"
appears alongside it, it resolves to the Nagpur institute instead.
"""

import re

# ---------------------------------------------------------------------
# The 28 institutes, as listed on icmr.gov.in/institutes (fetched 2026-07-05).
# "match_phrases" = every current/former name and acronym worth matching on.
# Longer, distinctive phrases are safe to match without an "ICMR" nearby;
# short/generic acronyms (marked below) are only matched when "icmr" also
# appears somewhere in the same affiliation string, to avoid false positives.
# ---------------------------------------------------------------------
ICMR_INSTITUTES = [
    {
        "current_name": "ICMR-National JALMA Institute for Leprosy & Other Mycobacterial Diseases, Agra",
        "acronym": "NJILOMD",
        "match_phrases": [
            "national jalma institute", "jalma institute for leprosy",
            "central jalma institute for leprosy", "jalma institute",
        ],
        "short_acronyms": ["njilomd", "jalma"],
    },
    {
        "current_name": "ICMR-National Institute of Occupational Health Research, Ahmedabad",
        "acronym": "NIOHR",
        "match_phrases": [
            "national institute of occupational health research",
            "national institute of occupational health",
        ],
        "short_acronyms": ["niohr"],
        # "nioh" alone is ambiguous with the new Nagpur institute - handled
        # as a special case in match_icmr_institute(), not listed here.
    },
    {
        "current_name": "ICMR-National Institute of Traditional Medicine, Belagavi",
        "acronym": "NITM",
        "match_phrases": ["national institute of traditional medicine"],
        "short_acronyms": ["nitm"],
    },
    {
        "current_name": "ICMR-National Institute of NCDs Epidemiology, Bengaluru",
        "acronym": "NINE",
        "match_phrases": [
            "national institute of ncds epidemiology",
            "national institute of non communicable diseases epidemiology",
            "national centre for disease informatics and research",  # former name (NCDIR)
        ],
        "short_acronyms": ["nine", "ncdir"],
    },
    {
        "current_name": "ICMR-Bhopal Memorial Hospital & Research Centre, Bhopal",
        "acronym": "BMHRC",
        "match_phrases": ["bhopal memorial hospital"],
        "short_acronyms": ["bmhrc"],
    },
    {
        "current_name": "ICMR-National Institute for Research in Environmental Health, Bhopal",
        "acronym": "NIREH",
        "match_phrases": ["national institute for research in environmental health"],
        "short_acronyms": ["nireh"],
    },
    {
        "current_name": "ICMR-National Institute of Health Research, Bhubaneswar",
        "acronym": "NIHR",
        "match_phrases": [
            "regional medical research centre, bhubaneswar", "regional medical research center, bhubaneswar",
            "rmrc, bhubaneswar", "rmrc bhubaneswar",
        ],
        "short_acronyms": [],  # "NIHR" alone is used by 5 different ICMR institutes - needs the city
        "nihr_city": "Bhubaneswar",
        # "Chandrasekharpur" is the specific locality within Bhubaneswar
        # where this institute sits - real data showed 32 rows phrased as
        # "...Centre, Chandrasekharpur, Bhubaneswar" (an extra locality
        # inserted between "Centre," and the city, breaking a strict
        # adjacent-phrase match).
        "extra_locations": ["bhubaneswar", "bhubaneshwar", "chandrasekharpur"],
    },
    {
        "current_name": "ICMR-National Institute for Research in Tuberculosis, Chennai",
        "acronym": "NIRT",
        "match_phrases": [
            "national institute for research in tuberculosis",
            "national institute of research in tuberculosis",  # real-data "of" variant
        ],
        "short_acronyms": ["nirt"],
    },
    {
        "current_name": "ICMR-National Institute of Epidemiology, Chennai",
        "acronym": "NIE",
        "match_phrases": ["national institute of epidemiology"],
        "short_acronyms": ["nie"],
    },
    {
        "current_name": "ICMR-National Institute of Malaria Research, Delhi",
        "acronym": "NIMR",
        "match_phrases": ["national institute of malaria research"],
        "short_acronyms": ["nimr"],
    },
    {
        "current_name": "ICMR-National Institute for Research in Digital Health, Delhi",
        "acronym": "NIRDH",
        "match_phrases": [
            "national institute for research in digital health",
            "national institute of medical statistics",
        ],
        "short_acronyms": ["nirdh", "nims"],
    },
    {
        "current_name": "ICMR-National Institute of Child Health Research, Delhi",
        "acronym": "NICHR",
        "match_phrases": [
            "national institute of child health research",
            "national institute of child health and development research",  # real-data variant (NICHDR)
            "national institute of pathology",
        ],
        "short_acronyms": ["nichr", "nichdr", "nip"],
    },
    {
        "current_name": "ICMR-National Institute of Health Research, Dibrugarh",
        "acronym": "NIHR",
        "match_phrases": [
            "regional medical research centre, dibrugarh", "regional medical research centre, ne",
            "regional medical research centre (ne)", "rmrc ne", "rmrc, ne", "rmrc-ne",
            "regional medical research centre north east", "regional medical research centre, northeast",
            "regional medical research centre, north east",
        ],
        "short_acronyms": [],
        "nihr_city": "Dibrugarh",
        # AND-logic locations: an RMRC/NIHR signal PLUS any of these (not
        # necessarily adjacent in the text) also counts as a match - real
        # data showed "Regional Medical Research Centre, N.E. Region,
        # Dibrugarh, Assam" where "Centre," isn't immediately followed by
        # the city, breaking a strict adjacent-phrase match.
        "extra_locations": ["dibrugarh", "n.e. region", "north east region", "ne region"],
    },
    {
        "current_name": "ICMR-National Institute of Health Research, Gorakhpur",
        "acronym": "NIHR",
        "match_phrases": ["regional medical research centre, gorakhpur", "rmrc gorakhpur", "rmrc, gorakhpur"],
        "short_acronyms": [],
        "nihr_city": "Gorakhpur",
        # RMRC Gorakhpur is physically located on the BRD Medical College
        # campus and many papers cite it that way instead of naming the
        # city directly - real data showed 39 rows using this form.
        "extra_locations": ["gorakhpur", "brd medical college"],
    },
    {
        "current_name": "ICMR-National Institute of Nutrition, Hyderabad",
        "acronym": "NIN",
        "match_phrases": ["national institute of nutrition"],
        "short_acronyms": ["nin"],
    },
    {
        "current_name": "ICMR-National Institute for Pre-Clinical Research, Hyderabad",
        "acronym": "NIPCR",
        "match_phrases": ["national institute for pre-clinical research", "national institute for preclinical research"],
        "short_acronyms": ["nipcr"],
    },
    {
        "current_name": "ICMR-National Institute for Tribal Health Research, Jabalpur",
        "acronym": "NITHR",
        "match_phrases": [
            "national institute for tribal health research",
            "national institute for research in tribal health",
            "national institute of research in tribal health",  # real-data "of" variant
        ],
        "short_acronyms": ["nithr", "nirth"],
    },
    {
        "current_name": "ICMR-National Institute of Health Research, Jodhpur",
        "acronym": "NIHR",
        "match_phrases": [
            "desert medicine research centre", "desert medicine research center",
            "national institute for implementation research on non-communicable diseases",
            "national institute for implementation research on non communicable diseases",
        ],
        "short_acronyms": ["dmrc", "niirncd"],
        "nihr_city": "Jodhpur",
        "extra_locations": ["jodhpur"],
    },
    {
        "current_name": "ICMR-National Institute for Research in Bacterial Infections, Kolkata",
        "acronym": "NIRBI",
        "match_phrases": [
            "national institute for research in bacterial infections",
            "national institute of cholera and enteric diseases",
        ],
        "short_acronyms": ["nirbi", "niced"],
    },
    {
        "current_name": "ICMR-National Institute of One Health, Nagpur",
        "acronym": "NIOH (Nagpur)",
        "match_phrases": ["national institute of one health"],
        "short_acronyms": [],  # bare "nioh" handled by the special-case below
    },
    {
        "current_name": "ICMR-National Institute for Research on Blood and Immune Disorders, Mumbai",
        "acronym": "NIRBID",
        "match_phrases": [
            "national institute for research on blood and immune disorders",
            "national institute of immunohaematology", "national institute of immunohematology",
            "national institute of immunohaemaotology", "national institute of immunohaemotology",  # real-data typos
        ],
        "short_acronyms": ["nirbid", "niih"],
    },
    {
        "current_name": "ICMR-National Institute for Research on Women's Health, Mumbai",
        "acronym": "NIRWoH",
        "match_phrases": [
            "national institute for research on women's health", "national institute for research on womens health",
            "national institute for research in reproductive health", "national institute for research in reproductive and child health",
            "national institute of research in reproductive health", "national institute of research in reproductive and child health",
        ],
        "short_acronyms": ["nirwoh", "nirrch"],
    },
    {
        "current_name": "ICMR-National Institute of Cancer Prevention and Research, Noida",
        "acronym": "NICPR",
        "match_phrases": ["national institute of cancer prevention and research"],
        "short_acronyms": ["nicpr"],
    },
    {
        "current_name": "ICMR-Rajendra Memorial National Institute of Health Research, Patna",
        "acronym": "RM NIHR",
        "match_phrases": [
            "rajendra memorial national institute of health research",
            "rajendra memorial research institute of medical sciences",
        ],
        "short_acronyms": ["rmnihr", "rmrims"],
    },
    {
        "current_name": "ICMR-National Institute of Vector Control Research, Puducherry",
        "acronym": "NIVCR",
        "match_phrases": ["national institute of vector control research", "vector control research centre", "vector control research center"],
        "short_acronyms": ["nivcr", "vcrc"],
    },
    {
        "current_name": "ICMR-National Institute of Virology, Pune",
        "acronym": "NIV",
        "match_phrases": ["national institute of virology"],
        "short_acronyms": ["niv"],
    },
    {
        "current_name": "ICMR-National Institute of Translational Virology and AIDS Research, Pune",
        "acronym": "NITVAR",
        "match_phrases": [
            "national institute of translational virology and aids research",
            "national aids research institute",
        ],
        "short_acronyms": ["nitvar", "nari"],
    },
    {
        "current_name": "ICMR-Regional Medical Research Centre, Sri Vijaya Puram",
        "acronym": "RMRCSVP",
        "match_phrases": [
            "regional medical research centre, sri vijaya puram", "regional medical research centre, port blair",
            "rmrc, port blair", "rmrc port blair", "rmrc, sri vijaya puram",
        ],
        "short_acronyms": ["rmrcsvp"],
    },
]

_NIHR_INSTITUTES = [inst for inst in ICMR_INSTITUTES if inst.get("nihr_city")]

# "ICMR" is not exclusively India's Indian Council of Medical Research -
# real data surfaced "Universite de Reims Champagne-Ardenne, CNRS, ICMR,
# Reims, France", where ICMR = Institut de Chimie Moleculaire de Reims, a
# French chemistry institute with zero connection to India. Citations don't
# spell out that full French name - they just use the bare acronym next to
# French-context words - so detection has to be contextual: "icmr" appearing
# alongside these French/CNRS signals, with no Indian-context word nearby,
# is treated as this unrelated French institute rather than India's ICMR.
_FRENCH_ICMR_CONTEXT_WORDS = ["reims", "cnrs", "champagne-ardenne", "champagne ardenne"]
_INDIAN_CONTEXT_WORDS = ["india", "indian council of medical research"]


def _strip_french_icmr_false_positives(text):
    """Removes any 'icmr' mention that's contextually the French Institut
    de Chimie Moleculaire de Reims (see above) rather than India's ICMR -
    checked in a window around each occurrence so a multi-author string
    with BOTH a genuine Indian ICMR institute AND an unrelated French co-
    author affiliation doesn't get the real Indian mention wiped out too."""
    def _replace(m):
        start, end = max(0, m.start() - 60), min(len(text), m.end() + 60)
        window = text[start:end]
        if any(w in window for w in _FRENCH_ICMR_CONTEXT_WORDS) and not any(w in window for w in _INDIAN_CONTEXT_WORDS):
            return ""
        return m.group(0)
    return re.sub(r"icmr", _replace, text)


def _normalize(text):
    """Lowercase + fold '&' to 'and' so phrase matching doesn't fragment on
    real data's inconsistent use of '&' vs 'and' (e.g. 'Translational
    Virology & AIDS Research' vs '...and AIDS Research')."""
    text = str(text).lower()
    text = re.sub(r"\s*&\s*", " and ", text)
    return text


_ICMR_CCOE_LABEL = "ICMR Collaborating Centre of Excellence (external partner institution, not one of the 28 core institutes)"
_ICMR_HQ_LABEL = "ICMR Headquarters, New Delhi (not a constituent institute)"
# Per explicit instruction: a bare "ICMR" mention that can't be pinned to
# a specific institute (and isn't a CCoE mention) is now classified as
# ICMR Headquarters rather than a separate "not identified" catch-all -
# there used to be a distinct _ICMR_NOT_IDENTIFIED_LABEL for this case;
# it's been folded into _ICMR_HQ_LABEL below.


def _has_ccoe_signal(text):
    return ("collaborating centre of excellence" in text or "collaborating center of excellence" in text
            or "collaborative centre of excellence" in text or "collaborative center of excellence" in text
            or re.search(r"\bicmr-?ccoe\b", text) is not None)


def _has_hq_signal(text):
    return "headquarters" in text or "hqrs" in text or "hq," in text


def match_all_icmr_institutes(affiliation_text):
    """Returns a list of (current_name, acronym) tuples - ONE PER DISTINCT
    ICMR institute identifiable anywhere in the given affiliation string, in
    the order each institute is first matched (de-duplicated). This is the
    multi-institute-aware version: a single affiliation string can list
    co-authors from several different ICMR institutes (real multi-site
    collaborations - confirmed in at least 144/2632 rows of one real
    dataset), and all of them should be captured, not just whichever one
    happens to be checked first.

    Returns an empty list if no SPECIFIC institute is identifiable (either
    ICMR isn't mentioned at all, or it's mentioned too generically to pin
    down a institute - see match_icmr_institute for the generic-label
    fallback in that case)."""
    if not affiliation_text or (isinstance(affiliation_text, float)):
        return []
    text = _normalize(affiliation_text)
    text = _strip_french_icmr_false_positives(text)

    found = []
    found_names = set()

    def _add(inst):
        if inst["current_name"] not in found_names:
            found_names.add(inst["current_name"])
            found.append((inst["current_name"], inst["acronym"]))

    def _add_label(name, acronym=""):
        if name not in found_names:
            found_names.add(name)
            found.append((name, acronym))

    # --- Long, distinctive phrases: safe to match with or without "icmr".
    # This includes the NIHR-linked institutes' distinctive FORMER names
    # (e.g. "desert medicine research centre") - those are unambiguous on
    # their own. Only the bare "NIHR"/"national institute of health
    # research" acronym itself is 5-way ambiguous and needs the AND-logic
    # city resolution further below. ---
    for inst in ICMR_INSTITUTES:
        for phrase in inst["match_phrases"]:
            if phrase in text:
                _add(inst)
                break

    # --- NIHR is shared by 5 institutes (Bhubaneswar/Dibrugarh/Gorakhpur/
    # Jodhpur/+Patna uses "RM NIHR") - only resolvable via location. Uses
    # AND-logic (RMRC/NIHR signal present ANYWHERE + a location keyword
    # present ANYWHERE, not necessarily adjacent) rather than a strict
    # adjacent phrase - real data showed extra locality names inserted
    # between "Centre," and the city (e.g. "...Centre, Chandrasekharpur,
    # Bhubaneswar", "...Centre, N.E. Region, Dibrugarh") that broke a
    # strict substring match. ---
    has_rmrc_or_nihr_signal = (
        "regional medical research centre" in text or "regional medical research center" in text
        or "nihr" in text or "national institute of health research" in text
    )
    if has_rmrc_or_nihr_signal:
        for inst in _NIHR_INSTITUTES:
            locations = inst.get("extra_locations") or [inst["nihr_city"].lower()]
            if any(loc in text for loc in locations):
                _add(inst)

    # --- Short/generic acronyms: only trust these alongside an explicit
    # "ICMR" mention, to avoid matching unrelated organizations that happen
    # to share a 3-4 letter acronym. ---
    has_icmr = "icmr" in text or "indian council of medical research" in text
    if has_icmr:
        for inst in ICMR_INSTITUTES:
            for acr in inst.get("short_acronyms", []):
                if re.search(r"\b" + re.escape(acr) + r"\b", text):
                    _add(inst)
                    break

        # "NIOH" acronym collision: Ahmedabad (Occupational Health) vs
        # Nagpur (One Health, est. 2026). Default to Ahmedabad (the
        # long-established one) unless Nagpur/One Health context is present.
        if re.search(r"\bnioh\b", text):
            if "one health" in text or "nagpur" in text:
                nagpur = next(i for i in ICMR_INSTITUTES if i["acronym"] == "NIOH (Nagpur)")
                _add(nagpur)
            else:
                ahmedabad = next(i for i in ICMR_INSTITUTES if i["acronym"] == "NIOHR")
                _add(ahmedabad)

        # --- ICMR Headquarters and ICMR-Collaborating Centre of Excellence
        # are ADDITIVE signals, not an exclusive fallback: a multi-author
        # paper can have one co-author affiliated with a specific institute
        # AND a separate co-author literally affiliated with "ICMR
        # Headquarters" or an ICMR-CCoE partner institution (both confirmed
        # in real data - e.g. a corresponding author from "ICMR
        # Headquarters, Ansari Nagar" alongside a first author from
        # "ICMR-National Institute for Research in Reproductive and Child
        # Health, Mumbai"). Previously these were only ever produced by the
        # single-result fallback path, so mentioning both silently dropped
        # the HQ/CCoE part - now both are captured. ---
        if _has_ccoe_signal(text):
            _add_label(_ICMR_CCOE_LABEL)
        if _has_hq_signal(text):
            _add_label(_ICMR_HQ_LABEL)

    return found


def match_icmr_institute(affiliation_text):
    """Single-result convenience wrapper over match_all_icmr_institutes:
    returns (current_name, acronym) for the FIRST ICMR institute
    identifiable in the given affiliation string, or the generic ICMR-CCoE/
    Headquarters label if ICMR is mentioned but no specific institute is
    found, or ("", "") if ICMR isn't mentioned at all. Kept for callers
    that only need/expect one result; use match_all_icmr_institutes or
    resolve_all_icmr_institutes directly if a row might mention more than
    one institute."""
    all_found = match_all_icmr_institutes(affiliation_text)
    if all_found:
        return all_found[0]
    # match_all_icmr_institutes() already checks for CCoE/HQ signals (see
    # above) - reaching here means neither a specific institute nor CCoE
    # was identifiable. Per instruction: a bare/generic "ICMR" mention that
    # can't be pinned to a specific institute is treated as ICMR
    # Headquarters (rather than a separate "couldn't identify" label).
    if not affiliation_text or (isinstance(affiliation_text, float)):
        return "", ""
    text = _normalize(affiliation_text)
    text = _strip_french_icmr_false_positives(text)
    has_icmr = "icmr" in text or "indian council of medical research" in text
    if has_icmr:
        return _ICMR_HQ_LABEL, ""
    return "", ""


def resolve_all_icmr_institutes(*affiliation_texts):
    """Multi-institute-aware wrapper for callers with several candidate
    affiliation strings (e.g. combined institute list, first-author
    affiliation, corresponding-author affiliation) - returns a single
    semicolon-joined string of every DISTINCT ICMR institute identifiable
    across ALL of the given texts (de-duplicated, in first-seen order).

    If none of the texts name a specific institute, falls back to the
    first generic ICMR-CCoE/Headquarters label found (checked in the order
    the texts are given) - a bare/generic ICMR mention that can't be
    pinned to a specific institute is treated as ICMR Headquarters - or ""
    if none of them mention ICMR at all."""
    found_names = []
    seen = set()
    for text in affiliation_texts:
        for name, _acr in match_all_icmr_institutes(text):
            if name not in seen:
                seen.add(name)
                found_names.append(name)
    if found_names:
        return "; ".join(found_names)
    for text in affiliation_texts:
        name, _acr = match_icmr_institute(text)
        if name:
            return name
    return ""


# ---------------------------------------------------------------------
# Division/department extraction - a follow-up to institute matching, per
# request: "if divisions are added, can add divisions of the institute as
# well". Only extracts the well-structured, unambiguous phrasings
# ("Division of X", "Department of X", "X Division", "X Department") -
# confirmed against real data these cover the clear majority of cases that
# use this terminology at all (706/1976 real ICMR-institute affiliation
# segments in one dataset). Deliberately does NOT try to guess at more
# heterogeneous sub-unit names ("Animal Facility", "Field Unit Guwahati",
# "Clinical Research Laboratory") - those are too varied to extract
# reliably without risking a wrong label, so they're left blank rather
# than guessed, consistent with this module's "blank means couldn't tell,
# never means confirmed absent" convention throughout.
# ---------------------------------------------------------------------
_DIVISION_PATTERNS_PREFIX = [
    re.compile(r"\bdivision\s+of\s+([^,;]+)", re.I),
    re.compile(r"\bdepartment\s+of\s+([^,;]+)", re.I),
    re.compile(r"\bdept\.?\s+of\s+([^,;]+)", re.I),
]
_DIVISION_PATTERNS_SUFFIX = [
    re.compile(r"([A-Z][A-Za-z &]*?)\s+Division\b"),
    re.compile(r"([A-Z][A-Za-z &]*?)\s+Department\b"),
]


def extract_division(affiliation_segment):
    """Best-effort extraction of a division/department name from ONE
    affiliation segment (e.g. a single author's own affiliation string,
    not a semicolon-joined blob of several authors - this only ever
    returns the FIRST match found in whatever text it's given, so running
    it on a multi-author blob risks picking up the wrong author's division
    entirely). Returns "" if no Division/Department phrasing is present."""
    if not affiliation_segment or isinstance(affiliation_segment, float):
        return ""
    text = str(affiliation_segment)
    for pat in _DIVISION_PATTERNS_PREFIX:
        m = pat.search(text)
        if m:
            return m.group(1).strip().rstrip(".")
    for pat in _DIVISION_PATTERNS_SUFFIX:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return ""


def match_institutes_with_divisions(*affiliation_segments):
    """Like resolve_all_icmr_institutes, but ALSO tries to attach a
    division/department name to each institute found - extracted from the
    SAME segment where that institute was identified, so a paper with
    co-authors from different institutes/divisions doesn't cross-attribute
    one author's division to a different author's institute.

    Each argument should be ONE segment of affiliation text (e.g. a single
    author's own affiliation string) - NOT a semicolon-joined blob of
    several authors' affiliations, since extract_division only looks at
    the whole segment given and returns its first match.

    Division attribution is skipped (left "") for any segment that matches
    2+ distinct institutes/labels at once, since there's then no reliable
    way to tell which institute a division phrase in that segment belongs
    to - confirmed rare in real data (23/1976 segments), so this costs
    very little coverage.

    Returns a list of (current_name, division) tuples, one per distinct
    institute/label identified (first-seen order across all segments);
    division is "" when nothing was found for it.

    If none of the segments name a specific institute (or CCoE/HQ), falls
    back to the same generic ICMR Headquarters label resolve_all_icmr_institutes
    uses for a bare/generic ICMR mention - checked across the same
    segments - so this function never loses information compared to that
    one just because it also does division extraction."""
    order = []
    divisions = {}
    for seg in affiliation_segments:
        hits = match_all_icmr_institutes(seg)
        if not hits:
            continue
        div = extract_division(seg) if len(hits) == 1 else ""
        for name, _acr in hits:
            if name not in divisions:
                divisions[name] = div
                order.append(name)
            elif not divisions[name] and div:
                divisions[name] = div
    if order:
        return [(name, divisions[name]) for name in order]
    for seg in affiliation_segments:
        name, _acr = match_icmr_institute(seg)
        if name:
            return [(name, "")]
    return []
