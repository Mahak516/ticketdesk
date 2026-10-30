"""Application settings, read from environment variables."""

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_DATABASE_URL = "postgresql+psycopg2://ticketdesk:ticketdesk@localhost:5432/ticketdesk"


@dataclass(frozen=True)
class Settings:
    database_url: str
    slow_call_ms: float
    cors_origins: tuple[str, ...]


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        slow_call_ms=float(os.getenv("SLOW_CALL_MS", "200")),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
    )
