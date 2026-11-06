"""DataForSEO (pay-per-use). Backlinks API + Labs competitors."""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.providers.base import BacklinkProvider, CompetitorInfo, DomainMetrics, ProviderError, RawBacklink
from app.registry import providers

BASE = "https://api.dataforseo.com/v3"
LOCATION = {"us": 2840, "gb": 2826, "ca": 2124, "au": 2036}


@providers.register("dataforseo")
class DataForSEOProvider(BacklinkProvider):
    @classmethod
    def configured(cls) -> bool:
        s = get_settings()
        return bool(s.dataforseo_login and s.dataforseo_password)

    def __init__(self, usage_cb=None, client: httpx.Client | None = None):
        super().__init__(usage_cb)
        s = get_settings()
        self.client = client or httpx.Client(base_url=BASE, timeout=90, auth=(s.dataforseo_login, s.dataforseo_password))

    def _post(self, path: str, task: dict) -> list[dict]:
        r = self.client.post(path, json=[task])
        if r.status_code >= 400:
            raise ProviderError(f"DataForSEO {path} {r.status_code}: {r.text[:300]}")
        body = r.json()
        self._usage(path, float(body.get("cost", 0) or 0))
        tasks = body.get("tasks") or []
        if not tasks or tasks[0].get("status_code") not in (20000,):
            msg = tasks[0].get("status_message") if tasks else body.get("status_message")
            raise ProviderError(f"DataForSEO {path}: {msg}")
        return tasks[0].get("result") or []

    def competitors(self, domain, country="us", limit=20):
        res = self._post("/dataforseo_labs/google/competitors_domain/live", {
            "target": domain, "location_code": LOCATION.get(country, 2840), "language_code": "en",
            "limit": limit, "exclude_top_domains": True,
        })
        items = (res[0].get("items") if res else None) or []
        out = []
        for it in items:
            org = (it.get("metrics") or {}).get("organic") or {}
            out.append(CompetitorInfo(it.get("domain", ""), None, int(org.get("etv") or 0), it.get("intersections")))
        return [c for c in out if c.domain and c.domain != domain]

    def metrics(self, domain, country="us"):
        res = self._post("/backlinks/summary/live", {"target": domain, "include_subdomains": True})
        r = res[0] if res else {}
        # DataForSEO rank is 0-1000; scale to a DR-like 0-100 for consistent scoring.
        rank = r.get("rank")
        return DomainMetrics(domain, (rank / 10) if rank is not None else None, r.get("referring_domains"), None, None)

    def backlinks(self, domain, limit=1000):
        res = self._post("/backlinks/backlinks/live", {
            "target": domain, "mode": "one_per_domain", "limit": min(limit, 1000),
            "include_subdomains": True, "order_by": ["domain_from_rank,desc"],
            "filters": ["is_lost", "=", False],
        })
        items = (res[0].get("items") if res else None) or []
        return [
            RawBacklink(
                source_url=i.get("url_from", ""),
                source_domain=(i.get("domain_from") or "").lower().removeprefix("www."),
                target_url=i.get("url_to", ""),
                anchor=i.get("anchor") or "",
                title=i.get("page_from_title") or "",
                dofollow=bool(i.get("dofollow")),
                domain_rating=float(i.get("domain_from_rank") or 0) / 10,
                traffic=0,
                page_type="",
                is_spam=(i.get("backlink_spam_score") or 0) >= 60,
                first_seen=i.get("first_seen") or "",
            )
            for i in items
        ]
