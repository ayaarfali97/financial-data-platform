# Financial Data Platform — Agentic Data Engineering

An end-to-end analytics pipeline built as **five specialized agents** rather than
one script, to showcase multi-agent AI data engineering:

> **Raw → Data Warehouse → ML → Agentic Query Layer → Dashboard**

Real SEC EDGAR financials + real earnings-call transcripts for **8 tech companies**
(AAPL, AMD, AMZN, CSCO, GOOGL, INTC, MSFT, NVDA), **2016–2020**, land in Postgres,
are modeled into a dbt star schema, enriched with an ML sentiment model, and served
through an LLM query router and a Streamlit dashboard.

---

## Architecture

```
                         ┌─────────────────────────────────────────────┐
   SEC EDGAR  ─────┐     │                 POSTGRES + pgvector          │
   (financials)    │     │                                             │
                   ├────▶│  raw.*      financial_facts, transcripts,    │
   HF transcripts  │  ①  │             company, router_log             │
   (jlh-ibm)  ─────┘     │  vector.*   transcript_chunks (384-d embeds) │
                         │  ml.*       ml_outputs (sentiment)           │
                         │  marts.*    dims + facts + KPI marts   ◀──② dbt
                         └─────────────────────────────────────────────┘
                               ▲            ▲             ▲
                               │ ③ ML       │ ④ Router    │
                        ┌──────┴─────┐ ┌────┴──────┐ ┌────┴─────┐
                        │ ML Agent   │ │  Query    │ │  Eval    │
                        │ LM tone    │ │  Router   │ │  Agent ⑤ │
                        └────────────┘ │  Agent    │ └──────────┘
                                       └─────┬─────┘
                                             │
                                  ┌──────────┴──────────┐
                                  │  Streamlit dashboard │  (4 tabs)
                                  └─────────────────────┘

  ① Ingestion Agent   ② Modeling Agent (dbt)   ③ ML Agent
  ④ Query Router Agent (SQL | vector | ML | hybrid)   ⑤ Eval Agent
```

### The five agents

| # | Agent | Does | Entry point |
|---|-------|------|-------------|
| 1 | **Ingestion** | Pull EDGAR financials + HF transcripts; chunk & embed transcripts into pgvector. Idempotent. | `python -m agents.ingestion.ingest` |
| 2 | **Modeling (dbt)** | Staging → dims (`dim_company/date/document_type`) → facts (`fact_financial_metrics`, `fact_transcript_mentions`) → KPI marts. 23 data tests. | `dbt run && dbt test` |
| 3 | **ML** | Loughran-McDonald earnings-call tone → `ml.ml_outputs`. Validated against real events. | `python -m agents.ml.train_sentiment` |
| 4 | **Query Router** | LLM classifies each question → SQL / vector / ML / hybrid, executes, synthesizes an answer, logs to `raw.router_log`. | `python -m agents.router.router "..."` |
| 5 | **Eval** | 18 Q&A pairs across all routes, run against the router, pass/fail. | `python -m agents.eval.eval` |

---

## Stack

- **Postgres 16 + pgvector** — structured warehouse *and* vector store in one DB
- **dbt** (postgres adapter) — star schema, KPI marts, data tests
- **Python** — ingestion, embeddings, ML, router
- **fastembed** (`BAAI/bge-small-en-v1.5`, 384-d, CPU/ONNX) — local, quota-free embeddings
- **LiteLLM gateway** (OpenAI-compatible) — router LLM (`gemini-3-flash`, Groq fallback)
- **Streamlit + Altair** — dashboard
- **Docker Compose** — packaging

---

## Quick start

```bash
cp .env.example .env          # set LLM_BASE_URL + LLM_API_KEY (any OpenAI-compatible gateway)
docker compose up -d postgres # Postgres + pgvector (schemas auto-created)

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make ingest    # ① raw + embeddings
make dbt       # ② warehouse + tests
make ml        # ③ sentiment
make eval      # ⑤ router eval
make dashboard # → http://localhost:8501
```

Or the whole thing containerized:

