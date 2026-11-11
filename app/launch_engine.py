"""Launch engine: parasite SEO (priority), tiered links, indexing helpers, syndication, niche finder and
the other grey-hat-lite tricks. Everything runs only when someone clicks a button (jobs in app/worker.py).

Parasite SEO flow ("Run launch autopilot"):
  1. keywords   - project keywords (Claude suggests them once) -> free Google autocomplete long-tails
  2. verify     - optional paid SERP check: keep long-tails where platform pages (Medium, LinkedIn, Reddit,
                  Blogspot...) already rank in the top 10 = proof a platform article can rank there
  3. write      - one unique article per keyword (cheap model), 1 contextual link to the best money page with
                  an anchor picked to keep the anchor mix natural, 2 links to trusted outside sources
                  (checked live; dead ones are unlinked)
  4. publish    - API platforms publish by themselves, spaced `spacing_hours` apart and within daily limits;
                  assisted platforms (Medium, LinkedIn) wait in Link publishing with Copy & open
  5. tier 2     - when a tier-1 article goes live: Bluesky / Mastodon / Telegraph pointers to it
  6. index      - an indexer page (Telegraph, + GitHub Pages hub when connected) lists every new backlink
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import pipeline
from app.classify import domain_of, root_domain
from app.config import project_cfg
from app.models import Competitor, ContentItem, EarnedLink, Opportunity, PlatformAccount, Project, utcnow

# Hosts whose pages in a top 10 mean "a platform article can rank here".
PARASITE_HOSTS = ("medium.com", "linkedin.com", "reddit.com", "quora.com", "blogspot.com", "tumblr.com", "wordpress.com",
                  "substack.com", "hashnode.dev", "hashnode.com", "dev.to", "telegra.ph", "pinterest.com", "youtube.com",
                  "facebook.com", "hubpages.com", "vocal.media", "write.as", "github.io", "sites.google.com", "notion.site",
                  "wixsite.com", "weebly.com", "issuu.com", "scribd.com", "slideshare.net", "x.com", "tiktok.com")
# Our channel -> hosts that prove it ranks.
CHANNEL_HOSTS = {"medium": ("medium.com",), "linkedin": ("linkedin.com",), "blogger": ("blogspot.com",),
                 "tumblr": ("tumblr.com",), "wordpress_com": ("wordpress.com",), "hashnode": ("hashnode.dev", "hashnode.com"),
                 "devto": ("dev.to",), "telegraph": ("telegra.ph",), "writeas": ("write.as",)}
TRUSTED_FALLBACK = ("wikipedia.org", "nih.gov", "cdc.gov", "epa.gov", "usda.gov", "britannica.com", "nytimes.com",
                    "bbc.com", "reuters.com", "smithsonianmag.com", "nationalgeographic.com", "consumerreports.org")
GENERIC_ANCHORS = ("this guide", "here", "read more", "this site", "learn more", "check this out", "more ideas here")


def _cfg(project: Project) -> dict:
    return project_cfg(project)


def _launch(project: Project) -> dict:
    return _cfg(project)["launch"]


def _brand(project: Project) -> str:
    return _cfg(project)["business"].get("business_name") or project.name


def _model(project: Project) -> str:
    return _launch(project).get("model") or ""


def _save_launch(project: Project, **values) -> None:
    st = dict(project.settings or {})
    st["launch"] = {**st.get("launch", {}), **values}
    project.settings = st


# ------------------------------------------------------------------ keywords
KEYWORD_PROMPT = """Suggest niche keywords for {brand} ({domain}). Niche: {niche}. Type: {ptype}.
Brand profile: {voice}
Return 15-25 short seed keywords (2-4 words) that real people search and that platform articles (Medium, Blogger,
LinkedIn) can rank for: problems, ideas, how-tos, gift/occasion angles, comparisons. No brand names of competitors."""


def ensure_keywords(s: Session, project: Project) -> list[str]:
    kws = list(_launch(project).get("keywords") or [])
    if kws:
        return kws
    from app import ai

    out = ai.complete_json(KEYWORD_PROMPT.format(brand=_brand(project), domain=project.domain, niche=project.niche or "(infer)",
                                                 ptype=project.type, voice=json.dumps(project.brand_voice or {})[:2000]),
                           {"keywords": "list"}, model=_model(project), max_tokens=4000)
    kws = [k.strip().lower() for k in out.get("keywords", []) if k.strip()][:25]
    _save_launch(project, keywords=kws)
    pipeline.event(s, project.id, f"Launch Kit: Claude suggested {len(kws)} niche keywords (Settings > Launch Kit).", "action")
    return kws


# ------------------------------------------------------------------ parasite keyword research
def _is_parasite_host(domain: str) -> bool:
    return any(domain == h or domain.endswith("." + h) for h in PARASITE_HOSTS)


def score_serp(results, volume: int, difficulty: float | None) -> dict:
    """How winnable a keyword is for a platform article, from its top 10."""
    top = results[:10]
    hosts = [r.domain for r in top]
    weak = [h for h in hosts if _is_parasite_host(h)]
    best = next((ch for ch, hs in CHANNEL_HOSTS.items() if any(h == x or h.endswith("." + x) for h in weak for x in hs)), "")
    kd = difficulty if difficulty is not None else 30
    vol = max(volume, 10)
    score = round(min(100.0, (len(weak) * 12 + min(vol, 2000) ** 0.5 * 2) * (1 - min(kd, 90) / 100)), 1)
    return {"weak_count": len(weak), "weak_hosts": weak[:6], "best_channel": best, "score": score, "top_hosts": hosts}


def research_keywords(s: Session, project: Project) -> dict:
    from app import search

    cfg = _cfg(project)
    lc = cfg["launch"]
    seeds = ensure_keywords(s, project)
    have = set(s.scalars(select(Opportunity.key).where(Opportunity.project_id == project.id,
                                                        Opportunity.kind == "parasite_kw")).all())
    pool: list[str] = []
    random.shuffle(seeds)
    for seed in seeds:
        for kw in search.autocomplete(seed, expand=len(pool) < lc["keyword_candidates"] // 2, limit=15):
            if kw not in have and kw not in pool and len(kw.split()) >= 3:
                pool.append(kw)
        if len(pool) >= lc["keyword_candidates"]:
            break
    pool = pool[:lc["keyword_candidates"]]
    if not pool:
        return {"added": 0, "reason": "no new long-tail keywords (add more keywords in Settings > Launch Kit)"}
    info = {}
    try:
        info = search.keyword_overview(pool, cfg, s, project.id)
    except search.SearchUnavailable as e:
        pipeline.event(s, project.id, f"Keyword volumes skipped: {e}", "info")
    # Keep keywords with some demand (unknown volume passes: autocomplete itself is a demand signal).
    cands = [k for k in pool if k not in info or (info[k].volume >= lc["min_volume"] and
                                                  (info[k].difficulty or 0) <= lc["max_difficulty"])]
    cands.sort(key=lambda k: -(info[k].volume if k in info else 0))
    checks = lc["serp_checks_per_run"] if search.provider_name(cfg) else 0
    added = 0
    for i, kw in enumerate(cands):
        ki = info.get(kw)
        vol, kd = (ki.volume if ki else 0), (ki.difficulty if ki else None)
        data = {"keyword": kw, "volume": vol, "difficulty": kd, "verified": False}
        score = 30.0 + min(vol, 1000) / 50
        if i < checks:
            try:
                res = search.serp(kw, cfg, s, project.id)
            except search.SearchUnavailable as e:
                pipeline.event(s, project.id, f"SERP checks stopped: {e}", "warn")
                checks = 0
                res = None
            if res is not None:
                sc = score_serp(res, vol, kd)
                if sc["weak_count"] == 0:
                    continue  # only strong sites rank: a platform article won't
                data.update(sc, verified=True)
                score = sc["score"] + 20
        s.add(Opportunity(project_id=project.id, kind="parasite_kw", key=kw[:255], title=kw, platform=data.get("best_channel", ""),
                          score=score, reason=("Platform pages already rank: " + ", ".join(data.get("weak_hosts", [])))
                          if data.get("verified") else "Long-tail from Google autocomplete (not SERP-checked)", data=data))
        added += 1
    return {"added": added, "candidates": len(pool), "serp_checked": min(checks, len(cands))}


# ------------------------------------------------------------------ anchors / money pages / outbound links
def pick_anchor(s: Session, project: Project, keyword: str) -> tuple[str, str]:
    """Anchor type with the biggest deficit vs the target mix -> (type, text)."""
    mix = _launch(project).get("anchor_mix") or {"brand": 50, "naked": 25, "generic": 15, "partial": 10}
    used = Counter((d or {}).get("anchor_type") for d in s.scalars(select(ContentItem.data).where(
        ContentItem.project_id == project.id, ContentItem.content_type == "parasite_article")).all())
    total = sum(used.values()) + 1
    kind = max(mix, key=lambda k: mix[k] / 100 - used.get(k, 0) / total)
    brand = _brand(project)
    text = {"brand": brand, "naked": project.domain, "generic": random.choice(GENERIC_ANCHORS),
            "partial": " ".join(keyword.split()[:4])}.get(kind, brand)
    return kind, text


def money_page(project: Project, keyword: str, pages: list[str]) -> str:
    """Best-matching site page for a keyword (word overlap with the path), else the homepage."""
    words = {w for w in re.split(r"\W+", keyword.lower()) if len(w) > 3}
    best, best_n = "/", 0
    for p in pages:
        n = len(words & {w for w in re.split(r"[\W_]+", p.lower()) if len(w) > 3})
        if n > best_n:
            best, best_n = p, n
    return f"https://{project.domain}{best if best.startswith('/') else '/' + best}"


def _alive(url: str) -> bool:
    from app.auth import assert_public_url

    try:
        assert_public_url(url)
        with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as c:
            r = c.head(url)
            if r.status_code in (405, 403, 400):
                r = c.get(url)
        return r.status_code < 400
    except Exception:  # noqa: BLE001
        return False


def clean_links(html: str, our_domain: str, money_url: str, anchor: str, max_outbound: int) -> tuple[str, list[str]]:
    """Unlink dead / excess outbound links, guarantee exactly one money link, mark outbound links rel=noopener."""
    soup = BeautifulSoup(html or "", "html.parser")
    kept, money_seen = [], False
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        host = domain_of(href) if href.startswith("http") else ""
        if not host:
            a.unwrap()
            continue
        if root_domain(host) == root_domain(our_domain):
            if money_seen:
                a.unwrap()
            else:
                money_seen = True
                a["href"] = money_url
            continue
        if len(kept) >= max_outbound or not _alive(href):
            a.unwrap()
            continue
        a["rel"] = "noopener"
        kept.append(href)
    if not money_seen:
        p = soup.new_tag("p")
        p.append("Further reading: ")
        link = soup.new_tag("a", href=money_url)
        link.string = anchor
        p.append(link)
        p.append(".")
        soup.append(p)
    return str(soup), kept


# ------------------------------------------------------------------ article writing
ARTICLE_PROMPT = """Write an original, genuinely useful article for {platform} that can rank on Google for the keyword
"{keyword}". Brand context: {brand} ({domain}). Brand voice: {voice}

