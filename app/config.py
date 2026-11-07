"""Global settings (env vars) + layered per-project settings.

Resolution order for any project setting:  DEFAULTS  <-  project.settings overrides.
Add a new knob by adding it to DEFAULTS; every project inherits it automatically
and can override it from the settings page without a migration.
"""
from __future__ import annotations

import copy
import time
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/link_engine.db"  # Railway injects DATABASE_URL (Postgres)
    secret_key: str = "dev-only-change-me"  # used to derive the encryption key for stored secrets
    admin_password: str = "admin"  # v1 single admin login; replace with real users later

    anthropic_api_key: str = ""
    ahrefs_api_key: str = ""
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # Model routing: cheap/high-volume vs. important pieces. Override via env.
    model_default: str = "claude-sonnet-5-5"
    model_premium: str = "claude-opus-5-5"

    worker_poll_seconds: int = 5
    job_max_attempts: int = 1  # 1 = never auto-retry; failed jobs wait for a manual re-run


# Editable from the UI (Global settings). DATABASE_URL / SECRET_KEY stay env-only (bootstrap).
SECRET_KEYS = ("anthropic_api_key", "ahrefs_api_key", "dataforseo_login", "dataforseo_password", "admin_password")
PLAIN_KEYS = ("model_default", "model_premium", "worker_poll_seconds", "job_max_attempts")
_cache: dict = {"t": 0.0, "v": None}


def invalidate_settings() -> None:
    _cache["v"] = None


def get_settings() -> Settings:
    """Env settings overlaid with values saved in the UI (cached 15s)."""
    now = time.monotonic()
    if _cache["v"] is not None and now - _cache["t"] < 15:
        return _cache["v"]
    s = base_settings().model_copy()
    try:
        from app.db import SessionLocal
        from app.models import AppSetting
        from app.security import decrypt

        with SessionLocal() as db:
            for row in db.query(AppSetting).all():
                if row.key in SECRET_KEYS and row.value:
                    setattr(s, row.key, decrypt(row.value))
                elif row.key in PLAIN_KEYS and row.value != "":
                    setattr(s, row.key, type(getattr(s, row.key))(row.value))
    except Exception:  # noqa: BLE001  (table missing on first boot, etc.)
        pass
    _cache.update(t=now, v=s)
    return s


@lru_cache
def base_settings() -> Settings:
    s = Settings()
    # Railway/Heroku style URLs use postgres:// ; SQLAlchemy + psycopg3 wants postgresql+psycopg://
    if s.database_url.startswith("postgres://"):
        s.database_url = s.database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif s.database_url.startswith("postgresql://"):
        s.database_url = s.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return s


# ---------------------------------------------------------------------------
# Per-project defaults. Everything here is editable per project.
# ---------------------------------------------------------------------------
DEFAULTS: dict = {
    "market": {"country": "us", "language": "en", "location_code": 2840},
    "discovery": {
        "providers": ["ahrefs", "dataforseo"],  # tried in order; first configured one wins
        "max_competitors": 10,
        "backlinks_per_competitor": 300,  # sorted by DR; rows past ~300 are mostly junk
        "min_link_dr": 10,  # filtered on the provider side -> we don't pay for junk rows
        "include_traffic": False,  # Ahrefs traffic_domain costs 10 units/row; DR is enough for scoring
        # Our own links are pulled too; spam is filtered out provider-side, so it is never paid for.
        "pull_own_backlinks": True,
        "refresh_days": 30,  # don't re-pull a competitor more often than this
        "monthly_unit_budget": 10000,  # per project; jobs stop + alert when exceeded (0 = no limit)
        # A competitor "has enough data" if it clears these; otherwise we ask the user for one.
        "min_competitor_refdomains": 50,
        "seed_keywords": [],
        "never_competitors": [],  # extra domains never treated as competitors
    },
    "quality": {
        "min_dr": 10,
        "min_traffic": 0,
        "reject_spam_flag": True,
        "spam_tokens": ["casino", "betting", "cbd", "viagra", "loan", "porn", "escort", "essay"],
        "relevance_terms": ["shirt", "tee", "apparel", "gift", "funny", "graphic", "fashion", "clothing", "merch"],
        "blocklist": [],
        # Country TLDs outside the target market (US default). Set [] for international brands.
        "exclude_tlds": ["ru", "pl", "no", "dk", "nl", "de", "fr", "es", "it", "il", "id", "my", "ua", "br", "cz", "lk", "mk"],
        "weights": {"dr": 0.30, "traffic": 0.15, "overlap": 0.25, "relevance": 0.20, "dofollow": 0.10},
    },
    "automation": {
        # per-channel: "approve" (queue) | "auto" (publish without review) | "off"
        "default_mode": "approve",
        "channels": {},
    },
    "limits": {
        # token-bucket style caps per channel per day; random jitter between actions
        "default_per_day": 5,
        "per_channel_per_day": {"reddit": 2, "quora": 3, "medium": 1, "email": 5, "pinterest": 10},
        "jitter_minutes": [3, 12],
        "business_hours": [9, 17],
        "email_ramp": {"start": 5, "max": 30, "weeks": 4, "bounce_pause_pct": 3.0, "followups": 1, "followup_days": 5},
    },
    "alerts": {"daily_digest": True, "digest_hour": 8, "chat": {"provider": "", "target": ""}},
}


def merged_settings(overrides: dict | None) -> dict:
    """Deep-merge project overrides onto DEFAULTS (dicts merge, everything else replaces)."""
    out = copy.deepcopy(DEFAULTS)

    def _merge(dst: dict, src: dict) -> None:
        for k, v in (src or {}).items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = v

    _merge(out, overrides or {})
    return out
