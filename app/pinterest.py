"""Pinterest for every project, no code per brand.

build_pins(): reads the site's sitemaps (WooCommerce/Yoast, Shopify, generic), picks product and collection
pages not pinned yet, reads each page's og:image/title/description, and has Claude write pin copy and pick a
board. Pins land in Link publishing (Pins filter) for approval.

After approval a pin is posted through the Pinterest API when a 'pinterest' account (access token) is connected
under Accounts; otherwise it waits and goes into the bulk-upload CSV (Pinterest -> Create -> Bulk create Pins).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import assert_public_url
from app.config import project_cfg
from app.models import ContentItem, Project
from app.security import decrypt

UA = {"User-Agent": "Mozilla/5.0 (compatible; BuzzScoutsEngine/2.0)"}
API = "https://api.pinterest.com/v5"


def _get(url: str) -> httpx.Response | None:
    try:
        assert_public_url(url)
        r = httpx.get(url, timeout=20, follow_redirects=True, headers=UA)
        return r if r.status_code == 200 else None
    except (ValueError, httpx.HTTPError):
        return None


def site_urls(domain: str, limit: int = 400) -> list[str]:
    """Product pages first, then collection/category pages, from the sitemap tree."""
    host = domain if domain.startswith("http") else f"https://{domain}"
    queue = [f"{host}/sitemap_index.xml", f"{host}/sitemap.xml"]
    seen, products, collections = set(), [], []
    while queue and len(seen) < 12:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        r = _get(sm)
        if r is None:
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
        kids = [loc for loc in locs if loc.split("?")[0].endswith(".xml")]
        if kids:  # an index: follow product sitemaps first, then categories/collections
            rank = lambda u: 0 if "product" in u and "cat" not in u else (1 if any(k in u for k in ("collection", "category", "product_cat")) else 9)
            queue = sorted([k for k in kids if rank(k) < 9], key=rank) + queue
            continue
        is_prod = "product" in sm and "cat" not in sm
        for loc in locs:
            (products if is_prod or "/product" in loc else collections).append(loc)
        if len(products) >= limit:
            break
    out = list(dict.fromkeys(products + [c for c in collections if any(k in c for k in ("/collections/", "/product-category/"))]))
    return out[:limit]


def page_meta(url: str) -> dict | None:
    r = _get(url)
    if r is None or "html" not in r.headers.get("content-type", ""):
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    def meta(*names):
        for n in names:
            m = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if m and m.get("content"):
                return m["content"].strip()
        return ""

    image = meta("og:image", "og:image:secure_url", "twitter:image")
    if not image.startswith("http"):
        return None
    return {"url": url, "image": image, "title": meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else ""),
            "description": meta("og:description", "description")[:400]}


def build_pins(s: Session, project: Project, n: int | None = None) -> dict:
    from app import ai

    cfg = project_cfg(project)
    pc = cfg.get("pinterest", {})
    n = n or int(pc.get("pins_per_build") or 20)
    done = {(i.data or {}).get("link") or i.target_url for i in s.scalars(select(ContentItem).where(
        ContentItem.project_id == project.id, ContentItem.channel == "pinterest"))}
    metas = []
    for url in site_urls(project.domain):
        if url in done:
            continue
        m = page_meta(url)
        if m:
            metas.append(m)
        if len(metas) >= n:
            break
    if not metas:
        return {"created": 0, "reason": "no new product/collection pages with images found in the sitemap"}
    boards = list(pc.get("boards") or [])
    out = ai.pin_copy(brand=cfg["business"].get("business_name") or project.name, voice=project.brand_voice or {},
                      pages=metas, boards=boards)
    if not boards and out.get("boards"):
        project.settings = {**(project.settings or {}),
                            "pinterest": {**(project.settings or {}).get("pinterest", {}), "boards": out["boards"][:8]}}
        boards = out["boards"][:8]
    by_url = {m["url"]: m for m in metas}
    created = 0
    for pin in out.get("pins", []):
        m = by_url.get(pin.get("url"))
        if not m:
            continue
        s.add(ContentItem(project_id=project.id, channel="pinterest", content_type="pin", title=pin["title"][:100],
                          body=pin["description"][:500], target_url=m["url"],
                          data={"image": m["image"], "link": m["url"], "board": pin.get("board") or (boards[0] if boards else project.name)}))
        created += 1
    return {"created": created, "boards": boards}


# ------------------------------------------------------------------ posting
def _token(account) -> str:
    return json.loads(decrypt(account.secret) or "{}").get("password", "")


def publish(item: ContentItem, account) -> tuple[bool, str, str]:
    """Create the pin via API v5 (board created if missing). Returns (ok, message, pin_url)."""
    h = {"Authorization": f"Bearer {_token(account)}", "Content-Type": "application/json"}
    d = item.data or {}
    try:
        r = httpx.get(f"{API}/boards?page_size=100", headers=h, timeout=20)
        if r.status_code >= 300:
            return False, f"Pinterest boards {r.status_code}: {r.text[:150]}", ""
        boards = {b["name"].lower(): b["id"] for b in r.json().get("items", [])}
        bid = boards.get((d.get("board") or "").lower())
        if not bid:
            r = httpx.post(f"{API}/boards", headers=h, json={"name": d.get("board") or "Shop"}, timeout=20)
            if r.status_code >= 300:
                return False, f"Pinterest create board {r.status_code}: {r.text[:150]}", ""
            bid = r.json()["id"]
        r = httpx.post(f"{API}/pins", headers=h, timeout=30, json={
            "board_id": bid, "title": item.title[:100], "description": item.body[:500], "link": d.get("link") or item.target_url,
            "alt_text": item.title[:500], "media_source": {"source_type": "image_url", "url": d.get("image")}})
        if r.status_code >= 300:
            return False, f"Pinterest {r.status_code}: {r.text[:150]}", ""
        pid = r.json().get("id", "")
        return True, "Pinned", f"https://www.pinterest.com/pin/{pid}/" if pid else ""
    except httpx.HTTPError as e:
        return False, f"Pinterest error: {str(e)[:120]}", ""


def bulk_csv(items: list[ContentItem], per_day: int = 3) -> str:
    """Pinterest bulk-create CSV, spaced per_day pins a day starting tomorrow 10:00 UTC."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Title", "Media URL", "Pinterest board", "Thumbnail", "Description", "Link", "Publish date", "Keywords"])
    start = (datetime.now(timezone.utc) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    per_day = max(1, per_day)
    for i, it in enumerate(items):
        d = it.data or {}
        when = start + timedelta(days=i // per_day, hours=(i % per_day) * (12 // per_day))
        w.writerow([it.title[:100], d.get("image", ""), d.get("board", ""), "", it.body[:500], d.get("link") or it.target_url,
                    when.strftime("%Y-%m-%dT%H:%M:%S"), ""])
    return buf.getvalue()
