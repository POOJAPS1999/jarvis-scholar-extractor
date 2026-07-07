"""
text_utils.py
=============
Small text/matching helpers shared by every source module.
"""

import re
import html
import unicodedata

# ---------------------------------------------------------------------
# Fuzzy-matching backend: rapidfuzz if available, else difflib.
#
# GUARDED against a confirmed false-positive failure mode: token_set_ratio
# (and to a lesser extent difflib's ratio) scores close to 100 whenever the
# SHORTER string's tokens are essentially a full subset of the longer
# string's tokens - even when the shorter string is short/generic and the
# longer one is a completely different, unrelated title that merely shares
# that vocabulary. Confirmed real example from a live run: the 2-word
# candidate title "Withania-somnifera" (a drug-bulletin blurb title from an
# unrelated "Reactions Weekly" entry) scored 100.0 against the real,
# unrelated 14-word input title "Leaf miRNAs of Withania somnifera
# Negatively Regulate the Aging-Associated Genes in C. elegans" - both
# contain "withania" and "somnifera", nothing else in common - and got
# Auto-accepted at the HIGHEST confidence tier with no manual-review flag.
#
# Fix: when the two strings differ a lot in word count (below a 0.5
# ratio - i.e. one has less than half the words of the other), scale the
# raw score down proportionally to how extreme that mismatch is. A minor
# subtitle/clause difference (e.g. one source drops a colon-separated
# subtitle) keeps a ratio well above 0.5 and is completely unaffected;
# only genuinely lopsided length mismatches - the "short generic candidate
# coincidentally contained in a much longer title" pattern - get
# discounted, which is exactly the failure mode this fixes.
# ---------------------------------------------------------------------
def _length_guard_multiplier(a, b):
    wa, wb = a.split(), b.split()
    if not wa or not wb:
        return 1.0
    ratio = min(len(wa), len(wb)) / max(len(wa), len(wb))
    if ratio >= 0.5:
        return 1.0
    return ratio / 0.5


try:
    from rapidfuzz import fuzz as _rf_fuzz

    def fuzzy_score(a, b):
        raw = float(_rf_fuzz.token_set_ratio(a, b))
        return raw * _length_guard_multiplier(a, b)
    FUZZ_BACKEND = "rapidfuzz"
except Exception:
    import difflib

    def fuzzy_score(a, b):
        raw = difflib.SequenceMatcher(None, a, b).ratio() * 100.0
        return raw * _length_guard_multiplier(a, b)
    FUZZ_BACKEND = "difflib"


# ---------------------------------------------------------------------
# Country code -> name
# ---------------------------------------------------------------------
try:
    import pycountry

    def country_name(code):
        if not code:
            return ""
        try:
            c = pycountry.countries.get(alpha_2=code.upper())
            return c.name if c else code.upper()
        except Exception:
            return code.upper()
except Exception:
    _CC = {
        "US": "United States", "GB": "United Kingdom", "IN": "India",
        "CN": "China", "JP": "Japan", "DE": "Germany", "FR": "France",
        "IT": "Italy", "ES": "Spain", "CA": "Canada", "AU": "Australia",
        "BR": "Brazil", "RU": "Russia", "KR": "South Korea", "NL": "Netherlands",
        "CH": "Switzerland", "SE": "Sweden", "BE": "Belgium", "AT": "Austria",
        "DK": "Denmark", "NO": "Norway", "FI": "Finland", "IE": "Ireland",
        "PT": "Portugal", "GR": "Greece", "PL": "Poland", "ZA": "South Africa",
        "MX": "Mexico", "AR": "Argentina", "EG": "Egypt", "SA": "Saudi Arabia",
        "AE": "United Arab Emirates", "IL": "Israel", "TR": "Turkey",
        "SG": "Singapore", "MY": "Malaysia", "TH": "Thailand", "ID": "Indonesia",
        "PH": "Philippines", "VN": "Vietnam", "PK": "Pakistan", "BD": "Bangladesh",
        "LK": "Sri Lanka", "NP": "Nepal", "NZ": "New Zealand", "TW": "Taiwan",
        "HK": "Hong Kong", "IR": "Iran", "NG": "Nigeria", "KE": "Kenya",
        "CL": "Chile", "CO": "Colombia", "CZ": "Czechia", "HU": "Hungary",
        "RO": "Romania", "UA": "Ukraine", "QA": "Qatar", "KW": "Kuwait",
        "OM": "Oman", "JO": "Jordan", "LB": "Lebanon", "ET": "Ethiopia",
    }

    def country_name(code):
        if not code:
            return ""
        return _CC.get(code.upper(), code.upper())


