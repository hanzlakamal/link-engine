"""Social & Community module: talks to the brand's social engine (social_engine/ service).

The dashboard is the source of truth for each project's social settings (Settings -> Social & Community).
They are pushed to the engine on save, on connect, and before every scan, so a new brand needs no code.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth as authz
from app.config import project_cfg
from app.models import PlatformAccount, Project
from app.security import decrypt


def engine_account(db: Session, pid: int) -> PlatformAccount | None:
    return db.scalar(select(PlatformAccount).where(PlatformAccount.project_id == pid,
                     PlatformAccount.platform == "social_engine", PlatformAccount.active.is_(True)))


def call(acct: PlatformAccount, method: str, path: str, payload: dict | None = None) -> dict:
    import httpx

    base = (acct.data or {}).get("site_url", "").rstrip("/")
    try:
        u = urlparse(base)
        # Railway private network (same project, never public) is allowed; everything else must be public.
        if not (u.scheme == "http" and (u.hostname or "").endswith(".railway.internal")):
            authz.assert_public_url(base)
        token = json.loads(decrypt(acct.secret) or "{}").get("password", "")
        r = httpx.request(method, base + path, headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=15)
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"error": r.status_code}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:120]}


def engine_config(project: Project) -> dict:
    """Map the project's social settings to the engine's config keys (empty values keep the engine default)."""
    sc = project_cfg(project).get("social", {})
    biz = project_cfg(project).get("business", {})
    brand = {k: v for k, v in {
        "name": biz.get("business_name") or project.name,
        "offer": sc.get("brand_offer"), "relevant": sc.get("relevant"), "live_problem": sc.get("looking_now"),
        "persona": sc.get("persona"), "rules": sc.get("rules"), "link_line": sc.get("link_line"),
    }.items() if v}
    return {
        "site": f"https://{project.domain}" if not project.domain.startswith("http") else project.domain,
        "brand": brand,
        "queries": sc.get("queries") or [], "subreddits": sc.get("subreddits") or [],
        "avoidSubreddits": sc.get("avoid_subreddits") or [], "blockedSubreddits": sc.get("blocked_subreddits") or [], "rejectTopics": sc.get("reject_topics") or [],
        "pages": [{"url": p if p.startswith("/") else "/" + p, "about": ""} for p in (sc.get("pages") or [])],
        "quora": bool(sc.get("quora", True)), "quoraQueries": sc.get("quora_queries") or [],
        "linkEveryNth": int(sc.get("link_every_nth") or 3), "maxDraftsPerScan": int(sc.get("max_drafts_per_scan") or 5),
        "maxAgeHours": int(sc.get("max_age_hours") or 24),
        **_quora_creds(),
    }


def _quora_creds() -> dict:
    """Quora search runs through the dashboard's DataForSEO account (Global settings), sent over the private network."""
    from app.config import get_settings

    st = get_settings()
    return {"dataforseo": {"login": st.dataforseo_login, "password": st.dataforseo_password}} if st.dataforseo_login else {}


def _host(url: str) -> str:
    return (urlparse(url if "://" in url else "https://" + url).hostname or "").lower().removeprefix("www.")


def import_from_engine(db: Session, project: Project) -> bool:
    """If the engine is already set up for this project's site (e.g. a migrated bot), copy its settings into the
    dashboard so nothing hand-tuned is lost. Returns True when imported."""
    acct = engine_account(db, project.id)
    conf = call(acct, "GET", "/api/config") if acct else {}
    if not conf or conf.get("error") or _host(conf.get("site", "")) != _host(project.domain) or not conf.get("queries"):
        return False
    b = conf.get("brand") or {}
    project.settings = {**(project.settings or {}), "social": {
        **((project.settings or {}).get("social") or {}),
        "brand_offer": b.get("offer", ""), "relevant": b.get("relevant", ""), "looking_now": b.get("live_problem", ""),
        "persona": b.get("persona", ""), "rules": b.get("rules", ""), "link_line": b.get("link_line", ""),
        "queries": conf.get("queries") or [], "subreddits": conf.get("subreddits") or [],
        "avoid_subreddits": conf.get("avoidSubreddits") or [], "reject_topics": conf.get("rejectTopics") or [],
        "pages": [p["url"] if isinstance(p, dict) else p for p in conf.get("pages") or []],
        "quora": bool(conf.get("quora")), "quora_queries": conf.get("quoraQueries") or [],
        "link_every_nth": conf.get("linkEveryNth", 3), "max_drafts_per_scan": conf.get("maxDraftsPerScan", 5),
        "max_age_hours": conf.get("maxAgeHours", 24)}}
    return True


def push(db: Session, project: Project) -> dict | None:
    acct = engine_account(db, project.id)
    return call(acct, "POST", "/api/config", engine_config(project)) if acct else None
