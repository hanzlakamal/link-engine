"""Ahrefs API v3. Field names verified against the v3 OpenAPI schema (2026-11)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import httpx

from app.config import get_settings
from app.providers.base import BacklinkProvider, CompetitorInfo, DomainMetrics, ProviderError, RawBacklink
from app.registry import providers

BASE = "https://api.ahrefs.com/v3"


@providers.register("ahrefs")
class AhrefsProvider(BacklinkProvider):
    @classmethod
    def configured(cls) -> bool:
        return bool(get_settings().ahrefs_api_key)

    def __init__(self, usage_cb=None, client: httpx.Client | None = None):
        super().__init__(usage_cb)
        self.client = client or httpx.Client(
            base_url=BASE, timeout=60,
            headers={"Authorization": f"Bearer {get_settings().ahrefs_api_key}", "Accept": "application/json"},
        )

    def _get(self, path: str, params: dict) -> dict:
        r = self.client.get(path, params=params)
        if r.status_code >= 400:
            raise ProviderError(f"Ahrefs {path} {r.status_code}: {r.text[:300]}")
        self._usage(path, float(r.headers.get("x-api-units-cost-total-actual", 0) or 0))
        return r.json()

    @staticmethod
    def _date() -> str:
        # yesterday: today's index is sometimes not complete yet
        return (date.today() - timedelta(days=1)).isoformat()

    def competitors(self, domain, country="us", limit=20):
        data = self._get("/site-explorer/organic-competitors", {
            "target": domain, "country": country, "date": self._date(), "mode": "subdomains",
            "select": "competitor_domain,domain_rating,traffic,keywords_common",
            "order_by": "keywords_common:desc", "limit": limit,
        })
        return [
            CompetitorInfo(c["competitor_domain"], c.get("domain_rating"), c.get("traffic"), c.get("keywords_common"))
            for c in data.get("competitors", []) if c.get("competitor_domain")
        ]

    def metrics(self, domain, country="us"):
        d = self._date()
        dr = self._get("/site-explorer/domain-rating", {"target": domain, "date": d}).get("domain_rating", {})
        stats = self._get("/site-explorer/backlinks-stats", {"target": domain, "date": d, "mode": "subdomains"}).get("metrics", {})
        m = self._get("/site-explorer/metrics", {"target": domain, "date": d, "mode": "subdomains", "country": country}).get("metrics", {})
        return DomainMetrics(
            domain=domain,
            domain_rating=dr.get("domain_rating") if isinstance(dr, dict) else dr,
            refdomains=stats.get("live_refdomains"),
            traffic=m.get("org_traffic"),
            keywords=m.get("org_keywords"),
        )

    def backlinks(self, domain, limit=300, min_dr=0, include_traffic=False):
        # Cost = rows x columns. Keep columns lean; traffic_domain alone is 10 units/row.
        cols = ["url_from", "url_to", "anchor", "title", "is_dofollow", "domain_rating_source", "root_name_source"]
        if include_traffic:
            cols.append("traffic_domain")
        where = {"and": [{"field": "is_spam", "is": ["eq", False]},
                         {"field": "domain_rating_source", "is": ["gte", min_dr]}]}
        data = self._get("/site-explorer/all-backlinks", {
            "target": domain, "mode": "subdomains", "history": "live", "aggregation": "1_per_domain",
            "limit": limit, "order_by": "domain_rating_source:desc", "select": ",".join(cols),
            "where": json.dumps(where),
        })
        out = []
        for b in data.get("backlinks", []):
            out.append(RawBacklink(
                source_url=b.get("url_from", ""),
                source_domain=(b.get("root_name_source") or "").lower(),
                target_url=b.get("url_to", ""),
                anchor=b.get("anchor") or "",
                title=b.get("title") or "",
                dofollow=bool(b.get("is_dofollow")),
                domain_rating=float(b.get("domain_rating_source") or 0),
                traffic=int(b.get("traffic_domain") or 0),
                page_type=b.get("page_type_source") or "",
                is_spam=bool(b.get("is_spam")),
                first_seen=b.get("first_seen_link") or "",
            ))
        return out
