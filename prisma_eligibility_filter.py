"""
prisma_eligibility_filter.py
=============================
Standalone, additive script: applies your study's actual PRISMA eligibility
criteria to a finished pipeline output and produces a real PRISMA-style
flow (Identification -> Screening with exclusion reasons -> Included),
not just the matching-funnel summary in pipeline_qa_report.py.

YOUR CRITERIA (as specified):
  INCLUDED : Original articles, Systematic reviews, Meta-analyses,
             Case reports/case series, Conference proceedings/abstracts -
             published April 2025 or later.
  EXCLUDED : Preprints, Erratums/corrections, Book chapters,
             Correspondence, Letters to the editor, Opinion pieces/
             Editorials/Comments, Perspectives, Narrative reviews
             (i.e. a "review" that does NOT self-describe as systematic
             review/meta-analysis) - and anything published before
             April 2025.

REVIEW DISAMBIGUATION (per your decision): a record typed as a review is
INCLUDED only if its title OR abstract explicitly mentions "systematic
review" or "meta-analysis" (case-insensitive) - otherwise it's treated as
a narrative review and excluded.

IMPORTANT - WHY THIS RE-FETCHES PUBMED DATA:
PubMed is the only one of the 3 sources that tags "Systematic Review" and
"Meta-Analysis" as their own distinct types (OpenAlex/Crossref just say
"review" or "article" with no finer distinction). But the main pipeline's
"Article Type" column silently keeps ONLY OpenAlex's coarse type whenever
OpenAlex has one at all (which is most records) - PubMed's richer,
multi-tag pub_types list gets dropped in that case. So for every row with
a PMID, this script RE-FETCHES PubMed's full pub_types list fresh (one
extra network call per PMID, reusing the main pipeline's own rate-limited
pubmed_by_pmid()) to recover that lost signal before classifying. This
needs a live internet connection - run it on your machine, not in an
offline/sandboxed environment. Use --no-refresh-pubmed to skip this (faster,
but relies only on OpenAlex/Crossref's coarser type + title/abstract text,
so more rows will land in "needs manual review").

DATE CUTOFF: uses Publication Date when a month is available. A record
with ONLY a bare Year that equals 2025 (can't tell if Jan-Mar, excluded, or
Apr-Dec, included) is FLAGGED FOR MANUAL REVIEW rather than guessed, per
your decision.

Never modifies the input - writes a new augmented file (adds classification
columns) plus a separate PRISMA flow-count summary workbook.

Usage:
  python3 prisma_eligibility_filter.py --input bibliometric_output_full.xlsx \
      --output bibliometric_output_full_prisma.xlsx \
      --summary prisma_flow_summary.xlsx
  (add --no-refresh-pubmed to skip the live PubMed re-fetch step)
"""

import argparse
import re
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, ".")
try:
    from bibliometric_pipeline.sources.pubmed import pubmed_by_pmid
    from bibliometric_pipeline.http_utils import FetchError
except ImportError:
    pubmed_by_pmid = None
    FetchError = Exception

CUTOFF_DATE = date(2025, 4, 1)

# Order matters: checked top-to-bottom, first match wins for EXCLUDE reasons.
EXCLUDE_TYPE_PATTERNS = [
    ("Peer-review report (not a literature review)", [r"peer[\s-]?review\b"]),
    ("Preprint", [r"preprint", r"posted[\s-]?content"]),
    ("Erratum/Correction", [r"erratum", r"correction", r"corrigendum", r"retraction"]),
    ("Book chapter", [r"book[\s-]?chapter", r"\bchapter\b"]),
    ("Correspondence", [r"correspondence"]),
    ("Letter", [r"\bletter\b"]),
    ("Opinion/Editorial/Comment", [r"\beditorial\b", r"\bcomment\b", r"\bopinion\b"]),
    ("Perspective", [r"\bperspective\b"]),
]

# Positive-evidence patterns for the systematic-review/meta-analysis carve-out
SYSTEMATIC_META_PATTERNS = [
    r"systematic review", r"systematic literature review", r"meta[\s-]?analysis",
]

INCLUDE_TYPE_PATTERNS = [
    ("Case report/series", [r"case report", r"case series"]),
    ("Conference proceedings/abstract", [r"proceedings", r"conference (paper|abstract)"]),
]


def _any_match(text, patterns):
    return any(re.search(p, text, re.I) for p in patterns)


