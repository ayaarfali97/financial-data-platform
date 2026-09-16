"""Load earnings-call transcripts from the public jlh-ibm/earnings_call dataset,
filter to our companies, and land them in raw.transcripts.

Idempotent: transcript_id is a deterministic hash of ticker+date+source, and
we upsert on it.
"""
from __future__ import annotations

import hashlib
import re

from datasets import concatenate_datasets, load_dataset

from fdp.db import cursor

SOURCE = "jlh-ibm/earnings_call"
_QRE = re.compile(r"Q([1-4])\s+(\d{4})")


def _transcript_id(ticker: str, date: str, source: str) -> str:
    return hashlib.sha1(f"{source}|{ticker}|{date}".encode()).hexdigest()[:16]


def _parse_quarter(text: str, date_str: str) -> tuple[str | None, int | None]:
    """Prefer the 'Q2 2016' marker in the transcript header; fall back to
    the calendar quarter of the call date."""
    head = text[:600]
    m = _QRE.search(head)
    if m:
        return f"Q{m.group(1)}", int(m.group(2))
    # fallback: calendar quarter from date (YYYY-MM-DD)
    try:
        y, mth, _ = date_str.split("-")
        q = (int(mth) - 1) // 3 + 1
        return f"Q{q}", int(y)
    except Exception:
        return None, None


UPSERT = """
INSERT INTO raw.transcripts
  (transcript_id, ticker, company, call_date, fiscal_year, quarter,
   doc_type, source, content, n_chars)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (transcript_id) DO UPDATE
  SET content = EXCLUDED.content, n_chars = EXCLUDED.n_chars
"""


def ingest_transcripts(companies: list[dict], start: str, end: str) -> int:
    tickers = {c["ticker"] for c in companies}
    name_by_ticker = {c["ticker"]: c["name"] for c in companies}

    print("  [transcripts] downloading dataset (jlh-ibm/earnings_call) ...")
    dd = load_dataset(SOURCE, "transcripts")
    ds = concatenate_datasets([dd[s] for s in dd.keys()])

    rows = []
    for r in ds:
        ticker = r["company"]
        if ticker not in tickers:
            continue
        date_str = str(r["date"])
        if date_str < start or date_str > end:
            continue
        text = r["transcript"] or ""
        if not text.strip():
            continue
        quarter, fy = _parse_quarter(text, date_str)
        tid = _transcript_id(ticker, date_str, SOURCE)
        rows.append((
            tid, ticker, name_by_ticker.get(ticker), date_str, fy, quarter,
            "earnings_call", SOURCE, text, len(text),
        ))

    if rows:
        with cursor() as cur:
            cur.executemany(UPSERT, rows)
    print(f"  [transcripts] landed {len(rows)} transcripts "
          f"for {len({r[1] for r in rows})} companies")
    return len(rows)
