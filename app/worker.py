"""Background worker: `python -m app.worker`.

DB-backed queue (Postgres SKIP LOCKED => several workers can run safely).
Add a job type by decorating a function with @job("name").
"""
from __future__ import annotations

import logging
import time
import traceback
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import pipeline
from app.config import get_settings, project_cfg
from app.db import SessionLocal, engine, init_db
from app.models import ContentItem, EarnedLink, Job, Opportunity, PlatformAccount, Project, utcnow
from app.registry import load_plugins

log = logging.getLogger("worker")
HANDLERS: dict = {}


def job(name: str):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco


def enqueue(s: Session, type_: str, project_id: int | None = None, delay_s: int = 0, **payload) -> Job:
    j = Job(type=type_, project_id=project_id, payload=payload, run_at=utcnow() + timedelta(seconds=delay_s))
    s.add(j)
    return j


# ---------------------------------------------------------------- handlers
@job("discover_competitors")
def _discover(s, project, payload):
    return pipeline.discover_competitors(s, project)


@job("pull_backlinks")
def _pull(s, project, payload):
    return pipeline.pull_backlinks(s, project, payload.get("competitor_id"))


@job("build_opportunities")
def _build(s, project, payload):
    return pipeline.build_opportunities(s, project)


@job("reclassify")
def _reclassify(s, project, payload):
    n = pipeline.reclassify(s, project)
    return {"reclassified": n, **pipeline.build_opportunities(s, project)}


@job("full_discovery")
def _full(s, project, payload):
    r = pipeline.discover_competitors(s, project)
    if r.get("status") != "ok":
        return r
    s.flush()
    r2 = pipeline.pull_backlinks(s, project)
    s.flush()
    return {"discover": r, "pull": r2, "opps": pipeline.build_opportunities(s, project)}


@job("build_brand_voice")
def _voice(s, project, payload):
    from app import ai

    project.brand_voice = ai.build_brand_voice(project.domain)
    pipeline.event(s, project.id, "Brand voice profile drafted — review it in Settings.", "action")
    if not ((project.settings or {}).get("social") or {}).get("queries"):
        enqueue(s, "suggest_social", project.id)
    if project_cfg(project).get("pinterest", {}).get("enabled", True) and not s.scalar(
            select(ContentItem.id).where(ContentItem.project_id == project.id, ContentItem.channel == "pinterest").limit(1)):
        enqueue(s, "build_pins", project.id)  # first batch of pins for a new project
    return {"keys": list(project.brand_voice)}


def _site_pages(domain: str, limit: int = 60) -> list[str]:
    """Collection/category/landing paths from the sitemap (cheap: a few HTTP GETs, no API cost)."""
    import re as _re

    import httpx

    from app.auth import assert_public_url

    paths, seen = [], set()
    todo = [f"https://{domain}/sitemap_index.xml", f"https://{domain}/sitemap.xml"]
    while todo and len(seen) < 8:
        url = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            assert_public_url(url)
            r = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "BuzzScoutsEngine/2.0"})
        except Exception:  # noqa: BLE001
            continue
        locs = _re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text)
        for loc in locs:
            if loc.endswith(".xml"):
                if any(k in loc for k in ("category", "collection", "page", "product_cat")):
                    todo.append(loc)
            else:
                path = "/" + loc.split("://", 1)[-1].split("/", 1)[-1] if "/" in loc.split("://", 1)[-1] else "/"
                if path not in paths:
                    paths.append(path)
        if len(paths) >= limit:
            break
    return paths[:limit]


@job("build_pins")
def _build_pins(s, project, payload):
    from app import pinterest

    r = pinterest.build_pins(s, project, payload.get("n"))
    pipeline.event(s, project.id, f"Pinterest: {r['created']} new pin(s) ready for approval (Link publishing > Pins)"
                   if r["created"] else f"Pinterest: nothing new ({r.get('reason', 'all pages already pinned')})",
                   "action" if r["created"] else "info")
    return r