# Unicode dash-like characters that visually read as a word separator but
# would otherwise be silently DROPPED (not converted to a space/hyphen) by
# the ascii-encode-ignore step below, since encode("ascii","ignore") just
# deletes any character it can't represent. Concretely found in this batch:
# "Aging-Associated" (plain ASCII hyphen) and "Aging‑Associated" (U+2011
# non-breaking hyphen - common when a title is copy-pasted from a journal
# site or PDF) cleaned to two DIFFERENT strings ("aging associated" vs
# "agingassociated"), silently lowering the fuzzy score between two titles
# that are otherwise identical - enough, in the worst case, to push a
# genuinely correct match below FUZZY_REVIEW_MIN or FUZZY_AUTO_ACCEPT.
_DASH_LIKE = "‐‑‒–—―−"
_DASH_TRANS = str.maketrans({c: "-" for c in _DASH_LIKE})


def clean_for_match(s):
    """Normalise a title for fuzzy comparison."""
    if not s:
        return ""
    s = html.unescape(str(s))
    s = s.translate(_DASH_TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_doi(doi):
    """
    Strip URL/scheme prefixes and whitespace so every DOI lookup uses a bare
    DOI (e.g. '10.1234/xyz'), regardless of whether the input was
    'https://doi.org/10.1234/xyz', 'doi:10.1234/xyz', or already bare.

    FIX: the original script assumed input DOIs were always bare, which
    silently broke OpenAlex lookups whenever a DOI came in with a URL
    prefix (a realistic case given your Crossref-based resolution pipeline).
    """
    if not doi:
        return ""
    d = str(doi).strip()
    if d.lower() == "nan":
        return ""
    d = re.sub(r"(?i)^https?://(dx\.)?doi\.org/", "", d)
    d = re.sub(r"(?i)^doi:\s*", "", d)
    d = d.strip().strip("/")
    return d.lower()


def uniq_keep_order(items):
    seen, out = set(), []
    for x in items:
        if x is None:
            continue
        x = str(x).strip()
        if not x:
            continue
        key = x.lower()
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def join_semicolon(items):
    return "; ".join(uniq_keep_order(items))


def is_icmr(text):
    """True if an affiliation string mentions ICMR."""
    if not text:
        return False
    t = str(text).lower()
    return ("icmr" in t) or ("indian council of medical research" in t)


# ---------------------------------------------------------------------
# Email extraction (heuristic - PubMed/OpenAlex affiliation strings
# sometimes embed a corresponding-author email, e.g. "Electronic address:
# name@inst.edu"). Not guaranteed to be present or correctly attributed.
# ---------------------------------------------------------------------
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_email(text):
    if not text:
        return ""
    m = _EMAIL_RE.search(str(text))
    if not m:
        return ""
    # Strip trailing sentence punctuation the regex can pick up
    # (e.g. "...jane@univ.edu." at the end of an affiliation sentence).
    return m.group(0).rstrip(".,;:)")


# ---------------------------------------------------------------------
# Synthetic Scopus-style identifiers.
#
# IMPORTANT: these are NOT real Scopus identifiers. Scopus EIDs/Author IDs
# are proprietary and only available via a paid Scopus API subscription.
# These synthetic values exist purely so Biblioshiny's Scopus-CSV importer
# (which drops rows with a blank EID) has a non-empty, unique, deterministic
# ID to key off. Never report these as genuine Scopus data in a manuscript -
# label them clearly as synthetic if they end up in any methods section.
# ---------------------------------------------------------------------
import hashlib


def _hash_to_digits(seed, n_digits=11):
    digest = hashlib.md5(str(seed).encode("utf-8")).hexdigest()
    numeric = str(int(digest[:14], 16))
    return numeric[:n_digits].rjust(n_digits, "0")


def generate_synthetic_eid(seed):
    """Deterministic '2-s2.0-XXXXXXXXXXX'-shaped ID. Same seed -> same EID,
    so reruns/checkpoints stay stable."""
    seed = str(seed or "").strip()
    if not seed:
        return ""
    return f"2-s2.0-{_hash_to_digits(seed, 11)}"


def generate_synthetic_author_id(name):
    """Deterministic ~11-digit numeric ID per normalised author name, shaped
    like a real Scopus Author ID. Two differently-spelled variants of the
    same person (e.g. 'Sharma P' vs 'Sharma, Pooja') will NOT get the same
    ID - this is a real limitation, same one Scopus itself has without
    author disambiguation."""
    seed = clean_for_match(name)
    if not seed:
        return ""
    return _hash_to_digits(seed, 11)