Rules:
- About {words} words. Title contains the keyword naturally. Answer the search intent in the first paragraph.
- Clean HTML only: <h2>, <h3>, <p>, <ul>, <ol>, <li>, <a>, <strong>, <em>. No <h1>, no markdown, no images.
- Structure: intro, 4-7 sections with H2s, a short FAQ (3 questions, H3 each) and a conclusion.
- Write as an independent, knowledgeable author. Mention {brand} once or twice at most, where it genuinely helps.
- Exactly ONE link to {money_url} with the anchor text "{anchor}", placed inside a relevant paragraph (not the intro).
- {outbound} links to trusted, well-known outside sources (government, universities, major publications, Wikipedia)
  that support specific claims. Use only URLs you are confident exist; prefer stable homepages or top-level sections.
- No fake statistics, no fake quotes, no placeholders, no "as an AI".
Also return: meta_description (<155 chars) and 3-5 tags."""


def write_article(s: Session, project: Project, opp: Opportunity, channel: str, pages: list[str]) -> ContentItem:
    from app import ai

    lc = _launch(project)
    kw = opp.data.get("keyword") or opp.title
    anchor_type, anchor = pick_anchor(s, project, kw)
    murl = money_page(project, kw, pages)
    out = ai.complete_json(ARTICLE_PROMPT.format(
        platform=channel, keyword=kw, brand=_brand(project), domain=project.domain,
        voice=json.dumps(project.brand_voice or {"tone": ["helpful"]})[:2000], words=lc["words"], money_url=murl,
        anchor=anchor, outbound=lc["outbound_links"]),
        {"title": "str", "body": "str", "meta_description": "str", "tags": "list"}, model=_model(project), max_tokens=12000)
    body, outbound = clean_links(out.get("body", ""), project.domain, murl, anchor, lc["outbound_links"])
    item = ContentItem(project_id=project.id, opportunity_id=opp.id, channel=channel, content_type="parasite_article",
                       title=out.get("title", kw)[:300], body=body, target_url=murl, status="pending_approval",
                       data={"tier": 1, "keyword": kw, "anchor_type": anchor_type, "anchor": anchor, "outbound": outbound,
                             "tags": out.get("tags", [])[:5], "meta_description": out.get("meta_description", ""),
                             "autopilot": True, "notes": f"Parasite SEO article for '{kw}' ({anchor_type} anchor)."})
    s.add(item)
    opp.status = "in_progress"
    return item


def connected(s: Session, project: Project) -> set[str]:
    return set(s.scalars(select(PlatformAccount.platform).where(PlatformAccount.project_id == project.id,
                                                                PlatformAccount.active.is_(True))).all())


def choose_channel(s: Session, project: Project, opp: Opportunity, rotation: list[str]) -> str:
    """The platform already ranking for this keyword if we can use it, else the next usable platform."""
    from app.channels import get_channel

    plats = _launch(project)["parasite_platforms"]
    conn = connected(s, project) | {"telegraph", "writeas"}  # these two publish without any account
    usable = [p for p in plats if get_channel(p).mode != "api" or p in conn]
    best = (opp.data or {}).get("best_channel")
    if best and best in usable:
        return best
    auto = [p for p in usable if get_channel(p).mode == "api"]
    pick_from = auto or usable or ["telegraph"]
    ch = pick_from[len(rotation) % len(pick_from)]
    rotation.append(ch)
    return ch


def ensure_telegraph_account(s: Session, project: Project) -> PlatformAccount:
    from app.channels.publishers import create_telegraph_token
    from app.security import encrypt

    acct = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                                                  PlatformAccount.platform == "telegraph"))
    if acct is None:
        with httpx.Client(timeout=30) as c:
            token = create_telegraph_token(c, _brand(project))
        acct = PlatformAccount(project_id=project.id, platform="telegraph", handle=_brand(project)[:32],
                               secret=encrypt(json.dumps({"password": token})), data={"auto": True})
        s.add(acct)
        s.flush()
    return acct


def queue_publish(s: Session, project: Project, item: ContentItem, delay_s: int) -> None:
    from app.channels import get_channel
    from app.worker import enqueue

    if get_channel(item.channel).mode != "api":
        return  # assisted: stays in To approve with Copy & open
    item.status = "approved"
    enqueue(s, "publish_content", project.id, delay_s=delay_s, content_id=item.id, autopilot=True)


def write_articles(s: Session, project: Project, n: int | None = None, opp_id: int | None = None) -> dict:
    from app.worker import _site_pages

    lc = _launch(project)
    n = n or lc["articles_per_run"]
    q = select(Opportunity).where(Opportunity.project_id == project.id, Opportunity.kind == "parasite_kw")
    q = q.where(Opportunity.id == opp_id) if opp_id else q.where(Opportunity.status.in_(("new", "approved")))
    opps = s.scalars(q.order_by(Opportunity.score.desc()).limit(n)).all()
    if not opps:
        return {"written": 0}
    pages = _site_pages(project.domain)
    rotation: list[str] = []
    spacing = max(lc["spacing_hours"], 0) * 3600
    written, auto = 0, 0
    if "telegraph" in lc["parasite_platforms"]:
        try:
            ensure_telegraph_account(s, project)
        except (httpx.HTTPError, ValueError) as e:
            pipeline.event(s, project.id, f"Telegraph account could not be created: {e}", "warn")
    for o in opps:
        ch = choose_channel(s, project, o, rotation)
        item = write_article(s, project, o, ch, pages)
        s.flush()
        written += 1
        if lc["auto_publish"]:
            from app.channels import get_channel

            if get_channel(ch).mode == "api":
                queue_publish(s, project, item, delay_s=auto * spacing + random.randint(60, 900))
                auto += 1
    return {"written": written, "auto_publishing": auto, "waiting_for_you": written - auto}


# ------------------------------------------------------------------ after a publish: tier 2 + indexer
TIER2_PROMPT = """Write {n} short, natural social posts that share this article: "{title}" ({url}).
Each 1-2 sentences, a different angle (a takeaway, a question, a tip), no hashtag spam (max 1), include the URL exactly once.
Voice: {voice}"""


def after_publish(s: Session, project: Project, item: ContentItem) -> None:
    """Called by the worker after an API publish succeeds."""
    lc = _launch(project)
    data = item.data or {}
    if data.get("tier") == 1 and lc.get("tier2") and item.published_url:
        try:
            make_tier2(s, project, item)
        except Exception as e:  # noqa: BLE001  (tier 2 is a bonus; never fail the publish)
            pipeline.event(s, project.id, f"Tier-2 posts skipped: {e}", "info")


def make_tier2(s: Session, project: Project, item: ContentItem) -> int:
    from app import ai
    from app.htmlconv import to_text

    lc = _launch(project)
    conn = connected(s, project)
    chans = [c for c in lc["tier2_channels"] if c in conn or c == "telegraph"]
    chans = [c for c in chans if c != item.channel]
    if not chans:
        return 0
    social = [c for c in chans if c in ("bluesky", "mastodon")]
    posts = []
    if social:
        posts = ai.complete_json(TIER2_PROMPT.format(n=len(social), title=item.title, url=item.published_url,
                                                     voice=json.dumps((project.brand_voice or {}).get("tone", []))),
                                 {"posts": "list"}, model=_model(project), max_tokens=3000).get("posts", [])
    made = 0
    delay = 3600
    for i, ch in enumerate(chans):
        if ch == "telegraph":
            title = f"{item.title} - summary"
            summary = to_text(item.body)[:700]
            body = (f"<p>{summary}...</p><p>Read the full article: <a href=\"{item.published_url}\">{item.title}</a></p>")
        else:
            text = posts[i % len(posts)] if posts else f"{item.title} {item.published_url}"
            if item.published_url not in text:
                text = f"{text} {item.published_url}"
            title, body = item.title[:80], f"<p>{text}</p>"
        t2 = ContentItem(project_id=project.id, channel=ch, content_type="tier2_pointer", title=title, body=body,
                         target_url=item.published_url, status="pending_approval",
                         data={"tier": 2, "points_to": item.published_url, "parent_id": item.id, "autopilot": True})
        s.add(t2)
        s.flush()
        if lc["auto_publish"]:
            queue_publish(s, project, t2, delay_s=delay + random.randint(0, 1800))
            delay += 2 * 3600
        made += 1
    return made


def indexer_html(s: Session, project: Project) -> tuple[str, str, int]:
    urls: list[tuple[str, str]] = []
    seen = set()
    for it in s.scalars(select(ContentItem).where(ContentItem.project_id == project.id, ContentItem.status == "published",
                                                  ContentItem.published_url != "").order_by(ContentItem.id.desc()).limit(300)):
        if it.channel == "own_blog" or (it.data or {}).get("indexer"):
            continue
        if it.published_url not in seen:
            seen.add(it.published_url)
            urls.append((it.published_url, it.title or it.published_url))
    for el in s.scalars(select(EarnedLink).where(EarnedLink.project_id == project.id, EarnedLink.status != "lost").limit(300)):
        if el.source_url not in seen:
            seen.add(el.source_url)
            urls.append((el.source_url, domain_of(el.source_url)))
    title = f"{_brand(project)}: articles, guides and resources"
    items = "".join(f'<li><a href="{u}">{t[:120]}</a></li>' for u, t in urls)
    body = (f"<p>Everything published about {_brand(project)} and its topics, in one place. "
            f"Official site: <a href=\"https://{project.domain}/\">{project.domain}</a>.</p><ul>{items}</ul>")
    return title, body, len(urls)


def update_indexer(s: Session, project: Project) -> dict:
    """Create/refresh the Telegraph indexer page (+ GitHub Pages hub when connected)."""
    from app.channels import get_channel
    from app.channels.publishers import _creds
    from app.htmlconv import to_telegraph_nodes

    title, body, n = indexer_html(s, project)
    if n == 0:
        return {"links": 0}
    out = {"links": n}
    acct = ensure_telegraph_account(s, project)
    token = _creds(acct).get("password", "")
    path = (acct.data or {}).get("indexer_path")
    with httpx.Client(timeout=60) as c:
        r = c.post(f"https://api.telegra.ph/{'editPage/' + path if path else 'createPage'}", data={
            "access_token": token, "title": title[:256], "author_name": _brand(project)[:128],
            "content": json.dumps(to_telegraph_nodes(body))[:64000]})
        res = r.json()
    if res.get("ok"):
        acct.data = {**(acct.data or {}), "indexer_path": res["result"]["path"], "indexer_url": res["result"]["url"]}
        out["telegraph"] = res["result"]["url"]
    else:
        out["telegraph_error"] = res.get("error")
    gh = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                                                PlatformAccount.platform == "github_pages", PlatformAccount.active.is_(True)))
    if gh is not None:
        hub = ContentItem(project_id=project.id, channel="github_pages", content_type="hub_page", title=title, body=body,
                          status="approved", data={"path": "index.html", "indexer": True})
        res2 = get_channel("github_pages").publish(hub, gh, _cfg(project))
        out["github"] = res2.url if res2.ok else res2.message
    return out


def index_check(s: Session, project: Project, limit: int = 20) -> dict:
    """Paid: `site:` search per published URL not yet confirmed indexed."""
    from app import search

    cfg = _cfg(project)
    n = yes = 0
    for it in s.scalars(select(ContentItem).where(ContentItem.project_id == project.id, ContentItem.status == "published",
                                                  ContentItem.published_url != "")).all():
        d = it.data or {}
        if d.get("indexed") or it.channel == "own_blog":
            continue
        if n >= limit:
            break
        u = it.published_url.split("://", 1)[-1].rstrip("/")
        try:
            res = search.serp(f"site:{u}", cfg, s, project.id, depth=10)
        except search.SearchUnavailable as e:
            return {"error": str(e), "checked": n}
        n += 1
        hit = any(r.url.split("://", 1)[-1].rstrip("/").lower() == u.lower() for r in res)
        it.data = {**d, "indexed": hit, "index_checked": utcnow().isoformat()}
        yes += hit
    return {"checked": n, "indexed": yes}


# ------------------------------------------------------------------ syndication of own-blog posts
def syndicate(s: Session, project: Project) -> dict:
    """Repost published own-blog articles to API platforms with a canonical link back (trick #9)."""
    from app.channels import get_channel

    lc = _launch(project)
    if not lc.get("syndicate_own_blog"):
        return {"syndicated": 0}
    conn = connected(s, project) | {"writeas"}
    chans = [c for c in lc["syndicate_channels"] if c in conn and get_channel(c).mode == "api"]
    if not chans:
        return {"syndicated": 0, "reason": "connect DEV, Hashnode or Tumblr to syndicate (Write.as works without one)"}
    done = 0
    delay = 1800
    for it in s.scalars(select(ContentItem).where(ContentItem.project_id == project.id, ContentItem.channel == "own_blog",
                                                  ContentItem.status == "published", ContentItem.published_url != "")).all():
        d = it.data or {}
        targets = [c for c in chans if c not in d.get("syndicated", [])]
        for ch in targets:
            body = (it.body + f'<p><em>Originally published at <a href="{it.published_url}">{_brand(project)}</a>.</em></p>')
            syn = ContentItem(project_id=project.id, channel=ch, content_type="syndication", title=it.title, body=body,
                              target_url=it.published_url, status="pending_approval",
                              data={"tier": 1, "canonical_url": it.published_url, "parent_id": it.id, "autopilot": True,
                                    "tags": d.get("tags", [])})
            s.add(syn)
            s.flush()
            if lc["auto_publish"]:
                queue_publish(s, project, syn, delay_s=delay)
                delay += int(lc["spacing_hours"] * 3600)
            done += 1
        it.data = {**d, "syndicated": d.get("syndicated", []) + targets}
    return {"syndicated": done}


# ------------------------------------------------------------------ niche finder
NICHE_PROMPT = """You review websites found for {brand} ({domain}), niche: {niche}. Keywords: {keywords}.
For EACH site decide how relevant it is to this brand's niche and audience (0-10) and what kind of opportunity it is:
  profile (create a member/brand profile), forum (join and participate), ugc_blog (users can publish posts),
  directory (add a listing), guest_post (editorial: needs a pitch), qa (answer questions), not_relevant.
Be strict: unrelated general sites, spam, PBN-looking blogs, casino/adult/pharma and link farms are not_relevant (score 0-2).
how: one sentence on what to do there. Sites:
{sites}"""


def _page_signals(html: str) -> dict:
    low = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    gen = (soup.find("meta", attrs={"name": "generator"}) or {}).get("content", "") if soup else ""
    ext = [a for a in soup.find_all("a", href=True) if a["href"].startswith("http")]
    nf = sum(1 for a in ext if "nofollow" in " ".join(a.get("rel", []) or []).lower() or "ugc" in " ".join(a.get("rel", []) or []).lower())
    return {
        "register": any(x in low for x in ("register", "sign up", "signup", "create account", "join now")),
        "write_for_us": any(x in low for x in ("write for us", "guest post", "contribute", "submit your story", "submit an article")),
        "submit": any(x in low for x in ("submit your", "add your business", "add listing", "submit a link", "add your site")),
        "comments": bool(soup.find("textarea", attrs={"name": re.compile("comment", re.I)})),
        "forum": any(x in (gen + low[:20000]) for x in ("discourse", "phpbb", "vbulletin", "xenforo", "invision", "flarum")),
        "generator": gen[:60],
        "nofollow_ratio": round(nf / len(ext), 2) if ext else None,
        "title": (soup.title.string.strip()[:120] if soup.title and soup.title.string else ""),
    }


def _fetch(url: str) -> str:
    from app.auth import assert_public_url

    try:
        assert_public_url(url)
        with httpx.Client(timeout=12, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; BuzzScoutsEngine/2.0)"}) as c:
            r = c.get(url)
        if r.status_code < 400 and "html" in r.headers.get("content-type", ""):
            return r.text[:400_000]
    except Exception:  # noqa: BLE001
        pass
    return ""


def niche_finder(s: Session, project: Project) -> dict:
    from app import ai, search
    from app.catalog import lookup
    from app.launchkit import BY_DOMAIN

    cfg = _cfg(project)
    lc = cfg["launch"]
    if not search.provider_name(cfg):
        return {"error": "Add DataForSEO or a Brave Search API key in Global settings to run the niche finder."}
    kws = ensure_keywords(s, project)
    queries = [f"{k} {fp}" for k in kws for fp in lc["niche_footprints"]]
    random.shuffle(queries)
    queries = queries[:lc["niche_searches_per_run"]]
    block = set(lc.get("niche_blocklist") or []) | set(cfg["quality"].get("blocklist") or [])
    known = set(s.scalars(select(Opportunity.domain).where(Opportunity.project_id == project.id)).all())
    comps = {root_domain(d) for d in s.scalars(select(Competitor.domain).where(Competitor.project_id == project.id)).all()}
    spam = cfg["quality"]["spam_tokens"]
    found: dict[str, dict] = {}
    for q in queries:
        try:
            res = search.serp(q, cfg, s, project.id)
        except search.SearchUnavailable as e:
            pipeline.event(s, project.id, f"Niche finder stopped searching: {e}", "warn")
            break
        for r in res:
            rd = root_domain(r.domain or domain_of(r.url))
            if (not rd or rd in found or rd in block or rd in known or rd in comps or rd == root_domain(project.domain)
                    or rd in BY_DOMAIN or any(t in rd for t in spam) or _is_parasite_host(rd)):
                continue
            hit = lookup(rd)
            if hit and hit[1].acquisition == "skip":
                continue
            found[rd] = {"domain": rd, "url": r.url, "title": r.title, "snippet": r.snippet[:200], "query": q}
        if len(found) >= lc["niche_pages_per_run"]:
            break
    sites = list(found.values())[:lc["niche_pages_per_run"]]
    for st in sites:
        st["signals"] = _page_signals(_fetch(st["url"]) or "<html></html>")
    added = 0
    for i in range(0, len(sites), 15):
        batch = sites[i:i + 15]
        listing = "\n".join(f"- {b['domain']} | {b['title']} | {b['snippet']} | signals: "
                            f"{json.dumps({k: v for k, v in b['signals'].items() if v})}" for b in batch)
        out = ai.complete_json(NICHE_PROMPT.format(brand=_brand(project), domain=project.domain, niche=project.niche or "",
                                                   keywords=", ".join(kws[:15]), sites=listing),
                               {"sites": {"domain": "str", "relevance": "str", "type": "str", "how": "str"}},
                               model=_model(project), max_tokens=8000)
        by = {b["domain"]: b for b in batch}
        for v in out.get("sites", []):
            b = by.get(v.get("domain", "").lower().strip())
            try:
                rel = float(v.get("relevance", 0))
            except ValueError:
                rel = 0
            if not b or v.get("type") == "not_relevant" or rel < lc["niche_min_relevance"]:
                continue
            sig = b["signals"]
            link = "unknown" if sig.get("nofollow_ratio") is None else ("mostly nofollow" if sig["nofollow_ratio"] > 0.6 else "some dofollow")
            s.add(Opportunity(project_id=project.id, kind="niche_site", key=b["domain"], title=sig.get("title") or b["title"] or b["domain"],
                              domain=b["domain"], url=b["url"], platform=b["domain"], score=rel * 10,
                              reason=v.get("how", ""), data={"tier": "niche", "type": v.get("type"), "relevance": rel,
                                                             "signals": sig, "query": b["query"], "link": link,
                                                             "category": "niche"}))
            added += 1
    return {"searched": len(queries), "sites_checked": len(sites), "added": added}


# ------------------------------------------------------------------ trick assets (drafts)
ASSETS = {
    "google_stack": ("Google stacking pack", "docs", "Google Doc + Slides outline + My Maps description + Google Site page that "
                     "all link to each other, to our tier-1 articles and to the site"),
    "video": ("Video pack (YouTube, Vimeo, Dailymotion, Rumble)", "video", "a 60-90s video script plus a different title, "
              "description (with links) and tags for each of the 4 video sites"),
    "pdf": ("PDF lookbook / guide", "docs", "a printable guide or lookbook (HTML that prints to PDF) with links inside, for Issuu, "
            "Scribd, Calameo and Yumpu, plus a short description for each upload"),
    "minisite": ("Mini-site (3-5 pages)", "github_pages", "a 4-page mini-site (home, guide, FAQ, resources) with unique "
                 "content that links to our tier-1 articles and money pages"),
    "gbp": ("Google Business Profile posts", "gbp", "5 Google Business Profile updates (offers, tips, new products) plus a My "
            "Maps pin description"),
    "podcast": ("Podcast episode scripts", "podcast", "3 short podcast episode scripts (5 min) turned from our articles, with "
                "show notes that include links, for Spotify for Podcasters (needs a text-to-speech or a real voice)"),
    "forum_signature": ("Forum signatures + bios", "forum_signature", "5 short forum signatures and member bios (plain, "
                        "non-spammy, one link) for niche forums where we genuinely participate"),
    "press_release": ("Press release", "pr", "a newsworthy press release (launch, milestone, data or charity angle) for "
                      "PRLog / OpenPR, with 2 links"),
}
ASSET_PROMPT = """Create {what} for {brand} ({domain}). Niche: {niche}. Keywords to use naturally: {keywords}.
Brand voice: {voice}
Tier-1 articles already live (link to some of them where it fits): {articles}
Money pages: {pages}
Return pieces: each with title, body (clean HTML: <h2>,<p>,<ul>,<li>,<a>,<strong>) and where (which site it goes on).
No placeholders, no fake facts."""


def draft_asset(s: Session, project: Project, asset: str) -> dict:
    from app import ai
    from app.worker import _site_pages

    if asset == "widget":
        return {"created": 0, "snippet": widget_snippet(project)}
    if asset not in ASSETS:
        raise ValueError(f"Unknown asset {asset}")
    label, channel, what = ASSETS[asset]
    arts = [f"{t} ({u})" for t, u in s.execute(select(ContentItem.title, ContentItem.published_url).where(
        ContentItem.project_id == project.id, ContentItem.status == "published",
        ContentItem.content_type.in_(("parasite_article", "syndication")))).all()][:12]
    pages = [f"https://{project.domain}{p}" for p in _site_pages(project.domain, 20)][:12]
    out = ai.complete_json(ASSET_PROMPT.format(what=what, brand=_brand(project), domain=project.domain, niche=project.niche or "",
                                               keywords=", ".join((_launch(project).get("keywords") or [])[:10]),
                                               voice=json.dumps(project.brand_voice or {})[:1500],
                                               articles="; ".join(arts) or "(none yet)", pages=", ".join(pages) or f"https://{project.domain}/"),
                           {"pieces": {"title": "str", "body": "str", "where": "str"}}, model=_model(project), max_tokens=12000)
    gh = channel == "github_pages" and "github_pages" in connected(s, project)
    ch = channel if channel != "github_pages" or gh else "launch_site"
    n = 0
    for i, pc in enumerate(out.get("pieces", [])):
        data = {"asset": asset, "where": pc.get("where", ""), "notes": f"{label}: post on {pc.get('where', '')}"}
        if gh:
            data["path"] = "index.html" if i == 0 else re.sub(r"[^a-z0-9]+", "-", pc.get("title", "page").lower()).strip("-")[:50] + ".html"
            data["tier"] = 2
        it = ContentItem(project_id=project.id, channel=ch, content_type=f"asset_{asset}", title=pc.get("title", label)[:300],
                         body=pc.get("body", ""), target_url=f"https://{project.domain}/", status="pending_approval", data=data)
        s.add(it)
        n += 1
    return {"created": n, "channel": ch}


def widget_snippet(project: Project) -> str:
    brand = _brand(project).replace('"', "")
    return (f'<a href="https://{project.domain}/" title="{brand}" rel="nofollow" target="_blank" '
            f'style="display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border:1px solid #ddd;border-radius:8px;'
            f'font:13px system-ui,sans-serif;color:#222;text-decoration:none">Featured on <strong>{brand}</strong></a>')


def same_as(s: Session, project: Project) -> dict:
    """Organization JSON-LD with sameAs = every live profile URL we know (trick #4)."""
    cfg = _cfg(project)
    urls: list[str] = []
    for k in ("facebook", "instagram", "pinterest", "tiktok", "linkedin", "x", "youtube"):
        v = cfg["business"].get(k)
        if v and v.startswith("http"):
            urls.append(v)
    for o in s.scalars(select(Opportunity).where(Opportunity.project_id == project.id,
                                                 Opportunity.kind.in_(("launch_site", "niche_site")),
                                                 Opportunity.status == "done")):
        u = (o.data or {}).get("profile_url")
        if u:
            urls.append(u)
    urls = list(dict.fromkeys(urls))
    return {"@context": "https://schema.org", "@type": "Organization", "name": _brand(project),
            "url": f"https://{project.domain}/", "sameAs": urls}


# ------------------------------------------------------------------ the one-button run
def autopilot(s: Session, project: Project) -> dict:
    from app.launchkit import seed

    out: dict = {"launch_sites_added": seed(s, project)}
    s.flush()
    lc = _launch(project)
    unused = s.scalar(select(Opportunity.id).where(Opportunity.project_id == project.id, Opportunity.kind == "parasite_kw",
                                                   Opportunity.status.in_(("new", "approved"))).limit(1))
    pending = len(s.scalars(select(Opportunity.id).where(Opportunity.project_id == project.id, Opportunity.kind == "parasite_kw",
                                                         Opportunity.status.in_(("new", "approved")))).all())
    if not unused or pending < lc["articles_per_run"]:
        out["keywords"] = research_keywords(s, project)
        s.flush()
    out["articles"] = write_articles(s, project)
    out["syndication"] = syndicate(s, project)
    from app.worker import enqueue

    if lc.get("indexer_page"):  # refresh after the spaced publishes have had time to run
        enqueue(s, "launch_indexer", project.id,
                delay_s=int((out["articles"].get("auto_publishing", 0) + 1) * lc["spacing_hours"] * 3600) + 1800)
    a = out["articles"]
    pipeline.event(s, project.id, f"Launch autopilot: {a.get('written', 0)} parasite article(s) written, "
                   f"{a.get('auto_publishing', 0)} publishing automatically over the next "
                   f"{int(a.get('auto_publishing', 0) * lc['spacing_hours'])}h, {a.get('waiting_for_you', 0)} waiting in "
                   f"Link publishing (Medium/LinkedIn).", "win" if a.get("written") else "info")
    return out


def due_retry(item: ContentItem, project: Project) -> bool:
    return bool((item.data or {}).get("autopilot")) and bool(_launch(project).get("retry_next_day", True))

