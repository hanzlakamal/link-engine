"""Classify raw backlinks and score opportunities. Pure functions -> easy to test and tune."""
from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlparse

from app.catalog import EDITORIAL_HINTS, lookup


def domain_of(url: str) -> str:
    host = urlparse(url if "://" in url else "http://" + url).hostname or ""
    return host.lower().removeprefix("www.")


def root_domain(host: str) -> str:
    """Cheap root-domain guess (handles common 2-part TLDs). Good enough for grouping."""
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in {"co", "com", "org", "net", "ac", "gov"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


@dataclass
class Classification:
    platform: str
    category: str
    acquisition: str  # self_publish | outreach | pr | skip
    subtype: str = ""
    reason: str = ""


def classify(source_url: str, title: str = "", page_type: str = "", is_spam: bool = False,
             quality: dict | None = None, catalog_extra: dict | None = None) -> Classification:
    quality = quality or {}
    host = domain_of(source_url)
    hay = f"{source_url} {title}".lower()

    if quality.get("reject_spam_flag", True) and is_spam:
        return Classification("", "spam", "skip", reason="provider flagged spam")
    for tok in quality.get("spam_tokens", []):
        if tok in host:
            return Classification("", "spam", "skip", reason=f"spam token '{tok}' in domain")
    if host in set(quality.get("blocklist", [])) or root_domain(host) in set(quality.get("blocklist", [])):
        return Classification("", "blocked", "skip", reason="blocklisted")
    tld = host.rsplit(".", 1)[-1]
    if tld in set(quality.get("exclude_tlds", [])):
        return Classification("", "off_market", "skip", reason=f".{tld} site outside target market")

    hit = lookup(host, catalog_extra)
    if hit:
        _, plat = hit
        return Classification(plat.name, plat.category, plat.acquisition, plat.category, plat.notes)

    subtype = ""
    for needle, st in EDITORIAL_HINTS:
        if needle in hay:
            subtype = st
            break
    pt = (page_type or "").lower()
    if not subtype and "/forum" in pt:
        subtype = "forum"
    if subtype == "guest_post_sales":
        return Classification("", "link_seller", "skip", subtype, "sells guest posts / sponsored")
    if subtype == "forum":
        return Classification(root_domain(host), "forum", "self_publish", subtype, "niche forum: participate, link in profile/signature")
    if subtype == "deals":
        return Classification(root_domain(host), "deals", "self_publish", subtype, "coupon/deal site: submit brand + real offers")
    if subtype == "affiliate":
        return Classification(root_domain(host), "affiliate", "self_publish", subtype, "affiliate directory: list our program")
    return Classification(root_domain(host), "editorial", "outreach", subtype or "article", "")


def relevance(text: str, terms: list[str]) -> float:
    text = text.lower()
    hits = sum(1 for t in terms if t in text)
    return min(1.0, hits / 2)  # 2+ niche terms = fully relevant


def score(*, dr: float, traffic: int, competitors_count: int, total_competitors: int,
          rel: float, dofollow_share: float, weights: dict) -> float:
    """0-100. Each component normalised to 0-1, weights from project settings."""
    comps = {
        "dr": min(dr, 100) / 100,
        "traffic": min(1.0, math.log10(traffic + 1) / 6),  # 1M visits ~ 1.0
        "overlap": competitors_count / max(total_competitors, 1),
        "relevance": rel,
        "dofollow": dofollow_share,
    }
    total_w = sum(weights.values()) or 1
    return round(100 * sum(comps[k] * weights.get(k, 0) for k in comps) / total_w, 1)
