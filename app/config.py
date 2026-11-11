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
    app_name: str = "Buzz Scouts Engine"
    public_base_url: str = "https://engine.buzzscouts.com"  # used in unsubscribe links
    brevo_api_key: str = ""
    hunter_api_key: str = ""
    brave_api_key: str = ""  # optional search provider for the Launch Kit (niche finder / parasite SERPs)
    require_2fa_for_admins: bool = False


# Editable from the UI (Global settings). DATABASE_URL / SECRET_KEY stay env-only (bootstrap).
SECRET_KEYS = ("anthropic_api_key", "ahrefs_api_key", "dataforseo_login", "dataforseo_password", "admin_password",
               "brevo_api_key", "hunter_api_key", "brave_api_key")
PLAIN_KEYS = ("app_name", "public_base_url", "model_default", "model_premium", "worker_poll_seconds", "job_max_attempts",
              "require_2fa_for_admins")
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
                    cur = getattr(s, row.key)
                    setattr(s, row.key, row.value in ("1", "true", "on", "True") if isinstance(cur, bool) else type(cur)(row.value))
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
        "skip_categories": [],  # catalog categories to ignore (set by project type, editable)
        # Country TLDs outside the target market (US default). Set [] for international brands.
        "exclude_tlds": ["ru", "pl", "no", "dk", "nl", "de", "fr", "es", "it", "il", "id", "my", "ua", "br", "cz", "lk", "mk"],
        "weights": {"dr": 0.30, "traffic": 0.15, "overlap": 0.25, "relevance": 0.20, "dofollow": 0.10},
    },
    "automation": {
        # per-channel: "approve" (queue) | "auto" (publish without review) | "off"
        "default_mode": "approve",
        "builders_can_approve": True,  # False = only managers/admins can approve content
        "channels": {},
    },
    "limits": {
        # token-bucket style caps per channel per day; random jitter between actions
        "default_per_day": 5,
        "per_channel_per_day": {"reddit": 2, "quora": 3, "medium": 1, "email": 5, "pinterest": 10, "own_blog": 2,
                                "telegraph": 3, "blogger": 2, "wordpress_com": 2, "tumblr": 3, "writeas": 2,
                                "hashnode": 1, "devto": 1, "mastodon": 6, "bluesky": 6, "github_pages": 3},
        "jitter_minutes": [3, 12],
        "business_hours": [9, 17],
        "email_ramp": {"start": 5, "max": 30, "weeks": 4, "bounce_pause_pct": 3.0, "followups": 1, "followup_days": 5},
    },
    "business": {
        # One place for directory / review-site / business-data submissions (NAP must match everywhere).
        "business_name": "",  # public / trading name shown on listings (e.g. T-Shirt Crisis); empty = project name
        "legal_name": "",  # company that owns the brand (only where a form asks for the legal entity)
        "company_number": "", "vat_number": "",
        "address": "", "city": "", "state": "", "postal_code": "", "country": "",
        "phone": "", "email": "", "founded": "", "hours": "", "categories": [],
        "facebook": "", "instagram": "", "pinterest": "", "tiktok": "", "linkedin": "", "x": "", "youtube": "",
    },
    "sender": {
        # Used in outreach emails and signatures so drafts never contain placeholders.
        "name": "", "title": "Founder", "email": "", "reply_to": "", "signature": "",
        "postal_address": "",  # required in commercial email (CAN-SPAM)
    },
    "outreach": {
        "timezone": "America/New_York",  # business hours are checked in this timezone
        "pr_sources": ["qwoted.com", "featured.com", "sourcebottle.com", "helpareporter.com", "sourceofsources.com",
                       "connectively.us", "terkel.io"],
        "max_contacts_per_site": 2,
    },
    "publishing": {
        "own_blog_status": "publish",  # publish | draft  (what Approve does on the blog hub)
        "own_blog_category": "",  # WordPress category name (optional)
        "shopify_blog_handle": "",  # Shopify: blog handle (empty = first blog, usually "news")
        "shopify_api_version": "2026-01",
    },
    "alerts": {"daily_digest": True, "digest_hour": 8, "chat": {"provider": "", "target": ""}},
    # AI teammate: Claude works the project with the engine's own tools when someone clicks "Run AI teammate".
    "agent": {"display_name": "AI teammate", "daily_budget_usd": 2.0, "auto_send": True,
              "auto_channels": ["outreach_email", "own_blog", "pinterest"], "max_pitches_per_run": 5, "max_steps": 40},
    # Pinterest: pins built from product/collection pages; posted via API when an account is connected, else CSV.
    "pinterest": {"enabled": True, "boards": [], "pins_per_build": 20, "csv_pins_per_day": 3},
    # Launch Kit: preloaded self-publish sites, parasite SEO, niche finder and the grey-hat tricks (app/launch_engine.py).
    "launch": {
        "keywords": [],  # niche keywords for this brand; empty = Claude suggests them on the first run
        "model": "claude-haiku-5-5",  # cheap model for bulk articles / classification ("" = global default model)
        # --- parasite SEO (articles on high-authority platforms that rank by themselves) ---
        "parasite_platforms": ["blogger", "telegraph", "wordpress_com", "tumblr", "writeas", "hashnode", "devto",
                               "medium", "linkedin"],
        "articles_per_run": 5,
        "keyword_candidates": 60,  # long-tails gathered per run (Google autocomplete is free)
        "serp_checks_per_run": 20,  # paid SERP checks per run (~$0.002 each on DataForSEO); 0 = skip
        "min_volume": 10,
        "max_difficulty": 30,
        "words": 1100,
        "outbound_links": 2,  # links to trusted outside sources per article (checked live before publishing)
        "auto_publish": True,  # API platforms publish without review (spaced, within daily limits)
        "spacing_hours": 6,  # gap between automatic publishes in one run
        "retry_next_day": True,  # when a daily limit is hit, try again tomorrow instead of waiting for a click
        # --- tiered links / indexing ---
        "tier2": True,  # after a tier-1 article goes live: social + Telegraph pointers to it
        "tier2_channels": ["bluesky", "mastodon", "telegraph"],
        "indexer_page": True,  # keep a Telegraph/GitHub page listing every new backlink (faster crawling)
        "index_check": False,  # paid site: check per new link (~$0.002 each)
        "syndicate_own_blog": True,  # repost own-blog articles to API platforms with a canonical link
        "syndicate_channels": ["devto", "hashnode", "tumblr", "writeas"],
        "anchor_mix": {"brand": 50, "naked": 25, "generic": 15, "partial": 10},  # % of links to the money site
        # --- niche finder ---
        "search_provider": "dataforseo",  # dataforseo | brave
        "niche_footprints": ['"write for us"', '"submit a guest post"', '"become a contributor"', '"submit your story"',
                             '"add your business"', '"submit your site"', 'forum "register"', '"powered by discourse"',
                             '"powered by phpbb"', '"powered by vbulletin"', '"create a profile"', '"submit a link"'],
        "niche_searches_per_run": 40,
        "niche_pages_per_run": 120,
        "niche_min_relevance": 6,
        "niche_blocklist": [],
    },
    # Social & Community engine (Reddit + Quora answers via Telegram). Empty = Claude fills it ("Suggest targets").
    "social": {
        "brand_offer": "", "relevant": "", "looking_now": "", "persona": "", "rules": "", "link_line": "",
        "queries": [], "subreddits": [], "avoid_subreddits": [], "blocked_subreddits": [], "reject_topics": [], "pages": [],
        "quora": True, "quora_queries": [],
        "link_every_nth": 3, "max_drafts_per_scan": 5, "max_age_hours": 24,
    },
}


# Per project type: different link strategies make sense (merged under the project's own overrides).
TYPE_PRESETS: dict[str, dict] = {
    "ecommerce": {},
    "affiliate": {"quality": {"skip_categories": ["deals", "affiliate", "marketplace", "reviews"]}},
    "local": {"quality": {"skip_categories": ["affiliate", "deals", "marketplace"]}},
    "saas": {"quality": {"skip_categories": ["deals", "marketplace"]}},
}
PROJECT_TYPES = list(TYPE_PRESETS)


def project_cfg(project) -> dict:
    """Effective settings for a project: DEFAULTS <- type preset <- project overrides."""
    base = merged_settings(TYPE_PRESETS.get(getattr(project, "type", "") or "ecommerce", {}))
    return merged_settings(project.settings, base)


def merged_settings(overrides: dict | None, base: dict | None = None) -> dict:
    """Deep-merge project overrides onto DEFAULTS (dicts merge, everything else replaces)."""
    out = copy.deepcopy(base if base is not None else DEFAULTS)

    def _merge(dst: dict, src: dict) -> None:
        for k, v in (src or {}).items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = v

    _merge(out, overrides or {})
    return out
