"""Ingestion Agent — orchestrates the raw layer end to end.

Steps (all idempotent, safe to re-run):
  1. seed raw.company from config/companies.yml
  2. pull EDGAR financials  -> raw.financial_facts
  3. load transcripts       -> raw.transcripts
  4. chunk + embed          -> vector.transcript_chunks

Usage:
  python -m agents.ingestion.ingest              # full run
  python -m agents.ingestion.ingest --skip-embed # everything but embeddings
  python -m agents.ingestion.ingest --force-embed # re-embed all transcripts
"""
from __future__ import annotations

import argparse
import sys

import yaml

from fdp.db import cursor, wait_ready
from fdp.settings import CONFIG_DIR

from .chunk_embed import embed_transcripts
from .edgar import ingest_financials
from .transcripts import ingest_transcripts


def load_config() -> dict:
    with open(CONFIG_DIR / "companies.yml") as f:
        return yaml.safe_load(f)


def seed_companies(companies: list[dict]) -> None:
    rows = [(c["ticker"], c["name"], c["cik"], c.get("sector")) for c in companies]
    with cursor() as cur:
        cur.executemany(
            """INSERT INTO raw.company (ticker, name, cik, sector)
               VALUES (%s,%s,%s,%s)
               ON CONFLICT (ticker) DO UPDATE
                 SET name = EXCLUDED.name, cik = EXCLUDED.cik,
                     sector = EXCLUDED.sector""",
            rows,
        )
    print(f"  [company] seeded {len(rows)} companies")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-embed", action="store_true")
    ap.add_argument("--force-embed", action="store_true")
    ap.add_argument("--only", choices=["company", "financials", "transcripts", "embed"])
    args = ap.parse_args()

    if not wait_ready():
        print("Postgres not reachable", file=sys.stderr)
        return 1

    cfg = load_config()
    companies = cfg["companies"]
    start, end = cfg["period"]["start"], cfg["period"]["end"]

    print(f"== Ingestion Agent | {len(companies)} companies | {start} .. {end} ==")

    if args.only in (None, "company"):
        seed_companies(companies)
    if args.only in (None, "financials"):
        n = ingest_financials(companies, start, end)
        print(f"  [edgar] total {n} financial facts")
    if args.only in (None, "transcripts"):
        ingest_transcripts(companies, start, end)
    if args.only in (None, "embed") and not args.skip_embed:
        n = embed_transcripts(force=args.force_embed)
        print(f"  [embed] total {n} chunks embedded")

    print("== Ingestion complete ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
