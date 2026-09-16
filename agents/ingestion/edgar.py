"""Pull structured financials from the SEC EDGAR companyfacts API.

EDGAR is free and authoritative but requires a descriptive User-Agent.
We pull a curated set of us-gaap concepts; different filers tag revenue
differently, so we try several candidates and keep whatever exists.
Idempotent: upsert on (ticker, concept, unit, period_end, fp, accn).
"""
from __future__ import annotations

import time
from typing import Any

import requests

from fdp.db import cursor
from fdp.settings import settings

BASE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Curated income-statement + balance-sheet concepts. Revenue has multiple
# possible tags; dbt staging later coalesces them into one canonical metric.
CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "GrossProfit",
    "OperatingIncomeLoss",
    "OperatingExpenses",
    "ResearchAndDevelopmentExpense",
    "NetIncomeLoss",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
]

KEEP_FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A"}


def _fetch_facts(cik: str) -> dict[str, Any]:
    url = BASE.format(cik=cik)
    headers = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def _rows_for_company(ticker: str, cik: str, facts: dict, start: str, end: str) -> list[tuple]:
    rows: list[tuple] = []
    usgaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in CONCEPTS:
        node = usgaap.get(concept)
        if not node:
            continue
        label = node.get("label")
        for unit, entries in node.get("units", {}).items():
            for e in entries:
                form = e.get("form")
                if form not in KEEP_FORMS:
                    continue
                period_end = e.get("end")
                if not period_end or period_end < start or period_end > end:
                    continue
                rows.append((
                    ticker, cik, concept, label, unit,
                    e.get("val"), e.get("fy"), e.get("fp"), form,
                    e.get("start"), period_end, e.get("filed"),
                    e.get("accn"), e.get("frame"),
                ))
    return rows


UPSERT = """
INSERT INTO raw.financial_facts
  (ticker, cik, concept, label, unit, value, fy, fp, form,
   period_start, period_end, filed, accn, frame)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (ticker, concept, unit, period_end, fp, accn) DO UPDATE
  SET value = EXCLUDED.value, filed = EXCLUDED.filed, label = EXCLUDED.label
"""


def ingest_financials(companies: list[dict], start: str, end: str) -> int:
    total = 0
    for c in companies:
        ticker, cik = c["ticker"], c["cik"]
        print(f"  [edgar] {ticker} (CIK {cik}) ...", end=" ", flush=True)
        try:
            facts = _fetch_facts(cik)
        except Exception as exc:
            print(f"FAILED: {exc}")
            continue
        rows = _rows_for_company(ticker, cik, facts, start, end)
        if rows:
            with cursor() as cur:
                cur.executemany(UPSERT, rows)
        total += len(rows)
        print(f"{len(rows)} facts")
        time.sleep(0.3)  # be polite to SEC (limit ~10 req/s)
    return total
