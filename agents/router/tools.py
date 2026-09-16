"""Execution tools the router can dispatch to: SQL (warehouse), vector
(transcripts), and ML (sentiment). Each returns structured context that the
synthesis step turns into a natural-language answer.
"""
from __future__ import annotations

import re

from fdp.db import connect, query_dicts
from fdp.embeddings import embed_text
from fdp.llm import chat

# ── schema shown to the text-to-SQL model ───────────────────────────────────
SCHEMA_DOC = """
You write Postgres SQL against a financial warehouse. Only these tables exist:

marts.dim_company(ticker, company_name, cik, sector, first_period, last_period)

marts.fact_financial_metrics(
  ticker, period_end DATE, grain TEXT ['quarter'|'annual'], year, quarter, year_quarter,
  fiscal_year, fiscal_period, revenue, cost_of_revenue, gross_profit,
  operating_income, operating_expenses, rnd_expense, net_income,
  eps_diluted, eps_basic, assets, liabilities, equity, cash)   -- USD

marts.mart_company_kpis(
  ticker, period_end DATE, year, quarter, year_quarter, fiscal_year,
  revenue, gross_profit, operating_income, net_income, rnd_expense, eps_diluted,
  gross_margin_pct, operating_margin_pct, net_margin_pct, rnd_intensity_pct,
  revenue_yoy_growth_pct, revenue_qoq_growth_pct, net_income_yoy_growth_pct)  -- one row per fiscal QUARTER

marts.mart_company_annual(
  ticker, year, period_end, revenue, gross_profit, operating_income, net_income,
  rnd_expense, eps_diluted, assets, liabilities, equity, cash,
  gross_margin_pct, operating_margin_pct, net_margin_pct, rnd_intensity_pct,
  revenue_yoy_growth_pct, net_income_yoy_growth_pct)  -- one row per FULL YEAR (authoritative annual totals)

marts.fact_transcript_mentions(
  transcript_id, ticker, company_name, call_date DATE, fiscal_year, quarter,
  n_chars, mentions_ai, mentions_cloud, mentions_datacenter, mentions_gaming,
  mentions_supply_chain, mentions_guidance, mentions_capital_return,
  mentions_headwind, mentions_positive)

ml.ml_outputs(model_name, ticker, transcript_id, call_date, fiscal_year, quarter,
  metric ['sentiment_score'|'sentiment_label'|'sentiment_subjectivity'],
  value_num, value_text)   -- model_name = 'lm_tone_v1'

Rules:
- Data covers 8 tech tickers (AAPL, AMD, AMZN, CSCO, GOOGL, INTC, MSFT, NVDA), 2016-2020.
- Revenue/income are in USD (divide by 1e9 for billions if helpful).
- For QUARTERLY "growth", "margin", "KPI" questions use marts.mart_company_kpis.
- For FULL-YEAR / ANNUAL totals and rankings use marts.mart_company_annual
  (do NOT sum quarters from mart_company_kpis — some quarters are absent in EDGAR).
- Use year_quarter like '2020-Q2' for quarter filters; use year (int) for annual.
- Return ONLY a single read-only SELECT (or WITH ... SELECT). No comments, no prose.
"""

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|call|do|merge)\b",
    re.I,
)


def generate_sql(question: str) -> str:
    msg = [
        {"role": "system", "content": SCHEMA_DOC},
        {"role": "user", "content": (
            f"Question: {question}\n\n"
            "Return ONLY the SQL wrapped in a ```sql code block, nothing else.")},
    ]
    # generous budget: the chat model reasons before emitting the fenced SQL
    raw = chat(msg, temperature=0.0, max_tokens=2500)
    return _extract_sql(raw)


def _extract_sql(raw: str) -> str:
    s = raw.strip()
    # 1) complete ```sql ... ``` block
    m = re.search(r"```(?:sql)?\s*(.*?)```", s, re.DOTALL | re.I)
    if m:
        return m.group(1).strip().rstrip(";").strip()
    # 2) opening fence with no close (truncated)
    m = re.search(r"```(?:sql)?\s*(.*)$", s, re.DOTALL | re.I)
    if m and re.search(r"\b(with|select)\b", m.group(1), re.I):
        return m.group(1).strip().rstrip(";").strip()
    # 3) no fences: slice from the last standalone WITH/SELECT keyword
    kw = list(re.finditer(r"(?im)^\s*(with|select)\b", s))
    if kw:
        return s[kw[-1].start():].strip().rstrip(";").strip()
    kw = list(re.finditer(r"\b(WITH|SELECT)\b", s))
    if kw:
        return s[kw[-1].start():].strip().rstrip(";").strip()
    return s.strip().rstrip(";").strip()


