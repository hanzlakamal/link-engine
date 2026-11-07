"""Analyse a published page and rate the link we earned on it (0-100).

Criteria (weights): live page + our link present (35), dofollow (20), indexable (15),
link inside main content rather than nav/footer/sidebar (15), niche relevance (10),
real content (>= 300 words) (3), not a link farm (< 150 outbound links) (2).
No paid APIs: one HTTP fetch per page.
"""
from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

from app.auth import assert_public_url

BOILERPLATE = ("nav", "footer", "aside", "header")


def analyse(url: str, our_domain: str, relevance_terms: list[str]) -> dict:
    out = {"status": 0, "live": False, "dofollow": None, "indexable": True, "in_content": False, "anchor": "",
           "words": 0, "outbound": 0, "relevance": 0.0, "score": 0, "issues": []}
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
    soup = BeautifulSoup(r.text, "html.parser")
    robots = " ".join(m.get("content", "") for m in soup.find_all("meta", attrs={"name": ["robots", "googlebot"]})).lower()
    if "noindex" in robots or "noindex" in r.headers.get("x-robots-tag", "").lower():
        out["indexable"] = False
        out["issues"].append("page is noindex (Google won't count it)")
    ours = [a for a in soup.find_all("a", href=True) if our_domain in a["href"]]
    host = httpx.URL(str(r.url)).host
    out["outbound"] = sum(1 for a in soup.find_all("a", href=True)
                          if a["href"].startswith("http") and host not in a["href"])
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = " ".join(soup.get_text(" ").split())
    out["words"] = len(text.split())
    low = text.lower()
    out["relevance"] = min(1.0, sum(1 for t in relevance_terms if t in low) / 3) if relevance_terms else 0.5
    if not ours:
        out["issues"].append("our link was not found on the page")
    else:
        a = ours[0]
        out["live"] = True
        out["anchor"] = a.get_text(" ", strip=True)[:120]
        rel = [x.lower() for x in (a.get("rel") or [])]
        out["dofollow"] = not any(x in rel for x in ("nofollow", "ugc", "sponsored"))
        if not out["dofollow"]:
            out["issues"].append(f"link is {'/'.join(rel)} (still brand/traffic value)")
        out["in_content"] = not any(p.name in BOILERPLATE for p in a.parents)
        if not out["in_content"]:
            out["issues"].append("link sits in nav/footer/sidebar, not in the content")
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
