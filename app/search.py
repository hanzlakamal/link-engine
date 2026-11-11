"""Search helpers for the Launch Kit: Google SERPs, keyword data and free autocomplete.

Providers (settings > launch.search_provider):
  dataforseo  pay per use (~$0.002 per live SERP, keyword overview ~ $0.01 per call)
  brave       Brave Search API key (Global settings) - web results only, no volumes
Google autocomplete is free and used for long-tail expansion.
Every paid call is written to ApiUsage (provider, endpoint, USD) so the spend shows on the dashboard.
"""
from __future__ import annotations

import string
from dataclasses import dataclass, field

import httpx
from sqlalchemy.orm import Session

from app.classify import domain_of
from app.config import get_settings
from app.models import ApiUsage

DFS = "https://api.dataforseo.com/v3"


class SearchUnavailable(RuntimeError):
    pass


@dataclass
class Result:
    url: str
    title: str
    rank: int
    domain: str = ""
    snippet: str = ""


@dataclass
class KeywordInfo:
    keyword: str
    volume: int = 0
    difficulty: float | None = None
    cpc: float = 0
    intent: str = ""
    extra: dict = field(default_factory=dict)


def provider_name(cfg: dict) -> str | None:
    s = get_settings()
    want = (cfg.get("launch", {}) or {}).get("search_provider", "dataforseo")
    has = {"dataforseo": bool(s.dataforseo_login and s.dataforseo_password), "brave": bool(getattr(s, "brave_api_key", ""))}
    if has.get(want):
        return want
    return next((k for k, v in has.items() if v), None)


def _usage(s: Session | None, project_id: int | None, provider: str, endpoint: str, units: float) -> None:
    if s is not None:
        s.add(ApiUsage(project_id=project_id, provider=provider, endpoint=endpoint, units=units))


def _dfs_post(path: str, tasks: list[dict], s=None, pid=None) -> list[dict]:
    st = get_settings()
    with httpx.Client(timeout=90, auth=(st.dataforseo_login, st.dataforseo_password)) as c:
        r = c.post(DFS + path, json=tasks)
    if r.status_code >= 400:
        raise SearchUnavailable(f"DataForSEO {path} {r.status_code}: {r.text[:200]}")
    body = r.json()
    _usage(s, pid, "dataforseo", path, float(body.get("cost", 0) or 0))
    return body.get("tasks") or []


def serp(query: str, cfg: dict, s: Session | None = None, project_id: int | None = None, depth: int = 10) -> list[Result]:
    prov = provider_name(cfg)
    market = cfg.get("market", {})
    if prov == "dataforseo":
        tasks = _dfs_post("/serp/google/organic/live/regular", [{
            "keyword": query, "location_code": market.get("location_code", 2840),
            "language_code": market.get("language", "en"), "depth": depth}], s, project_id)
        items = ((tasks[0].get("result") or [{}])[0].get("items") or []) if tasks else []
        return [Result(url=i.get("url", ""), title=i.get("title", ""), rank=i.get("rank_absolute", 0),
                       domain=i.get("domain", "") or domain_of(i.get("url", "")), snippet=i.get("description", "") or "")
                for i in items if i.get("type") == "organic" and i.get("url")]
    if prov == "brave":
        with httpx.Client(timeout=30) as c:
            r = c.get("https://api.search.brave.com/res/v1/web/search",
                      params={"q": query, "count": min(depth, 20), "country": market.get("country", "us")},
                      headers={"X-Subscription-Token": get_settings().brave_api_key, "Accept": "application/json"})
        if r.status_code >= 400:
            raise SearchUnavailable(f"Brave {r.status_code}: {r.text[:200]}")
        _usage(s, project_id, "brave", "web/search", 1)
        res = (r.json().get("web") or {}).get("results") or []
        return [Result(url=x.get("url", ""), title=x.get("title", ""), rank=i + 1, domain=domain_of(x.get("url", "")),
                       snippet=x.get("description", "")) for i, x in enumerate(res)]
    raise SearchUnavailable("No search provider: add DataForSEO login/password or a Brave Search API key in Global settings.")


def keyword_overview(keywords: list[str], cfg: dict, s: Session | None = None, project_id: int | None = None) -> dict[str, KeywordInfo]:
    """Volume + difficulty for up to 700 keywords in one DataForSEO call. Empty dict if unavailable."""
    if provider_name(cfg) != "dataforseo" or not keywords:
        return {}
    market = cfg.get("market", {})
    tasks = _dfs_post("/dataforseo_labs/google/keyword_overview/live", [{
        "keywords": keywords[:700], "location_code": market.get("location_code", 2840),
        "language_code": market.get("language", "en")}], s, project_id)
    out: dict[str, KeywordInfo] = {}
    for res in (tasks[0].get("result") or []) if tasks else []:
        for it in res.get("items") or []:
            ki = it.get("keyword_info") or {}
            props = it.get("keyword_properties") or {}
            si = it.get("search_intent_info") or {}
            out[it["keyword"]] = KeywordInfo(keyword=it["keyword"], volume=int(ki.get("search_volume") or 0),
                                             difficulty=props.get("keyword_difficulty"), cpc=float(ki.get("cpc") or 0),
                                             intent=si.get("main_intent", "") or "")
    return out


def autocomplete(seed: str, expand: bool = True, limit: int = 60) -> list[str]:
    """Free Google suggestions: the seed itself plus 'seed a'..'seed z' expansions."""
    out: list[str] = []
    probes = [seed] + ([f"{seed} {c}" for c in string.ascii_lowercase] if expand else [])
    with httpx.Client(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for q in probes:
            try:
                r = c.get("https://suggestqueries.google.com/complete/search", params={"client": "firefox", "q": q})
                sug = r.json()[1] if r.status_code == 200 else []
            except (httpx.HTTPError, ValueError, IndexError):
                continue
            for x in sug:
                x = str(x).strip().lower()
                if x and x not in out:
                    out.append(x)
            if len(out) >= limit:
                break
    return out[:limit]