@job("suggest_social")
def _suggest_social(s, project, payload):
    """Claude fills the project's Social & Community settings (only empty fields), then pushes them to the engine."""
    from app import ai, social

    cfg = project_cfg(project)
    pages = _site_pages(project.domain)
    out = ai.social_targets(brand=cfg["business"].get("business_name") or project.name, domain=project.domain,
                            niche=project.niche or "", market=str(cfg.get("market", {}).get("country", "US")),
                            voice=project.brand_voice or {}, pages=pages)
    current = (project.settings or {}).get("social", {})
    merged = dict(current)
    for k, v in out.items():
        if not current.get(k) or payload.get("overwrite"):
            merged[k] = v
    project.settings = {**(project.settings or {}), "social": merged}
    res = social.push(s, project)
    pipeline.event(s, project.id, "Social targets suggested by Claude (Settings > Social & Community)"
                   + ("" if res is None else ("; pushed to the social engine" if not (res or {}).get("error")
                                              else f"; engine push failed: {res.get('error')}")), "action")
    return {"filled": [k for k in out if merged.get(k) == out[k]]}


@job("draft_for_opportunity")
def _draft(s, project, payload):
    from app import ai

    opp = s.get(Opportunity, payload["opportunity_id"])
    platform = (opp.platform or opp.kind).lower().split(" ")[0]
    ctype = (opp.data.get("content_types") or ["post"])[0] if opp.kind == "self_publish" else "outreach email"
    goal = payload.get("goal") or (
        f"Earn a genuine {ctype} presence on {opp.platform} like competitors did. Examples: {opp.data.get('examples', [])[:3]}"
        if opp.kind == "self_publish" else
        f"Pitch {opp.domain} to include {project.name} (page: {opp.url}). Reason: {opp.reason}")
    out = ai.draft_content(brand=project.name, domain=project.domain, voice=project.brand_voice,
                           platform="email" if opp.kind != "self_publish" else platform,
                           content_type=ctype, goal=goal, target_url=payload.get("target_url", ""),
                           premium=opp.kind in ("gift_guide", "pr_target", "pr_request"),
                           sender=project_cfg(project)["sender"])
    from app.models import Contact

    from app.outreach import best_contact

    contact = best_contact(s.scalars(select(Contact).where(Contact.opportunity_id == opp.id)).all())
    s.add(ContentItem(project_id=project.id, opportunity_id=opp.id, created_by=payload.get("user_id"),
                      contact_id=contact.id if contact else None,
                      channel="outreach_email" if opp.kind != "self_publish" else platform, content_type=ctype,
                      title=out.get("title", ""), body=out.get("body", ""),
                      data={"notes": out.get("notes_for_reviewer", "")}))
    opp.status = "in_progress"
    pipeline.event(s, project.id, f"Draft ready for approval: {opp.title}", "action")
    return {"ok": True}


@job("draft_article")
def _draft_article(s, project, payload):
    from app import ai

    from app.channels import HUB_PLATFORMS, hub_categories

    hub = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                   PlatformAccount.platform.in_(HUB_PLATFORMS), PlatformAccount.active.is_(True)))
    cats = hub_categories(hub) if hub else []
    out = ai.draft_content(brand=project.name, domain=project.domain, voice=project.brand_voice, platform="own_blog",
                           content_type="blog article", goal=payload["topic"], target_url=payload.get("target_url", ""),
                           premium=True, sender=project_cfg(project)["sender"], categories=cats or None)
    s.add(ContentItem(project_id=project.id, channel="own_blog", content_type="article", title=out.get("title", ""),
                      body=out.get("body", ""), target_url=payload.get("target_url", ""), created_by=payload.get("user_id"),
                      data={"notes": out.get("notes_for_reviewer", ""), "topic": payload["topic"],
                            "category": out.get("category", ""), "categories": cats}))
    pipeline.event(s, project.id, f"Blog article draft ready: {out.get('title', '')}", "action")
    return {"ok": True}


