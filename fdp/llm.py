"""Thin client over the LiteLLM (OpenAI-compatible) gateway.

Handles two quirks of this gateway:
  * chat models are *reasoning* models that burn tokens before emitting text,
    so we always request a generous max_tokens and fall back to a second model
    if the primary returns empty / errors.
  * `response_format=json_object` is not supported, so JSON is enforced by
    prompt and parsed defensively (strip ```json fences, find first {...}).
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .settings import settings

# max_retries=0: the OpenAI SDK otherwise auto-retries 429s honoring a long
# Retry-After header, which stalls the whole pipeline. We fail fast and fall
# back to a different provider instead. timeout caps any single hung request.
_client = OpenAI(
    base_url=f"{settings.llm_base_url}/v1",
    api_key=settings.llm_api_key,
    timeout=45.0,
    max_retries=0,
)


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
def _chat_once(model: str, messages: list[dict], max_tokens: int, temperature: float) -> str:
    resp = _client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens, temperature=temperature,
    )
    content = resp.choices[0].message.content
    return content or ""


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
) -> str:
    """Return assistant text, transparently falling back to the backup model."""
    import time

    primary = model or settings.llm_chat_model
    max_tokens = max_tokens or settings.llm_max_tokens
    try:
        out = _chat_once(primary, messages, max_tokens, temperature)
        if out.strip():
            return out
    except Exception:
        pass
    # fallback model (different provider)
    try:
        out = _chat_once(settings.llm_chat_fallback, messages, max_tokens, temperature)
        if out.strip():
            return out
    except Exception:
        pass
    # last resort: both providers throttled — wait past the RPM window and retry
    time.sleep(20)
    return _chat_once(primary, messages, max_tokens, temperature)


def chat_json(messages: list[dict], **kwargs) -> dict[str, Any]:
    """Chat call that must return a JSON object; parses defensively."""
    raw = chat(messages, **kwargs)
    return _parse_json(raw)


def _parse_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # strip ```json ... ``` fences
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # grab the first balanced-looking {...}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def embed(text: str) -> list[float]:
    resp = _client.embeddings.create(model=settings.llm_embed_model, input=text)
    return resp.data[0].embedding


def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed many texts. Gateway may cap batch size, so we chunk."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = _client.embeddings.create(model=settings.llm_embed_model, input=chunk)
        # preserve order
        for item in sorted(resp.data, key=lambda d: d.index):
            out.append(item.embedding)
    return out
