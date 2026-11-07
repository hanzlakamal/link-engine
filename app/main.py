"""Web app: `uvicorn app.main:app`. Server-rendered (Jinja) for v1.

TODO(upgrade): JSON API under /api is already the source of truth for the views; a React
dashboard or client portal can be added on top without touching the backend.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from collections import Counter
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import pipeline
from app.channels import get_channel
from app.classify import domain_of
from app.config import DEFAULTS, PLAIN_KEYS, SECRET_KEYS, get_settings, invalidate_settings, merged_settings
from app.db import get_db, init_db
from app.models import (ApiUsage, AppSetting, Competitor, ContentItem, EarnedLink, Event, Job, Opportunity, Project, Task,
                        utcnow)
from app.registry import load_plugins, playbooks, providers, strategies
from app.security import encrypt
from app.web import forms
from app.worker import enqueue

load_plugins()


@asynccontextmanager
async def lifespan(_app):
    init_db()
    yield


app = FastAPI(title="Link Engine", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))
templates.env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, default=str)
COOKIE = "le_auth"


# ------------------------------------------------------------------ auth (v1: single admin)
def _token() -> str:
    s = get_settings()
    return hmac.new(s.secret_key.encode(), s.admin_password.encode(), hashlib.sha256).hexdigest()


@app.middleware("http")
async def auth(request: Request, call_next):
    open_paths = ("/login", "/healthz", "/static")
    if not request.url.path.startswith(open_paths) and request.cookies.get(COOKIE) != _token():
        if request.url.path.startswith("/api"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@app.post("/login")
def login(password: str = Form(...)):
    if not hmac.compare_digest(password, get_settings().admin_password):
        return RedirectResponse("/login?error=1", status_code=303)
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(COOKIE, _token(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return r


@app.get("/logout")
def logout():
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(COOKIE)
    return r


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ------------------------------------------------------------------ helpers
def _project(db: Session, pid: int) -> Project:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "project not found")
    return p


def funnel(db: Session, pid: int) -> dict:
    opp = Counter(dict(db.execute(select(Opportunity.status, func.count()).where(
        Opportunity.project_id == pid).group_by(Opportunity.status)).all()))
    content = Counter(dict(db.execute(select(ContentItem.status, func.count()).where(
        ContentItem.project_id == pid).group_by(ContentItem.status)).all()))
    live = db.scalar(select(func.count()).select_from(EarnedLink).where(
        EarnedLink.project_id == pid, EarnedLink.status == "live")) or 0
    return {
        "found": sum(opp.values()),
        "approved": opp["approved"] + opp["in_progress"] + opp["done"],
        "awaiting_approval": content["pending_approval"],
        "published": content["published"],
        "live_links": live,
    }


def _back(pid: int, tab: str = "") -> RedirectResponse:
    return RedirectResponse(f"/p/{pid}{('/' + tab) if tab else ''}", status_code=303)


# ------------------------------------------------------------------ pages
@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    projects = db.scalars(select(Project).order_by(Project.created_at)).all()
    rows = [{"p": p, "f": funnel(db, p.id),
             "todo": db.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id, Task.status == "todo")) or 0}
            for p in projects]
    events = db.scalars(select(Event).order_by(Event.created_at.desc()).limit(15)).all()
    configured = {n: cls.configured() for n, cls in providers.items()}
    return templates.TemplateResponse(request, "home.html", {
        "rows": rows, "events": events, "configured": configured,
        "ai": bool(get_settings().anthropic_api_key), "names": {p.id: p.name for p in projects}})


@app.post("/projects")
def create_project(name: str = Form(...), domain: str = Form(...), stage: str = Form("launch"),
                   niche: str = Form(""), client: str = Form(""), competitors: str = Form(""),
                   seed_keywords: str = Form(""), db: Session = Depends(get_db)):
    p = Project(name=name.strip(), domain=domain_of(domain), stage=stage, niche=niche, client=client,
                settings={"discovery": {"seed_keywords": [k.strip() for k in seed_keywords.split(",") if k.strip()]}})
    db.add(p)
    db.flush()
    for c in competitors.replace("\n", ",").split(","):
        if c.strip():
            db.add(Competitor(project_id=p.id, domain=domain_of(c), source="manual", confirmed=True))
    db.add(Event(project_id=p.id, message=f"Project created: {p.name} ({p.domain})"))
    db.commit()
    return _back(p.id)


@app.get("/p/{pid}", response_class=HTMLResponse)
def project_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    top = db.scalars(select(Opportunity).where(Opportunity.project_id == pid, Opportunity.status.in_(("new", "approved")))
                     .order_by(Opportunity.score.desc()).limit(10)).all()
    tasks = db.scalars(select(Task).where(Task.project_id == pid, Task.status != "done")
                       .order_by(Task.day, Task.id).limit(12)).all()
    events = db.scalars(select(Event).where(Event.project_id == pid).order_by(Event.created_at.desc()).limit(12)).all()
    jobs = db.scalars(select(Job).where(Job.project_id == pid).order_by(Job.created_at.desc()).limit(6)).all()
    by_acq = dict(db.execute(select(Opportunity.kind, func.count()).where(Opportunity.project_id == pid)
                             .group_by(Opportunity.kind)).all())
    usage = db.scalar(select(func.coalesce(func.sum(ApiUsage.units), 0)).where(ApiUsage.project_id == pid))
    return templates.TemplateResponse(request, "project.html", {
        "p": p, "f": funnel(db, pid), "top": top, "tasks": tasks, "events": events, "jobs": jobs,
        "by_kind": by_acq, "usage": usage, "playbooks": playbooks.items(),
        "strategies": [(n, c) for n, c in strategies.items()], "tab": "overview"})


@app.post("/p/{pid}/competitors")
def add_competitor(pid: int, domain: str = Form(...), db: Session = Depends(get_db)):
    p = _project(db, pid)
    d = domain_of(domain)
    if d and d != p.domain and not db.scalar(select(Competitor).where(Competitor.project_id == pid, Competitor.domain == d)):
        db.add(Competitor(project_id=pid, domain=d, source="manual", confirmed=True))
        p.needs_input = ""
        db.commit()
    return _back(pid, "competitors")


@app.post("/p/{pid}/competitors/{cid}/toggle")
def toggle_competitor(pid: int, cid: int, db: Session = Depends(get_db)):
    c = db.get(Competitor, cid)
    if c and c.project_id == pid:
        c.confirmed = not c.confirmed
        db.commit()
    return _back(pid, "competitors")


@app.get("/p/{pid}/competitors", response_class=HTMLResponse)
def competitors_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    return templates.TemplateResponse(request, "competitors.html", {"p": p, "tab": "competitors"})


@app.post("/p/{pid}/import")
async def import_csv(pid: int, file: UploadFile = File(...), competitor: str = Form(""), db: Session = Depends(get_db)):
    """Upload an Ahrefs/DataForSEO backlink export. Leave competitor empty for links to our own site."""
    p = _project(db, pid)
    text = (await file.read()).decode("utf-8", errors="replace")
    pipeline.import_backlinks_csv(db, p, text, competitor.strip() or None, source="csv")
    db.flush()
    pipeline.build_opportunities(db, p)
    db.commit()
    return _back(pid, "opportunities")


@app.get("/p/{pid}/disavow.txt", response_class=PlainTextResponse)
def disavow(pid: int, db: Session = Depends(get_db)):
    return pipeline.disavow_file(db, _project(db, pid))


@app.post("/p/{pid}/jobs/{jtype}")
def run_job(pid: int, jtype: str, db: Session = Depends(get_db)):
    _project(db, pid)
    enqueue(db, jtype, pid)
    db.commit()
    return _back(pid)


@app.post("/p/{pid}/playbooks/{name}")
def apply_playbook(pid: int, name: str, start: str = Form(""), db: Session = Depends(get_db)):
    p = _project(db, pid)
    n = playbooks.get(name)().apply(db, p, date.fromisoformat(start) if start else None)
    db.add(Event(project_id=pid, level="info", message=f"Playbook '{name}' applied: {n} tasks"))
    db.commit()
    return _back(pid, "tasks")


@app.get("/p/{pid}/opportunities", response_class=HTMLResponse)
def opportunities_page(pid: int, request: Request, kind: str = "", status: str = "new", db: Session = Depends(get_db)):
    p = _project(db, pid)
    q = select(Opportunity).where(Opportunity.project_id == pid)
    if kind:
        q = q.where(Opportunity.kind == kind)
    if status:
        q = q.where(Opportunity.status == status)
    opps = db.scalars(q.order_by(Opportunity.score.desc()).limit(300)).all()
    kinds = db.scalars(select(Opportunity.kind).where(Opportunity.project_id == pid).distinct()).all()
    return templates.TemplateResponse(request, "opportunities.html", {
        "p": p, "opps": opps, "kinds": kinds, "kind": kind, "status": status, "tab": "opportunities"})


@app.post("/p/{pid}/opportunities/{oid}")
def opportunity_action(pid: int, oid: int, action: str = Form(...), db: Session = Depends(get_db)):
    o = db.get(Opportunity, oid)
    if not o or o.project_id != pid:
        raise HTTPException(404)
    if action == "draft":
        o.status = "approved"
        enqueue(db, "draft_for_opportunity", pid, opportunity_id=oid)
    elif action in ("approved", "rejected", "snoozed", "done", "new"):
        o.status = action
    db.commit()
    return RedirectResponse(f"/p/{pid}/opportunities", status_code=303)


@app.get("/p/{pid}/queue", response_class=HTMLResponse)
def queue_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    items = db.scalars(select(ContentItem).where(ContentItem.project_id == pid,
                       ContentItem.status.in_(("pending_approval", "approved", "scheduled")))
                       .order_by(ContentItem.created_at.desc())).all()
    return templates.TemplateResponse(request, "queue.html", {
        "p": p, "items": items, "compose": {i.id: get_channel(i.channel).compose_url() for i in items}, "tab": "queue"})


@app.post("/p/{pid}/content/{cid}")
def content_action(pid: int, cid: int, action: str = Form(...), title: str = Form(""), body: str = Form(""),
                   published_url: str = Form(""), db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    if not c or c.project_id != pid:
        raise HTTPException(404)
    if action == "save":
        c.title, c.body = title, body
    elif action == "approve":
        c.title, c.body, c.status = title or c.title, body or c.body, "approved"
    elif action == "reject":
        c.status = "rejected"
    elif action == "published" and published_url:
        c.status, c.published_url = "published", published_url
        db.add(EarnedLink(project_id=pid, source_url=published_url, target_url=c.target_url,
                          kind="self_publish" if c.channel != "email" else "outreach", status="pending",
                          content_item_id=c.id))
        db.add(Event(project_id=pid, level="win", message=f"Published on {c.channel}: {published_url}"))
    db.commit()
    return _back(pid, "queue")


@app.get("/p/{pid}/tasks", response_class=HTMLResponse)
def tasks_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    tasks = db.scalars(select(Task).where(Task.project_id == pid).order_by(Task.playbook, Task.day, Task.id)).all()
    return templates.TemplateResponse(request, "tasks.html", {"p": p, "tasks": tasks, "tab": "tasks",
                                                             "playbooks": playbooks.items()})


@app.post("/p/{pid}/tasks/{tid}")
def task_action(pid: int, tid: int, status: str = Form(...), db: Session = Depends(get_db)):
    t = db.get(Task, tid)
    if t and t.project_id == pid and status in ("todo", "doing", "done", "skipped"):
        t.status = status
        if status == "doing" and t.owner == "auto" and t.data.get("job"):
            enqueue(db, t.data["job"], pid)
        db.commit()
    return _back(pid, "tasks")


@app.get("/p/{pid}/settings", response_class=HTMLResponse)
def settings_page(pid: int, request: Request, saved: int = 0, error: str = "", db: Session = Depends(get_db)):
    p = _project(db, pid)
    eff = merged_settings(p.settings)
    used = pipeline.over_budget(db, p, eff)[1]
    advanced = {k: v for k, v in (p.settings or {}).items() if k not in DEFAULTS}
    return templates.TemplateResponse(request, "settings.html", {
        "p": p, "effective": eff, "fields": forms.fields(eff), "labels": forms.SECTION_LABELS, "advanced": advanced,
        "used": used, "saved": saved, "error": error, "tab": "settings"})


@app.post("/p/{pid}/settings")
async def save_settings(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    form = await request.form()
    try:
        overrides = forms.parse(form)
        overrides.update(json.loads(form.get("advanced") or "{}"))
        voice = json.loads(form.get("brand_voice") or "{}")
    except (ValueError, json.JSONDecodeError) as e:
        return RedirectResponse(f"/p/{pid}/settings?error={str(e)[:120]}", status_code=303)
    p.settings, p.brand_voice = overrides, voice
    p.name = form.get("name") or p.name
    p.stage = form.get("stage") or p.stage
    p.client, p.niche, p.updated_at = form.get("client", ""), form.get("niche", ""), utcnow()
    db.commit()
    return RedirectResponse(f"/p/{pid}/settings?saved=1", status_code=303)


SECRET_LABELS = [("anthropic_api_key", "Anthropic API key"), ("ahrefs_api_key", "Ahrefs API key"),
                 ("dataforseo_login", "DataForSEO login"), ("dataforseo_password", "DataForSEO password")]


@app.get("/settings", response_class=HTMLResponse)
def app_settings_page(request: Request, saved: int = 0, db: Session = Depends(get_db)):
    s = get_settings()
    stored = {r.key for r in db.scalars(select(AppSetting)) if r.value}
    status = {k: ("saved in app" if k in stored else ("from env" if getattr(s, k) else "")) for k, _ in SECRET_LABELS}
    return templates.TemplateResponse(request, "app_settings.html", {
        "s": s, "secrets": SECRET_LABELS, "status": status, "saved": saved})


@app.post("/settings")
async def app_settings_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()

    def put(key: str, value: str):
        row = db.get(AppSetting, key) or AppSetting(key=key)
        row.value = value
        db.add(row)

    for k in SECRET_KEYS:
        if form.get(f"clear_{k}"):
            put(k, "")
        elif (form.get(k) or "").strip():
            put(k, encrypt(form.get(k).strip()))
    for k in PLAIN_KEYS:
        if k in form:
            put(k, str(form.get(k)).strip())
    db.commit()
    invalidate_settings()
    if (form.get("admin_password") or "").strip():
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/settings?saved=1", status_code=303)


# ------------------------------------------------------------------ JSON API
@app.get("/api/projects")
def api_projects(db: Session = Depends(get_db)):
    return [{"id": p.id, "name": p.name, "domain": p.domain, "stage": p.stage, "funnel": funnel(db, p.id),
             "needs_input": p.needs_input} for p in db.scalars(select(Project))]


@app.get("/api/projects/{pid}/opportunities")
def api_opps(pid: int, kind: str = "", db: Session = Depends(get_db)):
    q = select(Opportunity).where(Opportunity.project_id == pid)
    if kind:
        q = q.where(Opportunity.kind == kind)
    return [{"id": o.id, "kind": o.kind, "title": o.title, "domain": o.domain, "platform": o.platform,
             "score": o.score, "status": o.status, "competitors": o.competitors_count, "data": o.data}
            for o in db.scalars(q.order_by(Opportunity.score.desc()).limit(500))]
