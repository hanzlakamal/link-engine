"""Analyse a published page: find EVERY link to our site on it and rate the page (0-100).

One page can carry many links to us (homepage, products, collections). We record all of them in
audit["links"] and score the page by its best link (in-content + dofollow beats a nav/footer logo link).

Criteria (weights): live page + our link present (35), dofollow (20), indexable (15),
link inside main content rather than nav/footer/sidebar (15), niche relevance (10),
real content (>= 300 words) (3), not a link farm (< 150 outbound links) (2).
No paid APIs: one HTTP fetch per page.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.auth import assert_public_url

BOILERPLATE = ("nav", "footer", "aside", "header")
BOILER_HINTS = ("menu", "navbar", "nav-", "footer", "sidebar", "site-header", "breadcrumb", "widget")
MAX_LINKS = 100


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _is_ours(host: str, our_domain: str) -> bool:
    d = our_domain.lower().removeprefix("www.")
    return host == d or host.endswith("." + d)


def _in_boilerplate(a) -> bool:
    for p in a.parents:
        if p.name in BOILERPLATE:
            return True
        if p.name in ("main", "article"):
            return False  # explicitly marked main content
        attrs = (" ".join(p.get("class") or []) + " " + (p.get("id") or "")).lower() if hasattr(p, "get") else ""
        if any(h in attrs for h in BOILER_HINTS):
            return True
    return False


def analyse(url: str, our_domain: str, relevance_terms: list[str]) -> dict:
    out = {"status": 0, "live": False, "dofollow": None, "indexable": True, "in_content": False, "anchor": "",
           "words": 0, "outbound": 0, "relevance": 0.0, "score": 0, "issues": [], "links": [], "link_count": 0,
           "dofollow_count": 0, "in_content_count": 0, "internal": False}
    try:
        assert_public_url(url)
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (compatible; BuzzScoutsEngine/2.0)"})
    except (ValueError, httpx.HTTPError) as e:
        out["issues"].append(f"fetch failed: {str(e)[:80]}")
        return out
    out["status"] = r.status_code
    if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        out["issues"].append(f"page returned {r.status_code}")
        return out
    page_host = _host(str(r.url))
    out["internal"] = _is_ours(page_host, our_domain)
    soup = BeautifulSoup(r.text, "html.parser")
    robots = " ".join(m.get("content", "") for m in soup.find_all("meta", attrs={"name": ["robots", "googlebot"]})).lower()
    if "noindex" in robots or "noindex" in r.headers.get("x-robots-tag", "").lower():
        out["indexable"] = False
        out["issues"].append("page is noindex (Google won't count it)")
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(str(r.url), a["href"].strip())
        h = _host(href)
        if not href.startswith("http"):
            continue
        if not _is_ours(h, our_domain):
            if h and h != page_host:
                out["outbound"] += 1
            continue
        if href.split("#")[0].rstrip("/") == str(r.url).split("#")[0].rstrip("/"):
            continue  # "skip to content", "cancel reply" etc. point at the page itself
        rel = [x.lower() for x in (a.get("rel") or [])]
        anchor = a.get_text(" ", strip=True)[:120]
        if not anchor and a.find("img"):
            anchor = "image: " + (a.find("img").get("alt") or "")[:100]
        key = (href.split("#")[0], anchor)
        if key in seen:
            continue
        seen.add(key)
        out["links"].append({"url": href.split("#")[0], "anchor": anchor or "(image/no text)",
                             "dofollow": not any(x in rel for x in ("nofollow", "ugc", "sponsored")),
                             "rel": "/".join(rel), "in_content": not _in_boilerplate(a)})
    links = out["links"][:MAX_LINKS]
    out["links"] = links
    out["link_count"] = len(links)
    out["dofollow_count"] = sum(1 for x in links if x["dofollow"])
    out["in_content_count"] = sum(1 for x in links if x["in_content"])
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = " ".join(soup.get_text(" ").split())
    out["words"] = len(text.split())
    low = text.lower()
    out["relevance"] = min(1.0, sum(1 for t in relevance_terms if t in low) / 3) if relevance_terms else 0.5
    if out["internal"]:
        out["issues"].append("this page is on your own site: internal links, not a backlink")
    if not links:
        out["issues"].append("our link was not found on the page")
    else:
        best = max(links, key=lambda x: (x["in_content"], x["dofollow"]))
        out["live"] = True
        out["anchor"], out["dofollow"], out["in_content"] = best["anchor"], best["dofollow"], best["in_content"]
        if not out["dofollow"]:
            out["issues"].append(f"all links are {best['rel'] or 'nofollow'} (still brand/traffic value)")
        if not out["in_content"]:
            out["issues"].append("links sit only in nav/footer/sidebar, not in the content")
    if out["words"] < 300:
        out["issues"].append(f"thin page ({out['words']} words)")
    if out["outbound"] >= 150:
        out["issues"].append(f"{out['outbound']} outbound links (link-farm signal)")
    s = 35 if out["live"] else 0
    s += 20 if out["dofollow"] else 0
    s += 15 if out["indexable"] and out["live"] else 0
    s += 15 if out["in_content"] else 0
    s += round(10 * out["relevance"]) if out["live"] else 0
    s += 3 if out["words"] >= 300 else 0
    s += 2 if out["outbound"] < 150 else 0
    out["score"] = s
    return out
