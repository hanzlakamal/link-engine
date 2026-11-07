"""Web app: `uvicorn app.main:app`. Server-rendered (Jinja) for v1.

TODO(upgrade): JSON API under /api is already the source of truth for the views; a React
dashboard or client portal can be added on top without touching the backend.
"""
from __future__ import annotations

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
from app import auth as authz
from app.db import SessionLocal, get_db, init_db
from app.models import (ApiUsage, AppSetting, ProjectMember, User, Competitor, ContentItem, EarnedLink, Event, Job, Opportunity, Project, Task,
                        utcnow)
from app.registry import load_plugins, playbooks, providers, strategies
from app.security import decrypt, encrypt
from app.web import forms
from app.worker import enqueue

load_plugins()


@asynccontextmanager
async def lifespan(_app):
    authz.check_production_secrets()
    init_db()
    yield


app = FastAPI(title="Link Engine", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))
templates.env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, default=str)
COOKIE = "le_auth"


# ------------------------------------------------------------------ security + auth
def audit(db: Session, user_id: int | None, message: str, project_id: int | None = None) -> None:
    db.add(Event(project_id=project_id, user_id=user_id, level="audit", message=message))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    if request.method not in ("GET", "HEAD", "OPTIONS") and not authz.same_origin(
            request.headers.get("origin"), request.headers.get("referer"), request.headers.get("host", "")):
        return HTMLResponse("Blocked: cross-site request.", status_code=403)
    user = None
    if not path.startswith(("/login", "/healthz", "/static", "/logout")):
        with SessionLocal() as db:
            user = authz.user_from_token(db, request.cookies.get(COOKIE))
            if user is not None:
                db.expunge(user)
        if user is None:
            if path.startswith("/api"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        need = authz.required_role(request.method, path)
        pid = authz.project_id_from_path(path)
        if not authz.at_least(user, need) or (pid is not None and not authz.can_see_project(user, pid)):
            return HTMLResponse("You don't have permission for this. Ask an admin.", status_code=403)
        if (get_settings().require_2fa_for_admins and user.role == "admin" and not user.totp_secret
                and not path.startswith("/account")):
            return RedirectResponse("/account?need2fa=1", status_code=303)
    request.state.user = user
    response = await call_next(request)
    for k, v in authz.SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


def me(request: Request) -> User:
    return request.state.user


def _set_session(request: Request, response, user: User) -> None:
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(COOKIE, authz.session_token(user), httponly=True, samesite="lax", secure=secure,
                        max_age=authz.SESSION_DAYS * 86400)


templates.env.globals["ROLES"] = authz.ROLES
templates.env.globals["app_name"] = lambda: get_settings().app_name


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = "", db: Session = Depends(get_db)):
    first = db.scalar(select(func.count()).select_from(User)) == 0
    return templates.TemplateResponse(request, "login.html", {"error": error, "first": first})


@app.post("/login")
def login(request: Request, email: str = Form(""), password: str = Form(...), code: str = Form(""),
          db: Session = Depends(get_db)):
    email, ip = email.strip().lower(), _client_ip(request)
    if authz.login_locked(email, ip):
        return RedirectResponse("/login?error=locked", status_code=303)
    if db.scalar(select(func.count()).select_from(User)) == 0:
        # First run only: ADMIN_PASSWORD + your email creates the first admin account.
        if not email or not hmac.compare_digest(password, get_settings().admin_password):
            authz.login_failed(email, ip)
            return RedirectResponse("/login?error=1", status_code=303)
        db.add(User(email=email, name=email.split("@")[0], role="admin", password_hash=authz.hash_password(password)))
        db.commit()
    u = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
    if u is None or not authz.verify_password(password, u.password_hash):
        authz.login_failed(email, ip)
        audit(db, u.id if u else None, f"Failed login for {email} from {ip}")
        db.commit()
        return RedirectResponse("/login?error=1", status_code=303)
    if u.totp_secret and not authz.verify_totp(decrypt(u.totp_secret), code):
        authz.login_failed(email, ip)
        return RedirectResponse("/login?error=" + ("code" if code else "need_code"), status_code=303)
    authz.login_ok(email)
    u.last_login = utcnow()
    audit(db, u.id, f"Login from {ip}")
    db.commit()
    r = RedirectResponse("/", status_code=303)
    _set_session(request, r, u)
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
    u = me(request)
    projects = [p for p in db.scalars(select(Project).order_by(Project.created_at)) if authz.can_see_project(u, p.id)]
    rows = [{"p": p, "f": funnel(db, p.id),
             "todo": db.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id, Task.status == "todo")) or 0}
            for p in projects]
    events = [e for e in db.scalars(select(Event).where(Event.level != "audit").order_by(Event.created_at.desc()).limit(40))
              if e.project_id is None or e.project_id in {p.id for p in projects}][:15]
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