@job("publish_content")
def _publish(s, project, payload):
    """Publish an approved item via its channel API. Only runs because someone clicked Approve."""
    from app import limits
    from app.channels import HUB_PLATFORMS, get_channel

    item = s.get(ContentItem, payload["content_id"])
    if item is None or item.status not in ("approved", "scheduled"):
        return {"skipped": True}
    if item.channel in ("outreach_email", "email"):
        return HANDLERS["send_email"](s, project, payload)
    if item.channel == "pinterest":
        return _publish_pin(s, project, item, payload)
    cfg = project_cfg(project)
    ok, msg = limits.allow(s, cfg, project.id, item.channel)
    if not ok:
        item.status = "scheduled"
        pipeline.event(s, project.id, f"{msg}. '{item.title[:50]}' stays approved; click Publish again tomorrow.", "info")
        return {"deferred": msg}
    plats = HUB_PLATFORMS if item.channel == "own_blog" else (item.channel,)
    acct = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                    PlatformAccount.platform.in_(plats), PlatformAccount.active.is_(True)))
    res = get_channel(item.channel).publish(item, acct, cfg)
    if not res.ok:
        item.status = "failed"
        item.data = {**(item.data or {}), "error": res.message}
        pipeline.event(s, project.id, f"Publish failed on {item.channel}: {res.message}", "warn")
        return {"ok": False, "error": res.message}
    limits.record(s, project.id, item.channel, acct.id if acct else None)
    item.status, item.published_url = "published", res.url
    item.published_by = payload.get("user_id")
    if item.channel != "own_blog":  # own blog is the hub, not a backlink
        s.add(EarnedLink(project_id=project.id, source_url=res.url, target_url=item.target_url, kind="self_publish",
                         status="pending", content_item_id=item.id, credited_to=payload.get("user_id")))
    pipeline.event(s, project.id, f"{item.channel}: {res.message} {res.url}", "win", user_id=payload.get("user_id"))
    return {"ok": True, "url": res.url}


def _publish_pin(s, project, item, payload):
    from app import limits, pinterest

    acct = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                    PlatformAccount.platform == "pinterest", PlatformAccount.active.is_(True)))
    if acct is None:  # no API access yet: stays approved and goes into the bulk CSV
        item.data = {**(item.data or {}), "note": "Approved. Waiting for the bulk CSV (or connect a Pinterest account)."}
        return {"deferred": "no pinterest account"}
    ok, msg = limits.allow(s, project_cfg(project), project.id, "pinterest")
    if not ok:
        item.status = "scheduled"
        return {"deferred": msg}
    ok, msg, url = pinterest.publish(item, acct)
    if not ok:
        item.status, item.data = "failed", {**(item.data or {}), "error": msg}
        pipeline.event(s, project.id, msg, "warn")
        return {"ok": False, "error": msg}
    limits.record(s, project.id, "pinterest", acct.id)
    item.status, item.published_url, item.published_by = "published", url, payload.get("user_id")
    return {"ok": True, "url": url}


@job("find_contacts")
def _find_contacts(s, project, payload):
    from app import outreach

    opp = s.get(Opportunity, payload["opportunity_id"])
    n = outreach.find_contacts(s, project, opp)
    pipeline.event(s, project.id, f"Contacts for {opp.domain}: {n} found" + ("" if n else " (try adding one manually)"),
                   "action" if n else "info")
    return {"found": n}


@job("send_email")
def _send_email(s, project, payload):
    from app import limits, outreach
    from app.models import Contact

    item = s.get(ContentItem, payload["content_id"])
    if item is None or item.status not in ("approved", "scheduled"):
        return {"skipped": True}
    cfg = project_cfg(project)
    if not outreach.in_business_hours(cfg):
        item.status = "scheduled"
        pipeline.event(s, project.id, f"Outside business hours ({cfg['outreach']['timezone']}). '{item.title[:40]}' "
                       "stays approved; click Send again during business hours.", "info")
        return {"deferred": "hours"}
    ok, msg = limits.allow(s, cfg, project.id, "email", account_age_days=outreach._ramp_age_days(s, project.id))
    if not ok:
        item.status = "scheduled"
        pipeline.event(s, project.id, f"{msg} (warm-up). Email stays approved; send tomorrow.", "info")
        return {"deferred": msg}
    ok, msg, mid = outreach.send_email(s, project, item)
    if not ok:
        item.status, item.data = "failed", {**(item.data or {}), "error": msg}
        pipeline.event(s, project.id, f"Email not sent: {msg}", "warn")
        return {"ok": False, "error": msg}
    limits.record(s, project.id, "email")
    item.status, item.published_by = "published", payload.get("user_id")
    item.data = {**(item.data or {}), "message_id": mid}
    if item.opportunity_id:
        opp = s.get(Opportunity, item.opportunity_id)
        opp.status = "in_progress"
    pipeline.event(s, project.id, msg, "win", user_id=payload.get("user_id"))
    return {"ok": True}


