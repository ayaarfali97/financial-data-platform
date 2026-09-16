"""Local embeddings via fastembed (ONNX, CPU, no external quota).

Used for BOTH transcript-chunk embedding (ingestion) and query embedding
(router), so the vector space is identical on both sides. Deterministic and
fully offline after the one-time model download.
"""
from __future__ import annotations

from functools import lru_cache

from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim
DIM = 384


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    return TextEmbedding(MODEL_NAME)


def embed_text(text: str) -> list[float]:
    return next(iter(_model().embed([text]))).tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [v.tolist() for v in _model().embed(texts)]