def _team(db: Session, pid: int) -> list[User]:
    return [u for u in db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))
            if u.role in ("builder", "manager", "admin") and authz.can_see_project(u, pid)]


@app.post("/p/{pid}/opportunities/auto-assign")
def auto_assign(pid: int, request: Request, db: Session = Depends(get_db)):
    if not authz.at_least(me(request), "manager"):
        raise HTTPException(403)
    people = [u for u in _team(db, pid) if u.role == "builder"] or _team(db, pid)
    opps = db.scalars(select(Opportunity).where(Opportunity.project_id == pid, Opportunity.status == "new",
                      Opportunity.assigned_to.is_(None)).order_by(Opportunity.score.desc())).all()
    for i, o in enumerate(opps):
        o.assigned_to = people[i % len(people)].id
    audit(db, me(request).id, f"Auto-assigned {len(opps)} opportunities to {len(people)} people", pid)
    db.commit()
    return RedirectResponse(f"/p/{pid}/opportunities", status_code=303)


@app.get("/p/{pid}/opportunities", response_class=HTMLResponse)
def opportunities_page(pid: int, request: Request, kind: str = "", status: str = "new", mine: int = 0,
                       db: Session = Depends(get_db)):
    p = _project(db, pid)
    q = select(Opportunity).where(Opportunity.project_id == pid)
    if mine:
        q = q.where(Opportunity.assigned_to == me(request).id)
    if kind:
        q = q.where(Opportunity.kind == kind)
    if status:
        q = q.where(Opportunity.status == status)
    opps = db.scalars(q.order_by(Opportunity.score.desc()).limit(300)).all()
    kinds = db.scalars(select(Opportunity.kind).where(Opportunity.project_id == pid).distinct()).all()
    return templates.TemplateResponse(request, "opportunities.html", {
        "p": p, "opps": opps, "kinds": kinds, "kind": kind, "status": status, "mine": mine, "tab": "opportunities",
        "team": _team(db, pid), "names": {u.id: u.name or u.email for u in db.scalars(select(User))},
        "is_manager": authz.at_least(me(request), "manager"), "me": me(request)})


@app.post("/p/{pid}/opportunities/{oid}")
def opportunity_action(pid: int, oid: int, request: Request, action: str = Form(...), user_id: str = Form(""),
                       db: Session = Depends(get_db)):
    o = db.get(Opportunity, oid)
    if not o or o.project_id != pid:
        raise HTTPException(404)
    u = me(request)
    if action == "assign":
        if not authz.at_least(u, "manager") and user_id and int(user_id) != u.id:
            raise HTTPException(403, "Builders can only assign to themselves")
        o.assigned_to = int(user_id) if user_id else None
    elif action == "draft":
        o.status = "approved"
        o.assigned_to = o.assigned_to or u.id
        enqueue(db, "draft_for_opportunity", pid, opportunity_id=oid, user_id=u.id)
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
def content_action(pid: int, cid: int, request: Request, action: str = Form(...), title: str = Form(""),
                   body: str = Form(""), published_url: str = Form(""), db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    if not c or c.project_id != pid:
        raise HTTPException(404)
    u = me(request)
    if action == "approve":
        cfg = merged_settings(_project(db, pid).settings)
        if not authz.at_least(u, "manager") and not cfg["automation"].get("builders_can_approve", True):
            raise HTTPException(403, "A manager must approve this project's content")
        c.approved_by = u.id
    if action == "save":
        c.title, c.body = title, body
    elif action == "approve":
        c.title, c.body, c.status = title or c.title, body or c.body, "approved"
    elif action == "reject":
        c.status = "rejected"
    elif action == "published" and published_url:
        if not published_url.startswith(("https://", "http://")):
            raise HTTPException(400, "Live URL must start with https://")
        c.status, c.published_url, c.published_by = "published", published_url, u.id
        db.add(EarnedLink(project_id=pid, source_url=published_url, target_url=c.target_url,
                          kind="self_publish" if c.channel != "email" else "outreach", status="pending",
                          content_item_id=c.id, credited_to=u.id))
        db.add(Event(project_id=pid, user_id=u.id, level="win",
                     message=f"{u.name or u.email} published on {c.channel}: {published_url}"))
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
    audit(db, me(request).id, "Changed project settings", pid)
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
        if k == "require_2fa_for_admins":
            put(k, "1" if form.get(k) else "0")
        elif k in form:
            put(k, str(form.get(k)).strip())
    changed = [k for k in SECRET_KEYS if (form.get(k) or "").strip() or form.get(f"clear_{k}")]
    audit(db, me(request).id, "Changed global settings" + (f" (secrets: {', '.join(changed)})" if changed else ""))
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



# ------------------------------------------------------------------ my account: password + 2FA
@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, need2fa: int = 0, msg: str = "", setup: str = ""):
    u = me(request)
    uri = authz.otpauth_uri(setup, u.email, get_settings().app_name) if setup else ""
    return templates.TemplateResponse(request, "account.html", {
        "u": u, "need2fa": need2fa, "msg": msg, "setup": setup, "uri": uri})


