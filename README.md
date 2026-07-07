# Bibliometric Extractor — v3

## What changed since your test run

### Speed
Previously the 3 sources (OpenAlex, PubMed, Crossref) were queried one
after another for every record, each with its own sleep — that's why 100
records took ~40 minutes. Now:
- The 3 sources are queried **concurrently** per record (3 threads), so
  per-record time is roughly "however long the slowest source takes"
  instead of "the sum of all three."
- Each source has its **own** rate limiter tuned to what that API actually
  requires (NCBI ~0.12–0.34s, OpenAlex ~0.1s, Crossref ~0.5s) instead of
  one blanket sleep applied everywhere.
- Default request timeout lowered from 30s → 20s, so a single slow/dead
  source can't burn 90s of retries on one record.

**Please time a fresh 100-record run and tell me the new number** — actual
speedup depends on your network and how often each API responds slowly, so
I'd rather tune against your real numbers than guess.

### Columns removed (moved to opt-in groups — see below)
`Country (All Authors)`, `Country Count` (old), `INSTITUTE`, `DIVISION`,
`Institution Type`, `Collaborators`, `Collaboration Type`, `First/Corresponding/Any
Author from ICMR`, `Intramural/Extramural`, `Impact Factor`, `5-Year IF`,
`CiteScore`, `SJR`, `SNIP`, `WoS/Scopus Indexing`, `WoS/Scopus Quartile`,
`Country` (journal), `Subject Category`, `Top 10% Paper`, `Rank`,
`HEALTH IMPACT`, `Domains`, `Micro Domains`, `4Ds Framework`, `Comments`,
`Countries_All`, `First_Author_Country`.

I kept `Comments` available as the opt-in `qc_notes` group rather than
deleting it outright — it holds the match-diagnostic notes (which source
matched, at what score), which is useful for auditing later even though you
don't need it by default. Say the word if you'd rather it's gone entirely.

### Columns added
`EID`, `EID Type`, `Author(s) ID (synthetic)`, `Corresponding Author`,
`Corresponding Author Email ID`, `Corresponding Author Country`,
`All Country`, `Country Count` (single clean pair, replacing the two
overlapping pairs the old schema had), `Grants`, `COI`, `Acknowledgment`.

**Honesty check on data availability:**
- `Corresponding Author` — from OpenAlex's explicit flag, or a PubMed
  heuristic ("Electronic address:" in an author's affiliation — a common
  convention, not a guarantee).
- `Corresponding Author Email ID` — regex-extracted from affiliation text
  when present. Often blank; not every source embeds it.
- `Grants` — from PubMed's `GrantList` + OpenAlex's `grants` field +
  Crossref's `funder` field, merged.
- `COI` — only PubMed exposes a conflict-of-interest statement field, and
  only for more recent articles. Will be blank often.
- `Acknowledgment` — **left blank on purpose.** None of the three free
  APIs expose acknowledgment text in their metadata (it lives in the full
  text, not the record). Getting this would need a separate full-text
  mining step against PMC's open-access subset — doable, but a distinct
  pipeline stage, not a metadata field. Flagging rather than faking it.

### EID / Scopus ID — what's actually possible without the Scopus API
Real Scopus EIDs and Author IDs are proprietary — there is no free/legal
way to generate genuine ones. What this version does instead:
- `EID`: a deterministic, synthetic `2-s2.0-XXXXXXXXXXX`-shaped ID derived
  from the DOI (or PMID/title as fallback). Same input always produces the
  same EID, so it survives checkpoint reruns. This exists purely so
  **Biblioshiny's Scopus-CSV importer stops dropping rows with a blank
  EID** — it is not a real Scopus identifier.
- `Author(s) ID (synthetic)`: same idea, one synthetic ~11-digit ID per
  normalised author name, positionally matched to the `Authors` column —
  gives bibliometrix something to key co-authorship networks on. Known
  limitation: name variants ("Sharma P" vs "Sharma, Pooja") get different
  IDs, same as real Scopus has without disambiguation.
- **`EID Type` column flags every EID as synthetic.** Please keep that
  column (or an equivalent note) in any methods section — reviewers should
  never mistake these for genuine Scopus identifiers.

### Column groups (Scopus-style defaults + checklist)
`.env` now has `BIBLIO_OPTIONAL_COLUMN_GROUPS` — comma-separated, empty by
default (lean/core output only). Available groups:

| Group | Columns |
|---|---|
| `icmr_flags` | First/Corresponding/Any Author from ICMR, Intramural/Extramural |
| `institution_details` | INSTITUTE, DIVISION, Institution Type, Collaboration Type, Collaborators |
| `journal_metrics` | Impact Factor, 5-Year IF, CiteScore, SJR, SNIP, WoS/Scopus Indexing & Quartile, Top 10%, Rank (all blank without a paid data source — placeholders to fill manually) |
| `research_classification` | HEALTH IMPACT, Domains, Micro Domains, 4Ds Framework |
| `extra_bibliometric` | Country (journal), Subject Category |
| `qc_notes` | Comments |

Example for an ICMR-style run: `BIBLIO_OPTIONAL_COLUMN_GROUPS=icmr_flags,institution_details`

## Setup (unchanged)

```bash
pip3 install -r requirements.txt
cp .env.example .env    # fill in your (new, regenerated) NCBI key + real email
python3 run_extractor.py
```

## File map

```
run_extractor.py
requirements.txt
.env.example
bibliometric_pipeline/
  config.py            <- settings, rate-limit intervals, column groups
  text_utils.py         <- fuzzy matching, DOI normalization, EID/email helpers
  http_utils.py          <- HTTP session + per-source RateLimiter
  matcher.py              <- core matching + merge + column schema (the heart of it)
  pipeline.py              <- checkpointed run loop
  sources/
    openalex.py
    pubmed.py
    crossref.py
```
