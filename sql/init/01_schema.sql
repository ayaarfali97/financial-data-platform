-- Runs once at first container start (docker-entrypoint-initdb.d).
-- pgvector + landing schemas for the raw / vector / ml layers.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS ml;

-- ── company reference (seeded by ingestion agent) ───────────────────────────
CREATE TABLE IF NOT EXISTS raw.company (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    cik         TEXT NOT NULL,
    sector      TEXT
);

-- ── raw financial facts from SEC EDGAR companyfacts API ─────────────────────
-- One row per (company, concept, reported period). Idempotent on the unique key.
CREATE TABLE IF NOT EXISTS raw.financial_facts (
    id           BIGSERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    cik          TEXT NOT NULL,
    concept      TEXT NOT NULL,       -- us-gaap tag, e.g. Revenues
    label        TEXT,
    unit         TEXT NOT NULL,       -- USD, shares, etc.
    value        NUMERIC,
    fy           INT,                 -- fiscal year
    fp           TEXT,                -- fiscal period: FY, Q1..Q4
    form         TEXT,                -- 10-K, 10-Q
    period_start DATE,
    period_end   DATE NOT NULL,
    filed        DATE,
    accn         TEXT,                -- accession number
    frame        TEXT,
    UNIQUE (ticker, concept, unit, period_end, fp, accn)
);
CREATE INDEX IF NOT EXISTS ix_facts_ticker ON raw.financial_facts (ticker);
CREATE INDEX IF NOT EXISTS ix_facts_concept ON raw.financial_facts (concept);

-- ── full-text transcript landing ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw.transcripts (
    transcript_id TEXT PRIMARY KEY,   -- deterministic hash of ticker+date+source
    ticker        TEXT NOT NULL,
    company       TEXT,
    call_date     DATE,
    fiscal_year   INT,
    quarter       TEXT,               -- Q1..Q4
    doc_type      TEXT DEFAULT 'earnings_call',
    source        TEXT,
    content       TEXT NOT NULL,
    n_chars       INT
);

-- ── transcript chunks + embeddings (the vector store) ───────────────────────
CREATE TABLE IF NOT EXISTS vector.transcript_chunks (
    id            BIGSERIAL PRIMARY KEY,
    transcript_id TEXT NOT NULL REFERENCES raw.transcripts(transcript_id) ON DELETE CASCADE,
    ticker        TEXT NOT NULL,
    company       TEXT,
    call_date     DATE,
    fiscal_year   INT,
    quarter       TEXT,
    doc_type      TEXT DEFAULT 'earnings_call',
    chunk_index   INT NOT NULL,
    content       TEXT NOT NULL,
    embedding     vector(384),
    UNIQUE (transcript_id, chunk_index)
);
-- metadata filter indexes (vector filtering strategy: pre-filter by these,
-- then ANN search on embedding)
CREATE INDEX IF NOT EXISTS ix_chunks_ticker   ON vector.transcript_chunks (ticker);
CREATE INDEX IF NOT EXISTS ix_chunks_doctype  ON vector.transcript_chunks (doc_type);
CREATE INDEX IF NOT EXISTS ix_chunks_date     ON vector.transcript_chunks (call_date);
-- ANN index (cosine). Built after data load; ivfflat needs ANALYZE to be useful.
CREATE INDEX IF NOT EXISTS ix_chunks_embedding
    ON vector.transcript_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- ── ML outputs (written by the ML agent) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS ml.ml_outputs (
    id            BIGSERIAL PRIMARY KEY,
    model_name    TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    transcript_id TEXT,
    call_date     DATE,
    fiscal_year   INT,
    quarter       TEXT,
    metric        TEXT NOT NULL,      -- e.g. sentiment_score, sentiment_label
    value_num     DOUBLE PRECISION,
    value_text    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (model_name, ticker, transcript_id, metric)
);
CREATE INDEX IF NOT EXISTS ix_ml_ticker ON ml.ml_outputs (ticker);

-- ── router observability log ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw.router_log (
    id           BIGSERIAL PRIMARY KEY,
    asked_at     TIMESTAMPTZ DEFAULT now(),
    question     TEXT NOT NULL,
    route        TEXT,                -- sql | vector | ml | hybrid
    rationale    TEXT,
    tools_used   TEXT,
    answer       TEXT,
    latency_ms   INT,
    ok           BOOLEAN
);