@app.post("/account")
def account_save(request: Request, action: str = Form(...), current: str = Form(""), new: str = Form(""),
                 secret: str = Form(""), code: str = Form(""), db: Session = Depends(get_db)):
    u = db.get(User, me(request).id)
    if not authz.verify_password(current, u.password_hash):
        return RedirectResponse("/account?msg=Current+password+is+wrong", status_code=303)
    if action == "password":
        problem = authz.password_problem(new)
        if problem:
            return RedirectResponse(f"/account?msg={problem}", status_code=303)
        u.password_hash = authz.hash_password(new)
        audit(db, u.id, "Changed own password")
    elif action == "2fa_start":
        return RedirectResponse(f"/account?setup={authz.new_totp_secret()}", status_code=303)
    elif action == "2fa_enable":
        if not authz.verify_totp(secret, code):
            return RedirectResponse(f"/account?setup={secret}&msg=Code+did+not+match", status_code=303)
        u.totp_secret = encrypt(secret)
        audit(db, u.id, "Enabled 2FA")
    elif action == "2fa_disable":
        u.totp_secret = ""
        audit(db, u.id, "Disabled 2FA")
    db.commit()
    r = RedirectResponse("/account?msg=Saved", status_code=303)
    _set_session(request, r, u)  # password change invalidated old sessions; keep this one
    return r


# ------------------------------------------------------------------ team (admin)
def team_stats(db: Session, days: int = 30) -> dict[int, dict]:
    from datetime import timedelta

    since = utcnow() - timedelta(days=days)
    stats: dict[int, dict] = {}

    def bump(uid, key, n=1):
        if uid:
            stats.setdefault(uid, {}).setdefault(key, 0)
            stats[uid][key] += n

    for (uid, n) in db.execute(select(Opportunity.assigned_to, func.count()).where(
            Opportunity.status.in_(("new", "approved", "in_progress"))).group_by(Opportunity.assigned_to)):
        bump(uid, "open", n)
    for col, key in ((ContentItem.created_by, "drafted"), (ContentItem.approved_by, "approved"),
                     (ContentItem.published_by, "published")):
        for (uid, n) in db.execute(select(col, func.count()).where(ContentItem.updated_at >= since).group_by(col)):
            bump(uid, key, n)
    for (uid, status, n) in db.execute(select(EarnedLink.credited_to, EarnedLink.status, func.count())
                                       .where(EarnedLink.created_at >= since)
                                       .group_by(EarnedLink.credited_to, EarnedLink.status)):
        bump(uid, "links", n)
        bump(uid, f"links_{status}", n)
    return stats


@app.get("/team", response_class=HTMLResponse)
def team_page(request: Request, days: int = 30, error: str = "", db: Session = Depends(get_db)):
    users = db.scalars(select(User).order_by(User.role.desc(), User.name)).all()
    projects = db.scalars(select(Project).order_by(Project.name)).all()
    return templates.TemplateResponse(request, "team.html", {
        "users": users, "projects": projects, "stats": team_stats(db, days), "days": days, "error": error})


@app.post("/team")
def team_save(request: Request, email: str = Form(...), name: str = Form(""), role: str = Form("builder"),
              password: str = Form(""), user_id: str = Form(""), active: str = Form(""),
              reset_2fa: str = Form(""), project_ids: list[int] = Form([]), db: Session = Depends(get_db)):
    if role not in authz.ROLES:
        raise HTTPException(400)
    if password and authz.password_problem(password):
        return RedirectResponse(f"/team?error={authz.password_problem(password)}", status_code=303)
    u = db.get(User, int(user_id)) if user_id else None
    if u is None:
        if not password:
            return RedirectResponse("/team?error=New+people+need+a+password", status_code=303)
        u = User(email=email.strip().lower())
        db.add(u)
    u.name, u.role, u.active = name, role, bool(active)
    if u.id == me(request).id:
        u.role, u.active = "admin", True  # you can't lock yourself out
    if password:
        u.password_hash = authz.hash_password(password)
    if reset_2fa:
        u.totp_secret = ""
    db.flush()
    db.query(ProjectMember).filter(ProjectMember.user_id == u.id).delete()
    for pid in project_ids:
        db.add(ProjectMember(user_id=u.id, project_id=pid))
    audit(db, me(request).id, f"Saved user {u.email} (role {u.role}, active {u.active})")
    db.commit()
    return RedirectResponse("/team", status_code=303)


@app.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Event).where(Event.level == "audit").order_by(Event.created_at.desc()).limit(300)).all()
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return templates.TemplateResponse(request, "audit.html", {"rows": rows, "names": names})
