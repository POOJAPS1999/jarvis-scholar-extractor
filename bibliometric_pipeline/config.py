"""
config.py
=========
All settings loaded from environment variables / .env.
"""

import os
import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(name, default=None):
    return os.environ.get(name, default)


INPUT_FILE = os.path.expanduser(_env("BIBLIO_INPUT_FILE", "~/Desktop/publications.xlsx"))
OUTPUT_FILE = os.path.expanduser(_env("BIBLIO_OUTPUT_FILE", "~/Desktop/bibliometric_output.xlsx"))
CHECKPOINT_FILE = os.path.expanduser(_env("BIBLIO_CHECKPOINT_FILE", "~/Desktop/bibliometric_checkpoint.csv"))

COL_SNO = "Sno"
COL_TITLE = "Clean Title"
COL_DOI = "DOI"

CONTACT_EMAIL = _env("BIBLIO_CONTACT_EMAIL")
NCBI_API_KEY = _env("NCBI_API_KEY", "")

# OpenAlex now runs on a daily usage budget: $0.10/day anonymous, $1/day
# (10x more) with a free key. Single-entity lookups (i.e. DOI-based lookups
# - what this pipeline uses whenever a DOI is present) are UNLIMITED even
# without a key, but "Search" calls (the title-fallback path, used for
# every record with no DOI) are budget-limited and this is what runs out
# fast on title-heavy batches. Get a free key at openalex.org/settings/api
# (needs a free account) and put it here to get the 10x budget.
OPENALEX_API_KEY = _env("OPENALEX_API_KEY", "")

if not CONTACT_EMAIL:
    raise RuntimeError(
        "BIBLIO_CONTACT_EMAIL is not set.\n"
        "Copy .env.example to .env, fill in a real contact email, and try again."
    )

CHECKPOINT_EVERY = int(_env("BIBLIO_CHECKPOINT_EVERY", "50"))

FUZZY_AUTO_ACCEPT = float(_env("BIBLIO_FUZZY_AUTO_ACCEPT", "85"))
FUZZY_REVIEW_MIN = float(_env("BIBLIO_FUZZY_REVIEW_MIN", "75"))

TITLE_CANDIDATES = int(_env("BIBLIO_TITLE_CANDIDATES", "5"))

# Lowered from 30s -> 20s default: on a source that's slow/unresponsive,
# a 30s timeout x 3 retries could burn 90s on ONE source for ONE record.
REQUEST_TIMEOUT = int(_env("BIBLIO_REQUEST_TIMEOUT", "20"))
MAX_RETRIES = int(_env("BIBLIO_MAX_RETRIES", "3"))

# Per-source minimum interval between requests (seconds). Each source now
# has its OWN limiter (rather than one blanket sleep shared by everything),
# and the three sources are queried concurrently per record - see matcher.py.
NCBI_MIN_INTERVAL = 0.34 if not NCBI_API_KEY else 0.12
OPENALEX_MIN_INTERVAL = float(_env("BIBLIO_OPENALEX_MIN_INTERVAL", "0.1"))
CROSSREF_MIN_INTERVAL = float(_env("BIBLIO_CROSSREF_MIN_INTERVAL", "0.5"))

# Kept for backward compatibility with anything importing SLEEP_BETWEEN
SLEEP_BETWEEN = NCBI_MIN_INTERVAL

CURRENT_YEAR = datetime.date.today().year

# If a source request fails after all retries (timeout/rate-limit/5xx - NOT
# a clean 404), the record is no longer silently checkpointed as "done" with
# whatever partial data (e.g. missing affiliations) happened to come back.
# It's flagged and retried automatically on the next run, up to this many
# times, after which it's left as-is and flagged for manual review instead
# of retrying forever (e.g. a permanently broken DOI/API combination).
MAX_FETCH_RETRIES = int(_env("BIBLIO_MAX_FETCH_RETRIES", "3"))

# Acknowledgment text is NOT in Crossref/OpenAlex/PubMed abstract-level
# metadata - it only exists in full text. This is OFF by default because it
# adds one extra sequential NCBI call per record (only for records with a
# PMCID) and even then only succeeds for PMC's open-access full-text
# subset - most records will still come back empty. Turn on only if you
# want best-effort acknowledgment text and can accept the slower run.
FETCH_ACKNOWLEDGMENT = _env("BIBLIO_FETCH_ACKNOWLEDGMENT", "false").strip().lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------
# Output column groups - "core" columns always appear; anything else is
# opt-in via BIBLIO_OPTIONAL_COLUMN_GROUPS (comma-separated group names)
# so a lean run (e.g. your neuroblastoma review) and an institute-style run
# (e.g. ICMR, which wants ICMR flags) can use the same pipeline.
# Available groups: icmr_flags, icmr_institute, institution_details,
#                    journal_metrics, research_classification,
#                    extra_bibliometric, qc_notes
# "icmr_institute" adds "ICMR Institute (Current Name)" - which of ICMR's
# 28 constituent institutes an ICMR-affiliated record belongs to, tagged
# with the institute's current official name even if the paper's own
# affiliation text used an old/former name - see icmr_institutes.py.
# ---------------------------------------------------------------------
OPTIONAL_COLUMN_GROUPS = _env("BIBLIO_OPTIONAL_COLUMN_GROUPS", "")