def classify_type(article_type, pubmed_pub_types, title, abstract):
    """Returns (bucket, reason) where bucket in {'Include', 'Exclude', 'Manual Review'}."""
    parts = [str(x).strip() for x in (article_type, pubmed_pub_types) if str(x or "").strip()]
    if not parts:
        return "Manual Review", "No document-type information available from any source"
    type_blob = " | ".join(parts).lower()
    title = str(title or "")
    abstract = str(abstract or "")

    for reason, patterns in EXCLUDE_TYPE_PATTERNS:
        if _any_match(type_blob, patterns):
            return "Exclude", reason

    for reason, patterns in INCLUDE_TYPE_PATTERNS:
        if _any_match(type_blob, patterns):
            return "Include", reason

    if "review" in type_blob:
        # Positive evidence check: PubMed's own pub_types tag, or an
        # explicit mention in the title/abstract text.
        if _any_match(type_blob, SYSTEMATIC_META_PATTERNS):
            return "Include", "Systematic review / meta-analysis (confirmed via source type tag)"
        if _any_match(title, SYSTEMATIC_META_PATTERNS) or _any_match(abstract, SYSTEMATIC_META_PATTERNS):
            return "Include", "Systematic review / meta-analysis (confirmed via title/abstract text)"
        return "Exclude", "Narrative review (no systematic review/meta-analysis evidence in type, title, or abstract)"

    # Default: no exclude/special-include pattern matched, not tagged as a
    # review at all -> treat as an original article.
    return "Include", "Original article (default - no exclusion pattern matched)"


def _parse_pub_date(pub_date_str, year):
    """Try to get an actual (year, month) pair. Returns (year, month) or
    (year, None) if only the year is known, or (None, None) if nothing
    usable is available."""
    s = str(pub_date_str or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})", s)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^(\d{4})$", s)
    if m:
        return int(m.group(1)), None
    try:
        y = int(year)
        if 1900 < y < 2100:
            return y, None
    except (TypeError, ValueError):
        pass
    return None, None


def classify_date(pub_date_str, year):
    """Returns (bucket, reason)."""
    y, mo = _parse_pub_date(pub_date_str, year)
    if y is None:
        return "Manual Review", "No usable publication date available"
    if mo is not None:
        rec_date = date(y, mo, 1)
        if rec_date >= CUTOFF_DATE:
            return "Include", f"Published {y}-{mo:02d}, on/after April 2025 cutoff"
        return "Exclude", f"Published {y}-{mo:02d}, before April 2025 cutoff"
    # Year only, no month
    if y < 2025:
        return "Exclude", f"Published {y} (before 2025) - clearly before cutoff"
    if y > 2025:
        return "Include", f"Published {y} (after 2025) - clearly after cutoff"
    return "Manual Review", "Published 2025 but month unknown - cannot determine April cutoff, check manually"


