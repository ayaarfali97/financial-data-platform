"""Central config, loaded from environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of this file's parent (fdp/ -> project root)
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str | None = None) -> str:
    val = os.getenv(key, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


@dataclass(frozen=True)
class Settings:
    # LLM gateway
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:4000")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_chat_model: str = os.getenv("LLM_CHAT_MODEL", "gemini/gemini-3-flash")
    llm_chat_fallback: str = os.getenv("LLM_CHAT_FALLBACK", "groq/gpt-oss-120b")
    llm_embed_model: str = os.getenv("LLM_EMBED_MODEL", "gemini-embedding-001")
    embed_dim: int = int(os.getenv("EMBED_DIM", "1536"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1800"))

    # SEC
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "financial-data-platform example@example.com")
    ingest_years: int = int(os.getenv("INGEST_YEARS", "5"))

    # Postgres — chooses internal (docker network) vs host automatically.
    @property
    def pg_host(self) -> str:
        # If IN_DOCKER is set (see compose), talk to the service name.
        if os.getenv("IN_DOCKER") == "1":
            return os.getenv("POSTGRES_HOST_INTERNAL", "postgres")
        return os.getenv("POSTGRES_HOST", "localhost")

    @property
    def pg_port(self) -> int:
        if os.getenv("IN_DOCKER") == "1":
            return int(os.getenv("POSTGRES_PORT_INTERNAL", "5432"))
        return int(os.getenv("POSTGRES_PORT", "5433"))

    @property
    def pg_user(self) -> str:
        return os.getenv("POSTGRES_USER", "fdp")

    @property
    def pg_password(self) -> str:
        return os.getenv("POSTGRES_PASSWORD", "fdp_local_pw")

    @property
    def pg_db(self) -> str:
        return os.getenv("POSTGRES_DB", "financial")

    @property
    def sqlalchemy_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )


settings = Settings()
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