@job("draft_followups")
def _draft_followups(s, project, payload):
    from app import ai, outreach

    n = 0
    for it in outreach.due_followups(s, project):
        out = ai.draft_content(brand=project.name, domain=project.domain, voice=project.brand_voice, platform="email",
                               content_type="short follow-up email (2-3 sentences, polite, no guilt-tripping)",
                               goal=f"Follow up on: {it.title}. Original:\n{it.body[:1500]}",
                               sender=project_cfg(project)["sender"])
        s.add(ContentItem(project_id=project.id, opportunity_id=it.opportunity_id, contact_id=it.contact_id,
                          channel="outreach_email", content_type="follow-up",
                          title=out.get("title") or ("Re: " + it.title), body=out.get("body", ""),
                          data={"step": (it.data or {}).get("step", 1) + 1}))
        it.data = {**(it.data or {}), "followed_up": True}
        n += 1
    pipeline.event(s, project.id, f"{n} follow-up drafts ready for approval.", "action" if n else "info")
    return {"drafted": n}


@job("check_inbox")
def _check_inbox(s, project, payload):
    from app import ai, outreach
    from app.models import Contact

    cfg = project_cfg(project)
    acct = s.scalar(select(PlatformAccount).where(PlatformAccount.project_id == project.id,
                    PlatformAccount.platform == "imap_inbox", PlatformAccount.active.is_(True)))
    if acct is None:
        pipeline.event(s, project.id, "No imap_inbox account connected (Accounts tab).", "action")
        return {"error": "no inbox"}
    replies = prs = 0
    sender = cfg["sender"].get("name") or project.name
    sources = cfg["outreach"]["pr_sources"]
    known = {e.lower() for e in s.scalars(select(Contact.email).where(Contact.project_id == project.id)).all()}
    done_ids = list((acct.data or {}).get("seen_ids", []))
    msgs = outreach.read_inbox(acct, lambda a: a in known or any(a.split("@")[-1].endswith(x) for x in sources),
                               skip_ids=set(done_ids))
    acct.data = {**(acct.data or {}), "seen_ids": (done_ids + [m["message_id"] for m in msgs if m["message_id"]])[-2000:]}
    for m in msgs:
        dom = m["from"].split("@")[-1]
        if any(dom.endswith(src) for src in cfg["outreach"]["pr_sources"]):
            for req in ai.extract_pr_requests(project.name, project.niche, m["body"]):
                if not req.get("relevant"):
                    continue
                key = (req.get("title") or "")[:200]
                if not s.scalar(select(Opportunity).where(Opportunity.project_id == project.id,
                                Opportunity.kind == "pr_request", Opportunity.key == key)):
                    s.add(Opportunity(project_id=project.id, kind="pr_request", key=key, title=req.get("title", ""),
                                      domain=req.get("outlet", ""), score=70, reason=req.get("summary", ""),
                                      data={**req, "source": dom}))
                    prs += 1
            continue
        c = s.scalar(select(Contact).where(Contact.project_id == project.id, Contact.email == m["from"]))
        if c is None:
            continue
        bounce = "delivery status notification" in m["subject"].lower() or "undeliverable" in m["subject"].lower()
        if bounce:
            c.status = "bounced"
            continue
        c.status = "replied"
        res = ai.classify_reply(project.name, project.domain, m["subject"], m["body"], sender)
        c.data = {**(c.data or {}), "last_reply": res.get("summary", ""), "label": res.get("label", "")}
        if res.get("label") == "link_placed" and c.opportunity_id:
            s.get(Opportunity, c.opportunity_id).status = "done"
        if res.get("draft_reply"):
            s.add(ContentItem(project_id=project.id, opportunity_id=c.opportunity_id, contact_id=c.id,
                              channel="outreach_email", content_type="reply", title="Re: " + m["subject"].removeprefix("Re: "),
                              body=res["draft_reply"], data={"notes": f"{res.get('label')}: {res.get('summary')}"}))
        replies += 1
    pipeline.event(s, project.id, f"Inbox: {replies} replies, {prs} new journalist requests.", "action" if replies or prs else "info")
    return {"replies": replies, "pr_requests": prs}