def _refresh_pubmed_type(pmid):
    if not pmid or pubmed_by_pmid is None:
        return ""
    try:
        pmid_str = str(int(float(pmid))) if str(pmid).strip() else ""
    except (TypeError, ValueError):
        pmid_str = str(pmid).strip()
    if not pmid_str or pmid_str.lower() == "nan":
        return ""
    try:
        rec = pubmed_by_pmid(pmid_str)
    except FetchError:
        return "FETCH_ERROR"
    if not rec:
        return ""
    return "; ".join(rec.get("pub_types", []) or [])


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to the pipeline's output/checkpoint (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the augmented .xlsx (adds classification columns)")
    ap.add_argument("--summary", required=True, help="Path to write the PRISMA flow-count summary .xlsx")
    ap.add_argument("--no-refresh-pubmed", action="store_true",
                    help="Skip re-fetching PubMed pub_types (faster, offline-safe, but weaker review classification)")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    do_refresh = not args.no_refresh_pubmed and pubmed_by_pmid is not None
    if args.no_refresh_pubmed:
        print("Skipping PubMed pub_types refresh (--no-refresh-pubmed) - review classification relies only on "
              "OpenAlex/Crossref type + title/abstract text.")
    elif pubmed_by_pmid is None:
        print("WARNING: could not import bibliometric_pipeline - run this script from the project root. "
              "Proceeding WITHOUT the PubMed refresh step.")

    type_bucket, type_reason, date_bucket, date_reason, final_status, final_reason = [], [], [], [], [], []
    pubmed_refresh_col = []
    n_refreshed = 0

    for i, row in df.iterrows():
        pmid = row.get("PMID", "")
        refreshed = ""
        if do_refresh:
            refreshed = _refresh_pubmed_type(pmid)
            if refreshed and refreshed != "FETCH_ERROR":
                n_refreshed += 1
            if (i + 1) % 100 == 0:
                print(f"  ...PubMed refresh: {i + 1}/{len(df)} rows checked")
        pubmed_refresh_col.append(refreshed)

        tb, tr = classify_type(row.get("Article Type", ""), refreshed, row.get("TITLE", ""), row.get("Abstract", ""))
        db, dr = classify_date(row.get("Publication Date", ""), row.get("YEAR", ""))

        # Respect existing dedup flag if present - a secondary duplicate is
        # excluded regardless of type/date classification.
        dedup_status = str(row.get("Dedup Status", "") or "")
        if dedup_status.startswith("Duplicate"):
            fs, fr = "Excluded", f"Duplicate record ({dedup_status})"
        elif tb == "Exclude":
            fs, fr = "Excluded", f"Document type: {tr}"
        elif db == "Exclude":
            fs, fr = "Excluded", f"Publication date: {dr}"
        elif tb == "Manual Review" or db == "Manual Review":
            fs = "Needs Manual Review"
            fr = "; ".join(x for x in [tr if tb == "Manual Review" else "", dr if db == "Manual Review" else ""] if x)
        else:
            fs, fr = "Included", f"{tr}; {dr}"

        type_bucket.append(tb); type_reason.append(tr)
        date_bucket.append(db); date_reason.append(dr)
        final_status.append(fs); final_reason.append(fr)

    df["PubMed pub_types (refreshed)"] = pubmed_refresh_col
    df["PRISMA Type Classification"] = type_bucket
    df["PRISMA Type Reason"] = type_reason
    df["PRISMA Date Classification"] = date_bucket
    df["PRISMA Date Reason"] = date_reason
    df["PRISMA Final Status"] = final_status
    df["PRISMA Final Reason"] = final_reason

    df.to_excel(args.output, index=False)
    print(f"\nWrote {len(df)} rows to {args.output}")
    if do_refresh:
        print(f"PubMed pub_types successfully refreshed for {n_refreshed} row(s) with a PMID")

    # ---- PRISMA flow summary ----
    total = len(df)
    n_included = int((df["PRISMA Final Status"] == "Included").sum())
    n_excluded = int((df["PRISMA Final Status"] == "Excluded").sum())
    n_manual = int((df["PRISMA Final Status"] == "Needs Manual Review").sum())

    exclude_reason_counts = (df[df["PRISMA Final Status"] == "Excluded"]["PRISMA Final Reason"]
                              .apply(lambda r: r.split(":")[0] if ":" in r else r)
                              .value_counts())
    manual_reason_counts = (df[df["PRISMA Final Status"] == "Needs Manual Review"]["PRISMA Final Reason"]
                              .value_counts())

    flow_rows = [
        ("Records identified (total rows in pipeline output)", total, ""),
        ("Records excluded", n_excluded, ""),
    ]
    for reason, n in exclude_reason_counts.items():
        flow_rows.append((f"  - {reason}", int(n), ""))
    flow_rows.append(("Records needing manual review (not auto-classified)", n_manual, ""))
    for reason, n in manual_reason_counts.items():
        flow_rows.append((f"  - {reason}", int(n), ""))
    flow_rows.append(("Records INCLUDED (final eligible set)", n_included, ""))

    flow_df = pd.DataFrame(flow_rows, columns=["PRISMA stage", "Count", ""])
    manual_review_rows = df[df["PRISMA Final Status"] == "Needs Manual Review"][
        [c for c in ["Sno.", "Clean Title", "TITLE", "Article Type", "Publication Date", "YEAR",
                     "PRISMA Final Reason"] if c in df.columns]]

    with pd.ExcelWriter(args.summary, engine="openpyxl") as writer:
        flow_df.to_excel(writer, sheet_name="PRISMA Flow", index=False)
        manual_review_rows.to_excel(writer, sheet_name="Needs Manual Review", index=False)

    print(f"Wrote PRISMA flow summary to {args.summary}\n")
    print(flow_df.to_string(index=False))


if __name__ == "__main__":
    main()
