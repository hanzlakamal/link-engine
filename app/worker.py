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
from app.config import get_settings
from app.db import SessionLocal, engine, init_db
from app.models import ContentItem, Job, Opportunity, Project, utcnow
from app.registry import load_plugins

log = logging.getLogger("worker")
HANDLERS: dict = {}
MAX_ATTEMPTS = 3


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
    return {"keys": list(project.brand_voice)}


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
                           premium=opp.kind in ("gift_guide", "pr_request"))
    s.add(ContentItem(project_id=project.id, opportunity_id=opp.id,
                      channel="email" if opp.kind != "self_publish" else platform, content_type=ctype,
                      title=out.get("title", ""), body=out.get("body", ""),
                      data={"notes": out.get("notes_for_reviewer", "")}))
    opp.status = "in_progress"
    pipeline.event(s, project.id, f"Draft ready for approval: {opp.title}", "action")
    return {"ok": True}


# ---------------------------------------------------------------- loop
def _requeue_stale(s: Session) -> None:
    """Jobs left 'running' by a restart/redeploy get retried after 30 min."""
    cutoff = utcnow() - timedelta(minutes=30)
    for j in s.scalars(select(Job).where(Job.status == "running", Job.updated_at < cutoff)):
        j.status = "queued" if j.attempts < MAX_ATTEMPTS else "failed"
        j.error = (j.error + "\ninterrupted (worker restart)").strip()
    s.commit()


def _claim(s: Session) -> Job | None:
    _requeue_stale(s)
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
            if j.attempts < MAX_ATTEMPTS:
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
    poll = get_settings().worker_poll_seconds
    log.info("worker started; handlers=%s", sorted(HANDLERS))
    while True:
        if not run_one():
            time.sleep(poll)


if __name__ == "__main__":
    main()