def _sanitize(sql: str) -> str:
    low = sql.lower().lstrip()
    if not (low.startswith("select") or low.startswith("with")):
        raise ValueError("Only SELECT/WITH queries are allowed")
    if ";" in sql:
        raise ValueError("Multiple statements are not allowed")
    if _FORBIDDEN.search(sql):
        raise ValueError("Query contains a forbidden keyword")
    if not re.search(r"\blimit\b", sql, re.I):
        sql += "\nLIMIT 200"
    return sql


def run_sql(question: str) -> dict:
    """Text-to-SQL against the warehouse, executed read-only."""
    sql = _sanitize(generate_sql(question))
    conn = connect()
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET statement_timeout = '8s'")
            cur.execute(sql)
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.rollback()
    finally:
        conn.close()
    return {"sql": sql, "columns": cols, "rows": rows, "n": len(rows)}


# ── vector tool ─────────────────────────────────────────────────────────────
_TICKERS = ["AAPL", "AMD", "AMZN", "CSCO", "GOOGL", "INTC", "MSFT", "NVDA"]
_NAME_HINTS = {
    "apple": "AAPL", "amd": "AMD", "advanced micro": "AMD", "amazon": "AMZN",
    "cisco": "CSCO", "alphabet": "GOOGL", "google": "GOOGL", "intel": "INTC",
    "microsoft": "MSFT", "nvidia": "NVDA",
}


def detect_tickers(question: str) -> list[str]:
    q = question.lower()
    found = {t for t in _TICKERS if re.search(rf"\b{t.lower()}\b", q)}
    for hint, tk in _NAME_HINTS.items():
        if hint in q:
            found.add(tk)
    return sorted(found)


def detect_years(question: str) -> list[int]:
    return sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", question)
                   if 2016 <= int(y) <= 2020})


def run_vector(question: str, k: int = 6) -> dict:
    """Metadata-filtered ANN search over transcript chunks.

    Vector filtering strategy: pre-filter by ticker/year (cheap b-tree indexes)
    to shrink the candidate set, THEN rank by cosine distance on the embedding.
    """
    qvec = embed_text(question)
    tickers = detect_tickers(question)
    years = detect_years(question)

    where, params = [], []
    if tickers:
        where.append("ticker = ANY(%s)")
        params.append(tickers)
    if years:
        where.append("extract(year from call_date)::int = ANY(%s)")
        params.append(years)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = f"""
        SELECT ticker, company, call_date, quarter, fiscal_year, chunk_index,
               content, 1 - (embedding <=> %s::vector) AS similarity
        FROM vector.transcript_chunks
        {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT {k}
    """
    rows = query_dicts(sql, [qvec, *params, qvec])
    return {"filters": {"tickers": tickers, "years": years},
            "passages": rows, "n": len(rows)}


# ── ml tool ─────────────────────────────────────────────────────────────────
def run_ml(question: str) -> dict:
    tickers = detect_tickers(question)
    years = detect_years(question)
    where = ["metric = 'sentiment_score'"]
    params: list = []
    if tickers:
        where.append("ticker = ANY(%s)")
        params.append(tickers)
    if years:
        where.append("extract(year from call_date)::int = ANY(%s)")
        params.append(years)
    sql = f"""
        SELECT ticker,
               to_char(call_date,'YYYY-"Q"Q') AS quarter,
               call_date,
               round(value_num::numeric,3) AS sentiment_score,
               (SELECT value_text FROM ml.ml_outputs l2
                 WHERE l2.transcript_id=l.transcript_id AND l2.metric='sentiment_label') AS label
        FROM ml.ml_outputs l
        WHERE {' AND '.join(where)}
        ORDER BY ticker, call_date
    """
    rows = query_dicts(sql, params)

    # cross-company average tone per quarter — lets the router answer aggregate
    # questions like "which quarter had the lowest average sentiment?"
    quarter_avg = query_dicts("""
        SELECT to_char(call_date,'YYYY-"Q"Q') AS quarter,
               round(avg(value_num)::numeric,3) AS avg_sentiment,
               count(*) AS n_calls
        FROM ml.ml_outputs
        WHERE model_name='lm_tone_v1' AND metric='sentiment_score'
        GROUP BY 1 ORDER BY avg_sentiment ASC
    """)
    return {"filters": {"tickers": tickers, "years": years},
            "rows": rows, "quarter_avg": quarter_avg, "n": len(rows)}