```bash
docker compose up -d                          # postgres + dashboard
docker compose run --rm agents python -m agents.ingestion.ingest
docker compose run --rm agents bash -lc 'cd dbt/financial_warehouse && dbt run && dbt test'
docker compose run --rm agents python -m agents.ml.train_sentiment
# dashboard at http://localhost:8501
```

---

## Data modeling choices

- **Two grains, on purpose.** `mart_company_kpis` is **quarterly** (margins, QoQ/YoY
  per quarter); `mart_company_annual` is **full-year**. EDGAR does *not* expose a
  discrete 3-month value for every fiscal quarter (the September quarter is usually
  only in the 10-K), so **summing quarters undercounts revenue**. Annual totals come
  from the 10-K annual figures and are authoritative — the router is told to use the
  annual mart for full-year questions.
- **Canonical metrics.** us-gaap tags are messy (revenue alone is `Revenues` *or*
  `RevenueFromContractWithCustomerExcludingAssessedTax`). Staging coalesces them and
  `stg_financial_facts` classifies each fact as `quarter` / `annual` / `instant`.
- **Restatement dedup.** EDGAR returns the same period from multiple filings; we keep
  the **most recently filed** value per (ticker, metric, unit, period, grain).
- **YoY the right way.** Because quarters are unevenly spaced, YoY growth is computed
  by matching the **same calendar quarter one year earlier** (self-join), not a
  positional `lag(4)`.

## Vector filtering strategy

Every transcript chunk carries metadata: `ticker`, `company`, `call_date`,
`fiscal_year`, `quarter`, `doc_type`. On a query the router:

1. **Pre-filters** candidates by ticker/year using cheap b-tree indexes
   (detected from the question), shrinking the search space, then
2. ranks the survivors by **cosine distance** on the 384-d embedding
   (`ivfflat` index, `vector_cosine_ops`).

This "filter-then-ANN" approach keeps results on-topic (e.g. an Apple question never
returns NVIDIA passages) and fast.

## ML model choice (an honest one)

A supervised TF-IDF classifier trained on this dataset's paragraph labels scores
**below the majority-class baseline** (~0.53 vs 0.56) — the labels track post-call
price moves, which paragraph text can't predict. So the ML agent uses the
finance-standard **Loughran-McDonald sentiment dictionary** (deterministic,
interpretable) and *validates* it against reality instead of quoting a fake accuracy:

- **The model captures the COVID shock.** Average call tone is a steady ~0.17–0.35
  every quarter but **collapses to 0.10 in 2020-Q2** — the lowest of all 19 quarters,
  exactly when the pandemic hit. (See `models_store/metrics.json` and the ML tab.)

---

## Eval results

Each of 18 questions is graded on: **route** correctness, whether **context** was
retrieved (`grounded`), and whether the answer contains the expected **anchor facts**.

```
QUERY ROUTER — EVAL REPORT
--------------------------------------------------------------------------
route      passed     examples
sql        7/7        "Amazon's full-year 2019 revenue?" → $280.5B
vector     5/5        "What did NVIDIA say about data center demand?"
ml         3/3        "Which call had the most negative tone?" → AMZN
hybrid     3/3        "Did Intel's tone match its revenue trend in 2020?"
--------------------------------------------------------------------------
PASS 18/18  (100%)    route-accuracy 100%    avg ~3–7s/question
```

Reproduce with `make eval` (writes `agents/eval/results.json`). Latency depends on
the LLM gateway; on free-tier rate limits the eval self-throttles.

---

## Repo layout

```
fdp/                 shared: settings, db, llm gateway client, local embeddings
agents/
  ingestion/         edgar.py, transcripts.py, chunk_embed.py, ingest.py
  ml/                train_sentiment.py         (LM tone + validation)
  router/            router.py, tools.py        (SQL / vector / ML tools)
  eval/              eval.py, qa_pairs.yml
dbt/financial_warehouse/
  models/staging     stg_companies, stg_financial_facts, stg_transcripts
  models/marts       dim_*, fact_*, mart_company_kpis, mart_company_annual
dashboard/app.py     Streamlit, 4 tabs
sql/init/            pgvector + schema bootstrap
docker-compose.yml   postgres + agents + dashboard
```
