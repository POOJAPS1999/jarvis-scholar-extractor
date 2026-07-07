"""
http_utils.py
=============
Shared HTTP session + retry/backoff + per-source rate limiting.

FIX for the 40-min/100-record slowdown: previously every call (regardless
of which API it hit) shared one blanket sleep, and the three sources were
queried sequentially per record. Now each source has its OWN rate limiter
(so it's only as conservative as that specific API requires), and
matcher.py fires all three sources concurrently per record - the per-record
wait time becomes roughly "slowest of the three" instead of "sum of all
three".
"""

import sys
import time
import threading
import requests

from . import config

_session = None


def get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({
            "User-Agent": f"bibliometric-extractor (mailto:{config.CONTACT_EMAIL})"
        })
    return _session


class RateLimiter:
    """Thread-safe minimum-interval limiter, one instance per API source."""

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_call = time.monotonic()


NCBI_LIMITER = RateLimiter(config.NCBI_MIN_INTERVAL)
OPENALEX_LIMITER = RateLimiter(config.OPENALEX_MIN_INTERVAL)
CROSSREF_LIMITER = RateLimiter(config.CROSSREF_MIN_INTERVAL)


class FetchError(Exception):
    """Raised when a request could NOT be completed after all retries
    (timeout, connection error, or a persistent 429/5xx).

    This is deliberately distinct from a clean 404, which means "this API
    genuinely has no record for this DOI/PMID" and is a real, final answer.
    A FetchError means "we don't know" - the record might well exist, we
    just couldn't reach the API right now. Callers (matcher.py) treat these
    very differently: a 404 is reported as "not found in X", a FetchError
    is reported as "fetch failed, will retry" and the record is NOT
    checkpointed as done, so a later run tries again instead of silently
    baking in missing data (e.g. missing affiliations) forever.
    """
    pass


def http_get(url, params=None, expect="json", limiter=None):
    """GET with retries. Returns parsed json / text on success, None on a
    clean 404. Raises FetchError if every retry failed for another reason."""
    if limiter is not None:
        limiter.wait()
    session = get_session()
    last_err = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}"
                time.sleep(1.5 * attempt)
                continue
            r.raise_for_status()
            if expect == "json":
                return r.json()
            return r.text
        except Exception as e:  # noqa
            last_err = e
            time.sleep(1.0 * attempt)
    sys.stderr.write(f"   [http] giving up on {url} -> {last_err}\n")
    raise FetchError(f"{url} :: {last_err}")