@job("check_links")
def _check_links(s, project, payload):
    """Link monitor: is each earned link still there, and is it dofollow?"""
    import httpx
    from bs4 import BeautifulSoup

    from app.auth import assert_public_url

    from app.linkaudit import analyse

    terms = project_cfg(project)["quality"]["relevance_terms"]
    q = select(EarnedLink).where(EarnedLink.project_id == project.id)
    if payload.get("link_id"):
        q = q.where(EarnedLink.id == payload["link_id"])
    if payload.get("credited_to"):
        q = q.where(EarnedLink.credited_to == payload["credited_to"])
    n = live = 0
    for el in s.scalars(q):
        n += 1
        a = analyse(el.source_url, project.domain, terms)
        el.audit, el.score, el.anchor, el.last_checked = a, a["score"], a["anchor"], utcnow()
        if a["live"]:
            live += 1
            el.status, el.dofollow = "live", a["dofollow"]
        elif el.status == "live":
            el.status = "lost"
            pipeline.event(s, project.id, f"Link lost: {el.source_url}", "warn")
        elif el.status == "pending":
            el.status = "not_found"
    pipeline.event(s, project.id, f"Link check: {live}/{n} live.", "info")
    return {"checked": n, "live": live}


@job("profile_kit")
def _profile_kit(s, project, payload):
    from app import ai

    project.brand_voice = {**(project.brand_voice or {}),
                           "profile_kit": ai.profile_kit(project.name, project.domain, project.brand_voice)}
    pipeline.event(s, project.id, "Profile kit ready (Link publishing tab).", "action")
    return {"ok": True}


# ---------------------------------------------------------------- loop
def _fail_stale(s: Session) -> None:
    """Jobs left 'running' by a restart are marked failed (never re-run automatically)."""
    cutoff = utcnow() - timedelta(minutes=30)
    for j in s.scalars(select(Job).where(Job.status == "running", Job.updated_at < cutoff)):
        j.status = "failed"
        j.error = (j.error + "\ninterrupted (worker restart) - run it again from the dashboard").strip()
    s.commit()


def _claim(s: Session) -> Job | None:
    _fail_stale(s)
    q = (select(Job).where(Job.status == "queued", Job.run_at <= utcnow())
         .order_by(Job.run_at).limit(1))
    if engine.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    j = s.scalar(q)
    if j:
        j.status, j.attempts = "running", j.attempts + 1
        s.commit()
    return j


def run_one() -> bool:
    s = SessionLocal()
    try:
        j = _claim(s)
        if not j:
            return False
        handler = HANDLERS.get(j.type)
        try:
            if handler is None:
                raise RuntimeError(f"No handler for job type {j.type}")
            project = s.get(Project, j.project_id) if j.project_id else None
            j.result = handler(s, project, j.payload or {}) or {}
            j.status, j.error = "done", ""
            s.commit()
        except Exception as e:  # noqa: BLE001
            s.rollback()
            j = s.get(Job, j.id)
            j.error = f"{e}\n{traceback.format_exc()[-2000:]}"
            if j.attempts < get_settings().job_max_attempts:
                j.status, j.run_at = "queued", utcnow() + timedelta(minutes=2 ** j.attempts)
            else:
                j.status = "failed"
                pipeline.event(s, j.project_id, f"Job {j.type} failed: {e}", "warn")
            s.commit()
            log.exception("job %s failed", j.type)
        return True
    finally:
        s.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_plugins()
    init_db()
    log.info("worker started; handlers=%s", sorted(HANDLERS))
    while True:
        if not run_one():
            time.sleep(get_settings().worker_poll_seconds)


if __name__ == "__main__":
    main()
