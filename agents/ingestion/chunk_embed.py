"""Chunk landed transcripts and write embeddings into vector.transcript_chunks.

Chunking: word-window with overlap (keeps sentences of context together).
Metadata carried on every chunk: ticker, company, call_date, fiscal_year,
quarter, doc_type — this is what the vector layer filters on before ANN search.

Idempotent: by default we skip transcripts that already have chunks. Pass
force=True to re-embed everything.
"""
from __future__ import annotations

from fdp.db import cursor, query
from fdp.embeddings import embed_texts

CHUNK_WORDS = 400
OVERLAP_WORDS = 50


def _chunk(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks, i = [], 0
    step = CHUNK_WORDS - OVERLAP_WORDS
    while i < len(words):
        chunks.append(" ".join(words[i : i + CHUNK_WORDS]))
        i += step
    return chunks


UPSERT = """
INSERT INTO vector.transcript_chunks
  (transcript_id, ticker, company, call_date, fiscal_year, quarter,
   doc_type, chunk_index, content, embedding)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (transcript_id, chunk_index) DO UPDATE
  SET content = EXCLUDED.content, embedding = EXCLUDED.embedding
"""


def embed_transcripts(force: bool = False) -> int:
    transcripts = query(
        """SELECT transcript_id, ticker, company, call_date, fiscal_year,
                  quarter, doc_type, content
           FROM raw.transcripts ORDER BY ticker, call_date"""
    )
    already = set()
    if not force:
        already = {r[0] for r in query(
            "SELECT DISTINCT transcript_id FROM vector.transcript_chunks")}

    total_chunks = 0
    for (tid, ticker, company, call_date, fy, quarter, doc_type, content) in transcripts:
        if tid in already:
            continue
        chunks = _chunk(content)
        if not chunks:
            continue
        vectors = embed_texts(chunks)
        rows = [
            (tid, ticker, company, call_date, fy, quarter, doc_type, idx, ch, vec)
            for idx, (ch, vec) in enumerate(zip(chunks, vectors))
        ]
        with cursor() as cur:
            cur.executemany(UPSERT, rows)
        total_chunks += len(rows)
        print(f"  [embed] {ticker} {call_date} -> {len(rows)} chunks")

    # refresh ANN planner stats after a bulk load
    with cursor() as cur:
        cur.execute("ANALYZE vector.transcript_chunks")
    return total_chunks
