"""Web app: `uvicorn app.main:app`. Server-rendered (Jinja) for v1.

TODO(upgrade): JSON API under /api is already the source of truth for the views; a React
dashboard or client portal can be added on top without touching the backend.
"""
from __future__ import annotations

import hmac
import json
import re
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
from app.channels import COMPOSE_URLS, HUB_PLATFORMS, get_channel, test_hub
from app.classify import domain_of
from app.config import DEFAULTS, PLAIN_KEYS, PROJECT_TYPES, project_cfg, SECRET_KEYS, get_settings, invalidate_settings, merged_settings
from app import auth as authz
from app.db import SessionLocal, get_db, init_db
from app.models import (ApiUsage, AppSetting, Contact, PlatformAccount, ProjectMember, User, Competitor, ContentItem, EarnedLink, Event, Job, Opportunity, Project, Task,
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
    if not path.startswith(("/login", "/healthz", "/static", "/logout", "/u/")):
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
def create_project(name: str = Form(...), domain: str = Form(...), stage: str = Form("launch"), type: str = Form("ecommerce"),
                   niche: str = Form(""), client: str = Form(""), competitors: str = Form(""),
                   seed_keywords: str = Form(""), db: Session = Depends(get_db)):
    p = Project(name=name.strip(), domain=domain_of(domain), stage=stage, niche=niche, client=client,
                type=type if type in PROJECT_TYPES else "ecommerce",
                settings={"discovery": {"seed_keywords": [k.strip() for k in seed_keywords.split(",") if k.strip()]}})
    db.add(p)
    db.flush()
    for c in competitors.replace("\n", ",").split(","):
        if c.strip():
            db.add(Competitor(project_id=p.id, domain=domain_of(c), source="manual", confirmed=True))
    db.add(Event(project_id=p.id, message=f"Project created: {p.name} ({p.domain})"))
    # one-time setup: brand voice -> social targets + first Pinterest pins (no recurring jobs)
    enqueue(db, "build_brand_voice", p.id)
    db.commit()
    return _back(p.id)


@app.get("/p/{pid}", response_class=HTMLResponse)
def project_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    top_q = select(Opportunity).where(Opportunity.project_id == pid, Opportunity.status.in_(("new", "approved")))
    if _builder_only_own(me(request)):
        top_q = top_q.where(Opportunity.assigned_to == me(request).id)
    top = db.scalars(top_q
                     .order_by(Opportunity.score.desc()).limit(10)).all()
    tasks = db.scalars(select(Task).where(Task.project_id == pid, Task.status != "done")
                       .order_by(Task.day, Task.id).limit(12)).all()
    events = db.scalars(select(Event).where(Event.project_id == pid).order_by(Event.created_at.desc()).limit(12)).all()
    jobs = db.scalars(select(Job).where(Job.project_id == pid).order_by(Job.created_at.desc()).limit(6)).all()
    by_acq = dict(db.execute(select(Opportunity.kind, func.count()).where(Opportunity.project_id == pid)
                             .group_by(Opportunity.kind)).all())
    usage = db.scalar(select(func.coalesce(func.sum(ApiUsage.units), 0)).where(ApiUsage.project_id == pid))
    se = _social_engine(db, pid)
    social = social_engine_call(se, "GET", "/api/stats") if se else None
    return templates.TemplateResponse(request, "project.html", {
        "p": p, "f": funnel(db, pid), "top": top, "tasks": tasks, "events": events, "jobs": jobs,
        "by_kind": by_acq, "usage": usage, "playbooks": playbooks.items(), "social": social,
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
    from app.worker import HANDLERS

    _project(db, pid)
    if jtype not in HANDLERS:
        raise HTTPException(404, "Unknown job")
    enqueue(db, jtype, pid)
    db.commit()
    return _back(pid)


@app.post("/p/{pid}/playbooks/{name}/reset")
def reset_playbook(pid: int, name: str, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    if not authz.at_least(me(request), "manager"):
        raise HTTPException(403, "Only managers can reset a playbook")
    n = playbooks.get(name)().reset(db, p)
    db.add(Event(project_id=pid, user_id=me(request).id, level="info", message=f"Playbook '{name}' reset: {n} tasks removed"))
    db.commit()
    return _back(pid, "tasks")


@app.post("/p/{pid}/playbooks/{name}")
def apply_playbook(pid: int, name: str, start: str = Form(""), db: Session = Depends(get_db)):
    p = _project(db, pid)
    n = playbooks.get(name)().apply(db, p, date.fromisoformat(start) if start else None)
    db.add(Event(project_id=pid, level="info", message=f"Playbook '{name}' applied: {n} tasks"))
    db.commit()
    return _back(pid, "tasks")


PER_PAGE = 50


def paginate(q, page: int, db: Session):
    total = db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0
    page = max(1, page)
    rows = db.scalars(q.offset((page - 1) * PER_PAGE).limit(PER_PAGE)).all()
    return rows, {"page": page, "pages": max(1, -(-total // PER_PAGE)), "total": total}


def mask_email(e: str) -> str:
    local, _, dom = (e or "").partition("@")
    return f"{local[:2]}•••@{dom}" if dom else "•••"


templates.env.filters["mask_email"] = mask_email


def _back_to_list(request: Request, pid: int) -> RedirectResponse:
    from urllib.parse import urlparse

    ref = urlparse(request.headers.get("referer", ""))
    base = f"/p/{pid}/opportunities"
    same_project = ref.path == base or ref.path.startswith(f"/p/{pid}/") or ref.path == f"/p/{pid}"
    target = ref.path + (f"?{ref.query}" if ref.query else "") if same_project else base
    return RedirectResponse(target, status_code=303)


def _builder_only_own(user: User) -> bool:
    """Builders see and work only on opportunities assigned to them."""
    return not authz.at_least(user, "manager")


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
    return _back_to_list(request, pid)


@app.get("/p/{pid}/opportunities", response_class=HTMLResponse)
def opportunities_page(pid: int, request: Request, kind: str = "", status: str = "new", mine: int = 0, page: int = 1,
                       search: str = "",
                       db: Session = Depends(get_db)):
    p = _project(db, pid)
    q = select(Opportunity).where(Opportunity.project_id == pid)
    if search.strip():
        from sqlalchemy import or_

        like = f"%{search.strip()[:100]}%"
        q = q.where(or_(Opportunity.domain.ilike(like), Opportunity.url.ilike(like), Opportunity.title.ilike(like),
                        Opportunity.platform.ilike(like)))
    if mine or _builder_only_own(me(request)):
        q = q.where(Opportunity.assigned_to == me(request).id)
    if kind:
        q = q.where(Opportunity.kind == kind)
    if status == "any":
        status = ""
    if status:
        q = q.where(Opportunity.status == status)
    opps, pager = paginate(q.order_by(Opportunity.score.desc(), Opportunity.id), page, db)
    kinds = db.scalars(select(Opportunity.kind).where(Opportunity.project_id == pid).distinct()).all()
    return templates.TemplateResponse(request, "opportunities.html", {
        "p": p, "opps": opps, "kinds": kinds, "kind": kind, "status": status, "mine": mine, "tab": "opportunities",
        "pager": pager, "search": search,
        "team": _team(db, pid), "names": {u.id: u.name or u.email for u in db.scalars(select(User))},
        "is_manager": authz.at_least(me(request), "manager"), "me": me(request)})


@app.post("/p/{pid}/opportunities/{oid}")
def opportunity_action(pid: int, oid: int, request: Request, action: str = Form(...), user_id: str = Form(""),
                       db: Session = Depends(get_db)):
    o = db.get(Opportunity, oid)
    if not o or o.project_id != pid:
        raise HTTPException(404)
    u = me(request)
    if _builder_only_own(u) and o.assigned_to != u.id:
        raise HTTPException(403, "This opportunity isn't assigned to you")
    if action == "assign":
        if not authz.at_least(u, "manager") and user_id and int(user_id) != u.id:
            raise HTTPException(403, "Builders can only assign to themselves")
        o.assigned_to = int(user_id) if user_id else None
    elif action == "find_contact":
        enqueue(db, "find_contacts", pid, opportunity_id=oid)
    elif action == "draft":
        o.status = "approved"
        o.assigned_to = o.assigned_to or u.id
        enqueue(db, "draft_for_opportunity", pid, opportunity_id=oid, user_id=u.id)
    elif action in ("approved", "rejected", "snoozed", "done", "new"):
        o.status = action
    db.commit()
    return _back_to_list(request, pid)


QUEUE_VIEWS = {  # Link publishing sub-tabs: every content status has a home, nothing disappears
    "approve": ("To approve", ("pending_approval",)),
    "approved": ("Approved / sending", ("approved", "scheduled")),
    "published": ("Published", ("published",)),
    "failed": ("Failed", ("failed",)),
    "rejected": ("Rejected", ("rejected",)),
}


@app.get("/p/{pid}/queue", response_class=HTMLResponse)
def queue_page(pid: int, request: Request, page: int = 1, show: str = "", view: str = "", moved: str = "",
               search: str = "", db: Session = Depends(get_db)):
    p = _project(db, pid)
    by_status = dict(db.execute(select(ContentItem.status, func.count()).where(ContentItem.project_id == pid)
                                .group_by(ContentItem.status)).all())
    counts = {k: sum(by_status.get(s, 0) for s in sts) for k, (_, sts) in QUEUE_VIEWS.items()}
    if view not in QUEUE_VIEWS and view != "signups":
        view = "approve" if counts["approve"] else "signups"
    items, pager = [], {"page": 1, "pages": 1, "total": 0}
    if view in QUEUE_VIEWS:
        iq = select(ContentItem).where(ContentItem.project_id == pid, ContentItem.status.in_(QUEUE_VIEWS[view][1]))
        mail = ("outreach_email", "email")
        if show == "emails":
            iq = iq.where(ContentItem.channel.in_(mail))
        elif show == "posts":
            iq = iq.where(ContentItem.channel.notin_(mail + ("pinterest",)))
        elif show == "pins":
            iq = iq.where(ContentItem.channel == "pinterest")
        else:  # pins come in batches; they have their own filter so they don't bury emails and posts
            iq = iq.where(ContentItem.channel != "pinterest")
        if search.strip():
            from sqlalchemy import or_

            like = f"%{search.strip()[:100]}%"
            iq = iq.where(or_(ContentItem.title.ilike(like), ContentItem.channel.ilike(like),
                              ContentItem.published_url.ilike(like)))
        items, pager = paginate(iq.order_by(ContentItem.updated_at.desc()), page, db)
    links = {}
    if view == "published" and items:
        for el in db.scalars(select(EarnedLink).where(EarnedLink.content_item_id.in_([i.id for i in items]))):
            links.setdefault(el.content_item_id, []).append(el)
    kit_all = db.scalars(select(Opportunity).where(Opportunity.project_id == pid, Opportunity.kind == "self_publish",
                         Opportunity.status.in_(("new", "approved", "in_progress", "done")))
                         .order_by(Opportunity.score.desc())).all()
    if _builder_only_own(me(request)):
        kit_all = [o for o in kit_all if o.assigned_to == me(request).id]
    kit_all = [o for o in kit_all if (o.data or {}).get("category") in ("directory", "reviews", "deals", "affiliate", "profile", "marketplace", "web2")]
    kit_opps = [o for o in kit_all if o.status != "done"]
    kit_done = [o for o in kit_all if o.status == "done"]
    return templates.TemplateResponse(request, "queue.html", {
        "p": p, "items": items, "tab": "queue", "pager": pager, "show": show, "view": view, "views": QUEUE_VIEWS,
        "counts": counts, "moved": moved, "search": search, "links": links,
        "pin_counts": dict(db.execute(select(ContentItem.status, func.count()).where(
            ContentItem.project_id == pid, ContentItem.channel == "pinterest").group_by(ContentItem.status)).all()),
        "pin_api": bool(db.scalar(select(PlatformAccount.id).where(PlatformAccount.project_id == pid,
                                                                   PlatformAccount.platform == "pinterest",
                                                                   PlatformAccount.active.is_(True)).limit(1))),
        "kit": (p.brand_voice or {}).get("profile_kit"), "kit_opps": kit_opps, "kit_done": kit_done,
        "biz": {k: v for k, v in {**project_cfg(p)["business"],
                                  "business_name": project_cfg(p)["business"].get("business_name") or p.name}.items() if v},
        "compose": {i.id: _compose_url(db, i) for i in items},
        "opps": {o.id: o for o in db.scalars(select(Opportunity).where(
            Opportunity.id.in_([i.opportunity_id for i in items if i.opportunity_id] or [0])))},
        "recipients": _recipients(db, items), "full_contacts": authz.at_least(me(request), "manager"),
        "api": {i.id: get_channel(i.channel).mode == "api" for i in items}})


def _recipients(db: Session, items) -> dict:
    """Possible To: addresses per email draft (contacts found for that opportunity), best first."""
    from app.models import Contact
    from app.outreach import is_generic

    out = {}
    for i in items:
        if i.channel in ("outreach_email", "email") and (i.opportunity_id or i.contact_id):
            cs = db.scalars(select(Contact).where(
                Contact.project_id == i.project_id, Contact.status.notin_(("unsubscribed", "bounced")),
                (Contact.opportunity_id == (i.opportunity_id or -1)) | (Contact.id == (i.contact_id or -1)))).all()
            out[i.id] = [(c, is_generic(c.email)) for c in sorted(cs, key=lambda c: (is_generic(c.email), c.id))]
    return out


def _compose_url(db: Session, item: ContentItem) -> str:
    """Where to paste: the platform's posting page if known, else the site from the opportunity."""
    url = get_channel(item.channel).compose_url()
    if not url and item.opportunity_id:
        o = db.get(Opportunity, item.opportunity_id)
        if o and o.domain:
            url = f"https://{o.domain}"
    return url


@app.get("/p/{pid}/pins.csv")
def pins_csv(pid: int, db: Session = Depends(get_db)):
    from fastapi.responses import Response

    from app import pinterest

    p = _project(db, pid)
    items = db.scalars(select(ContentItem).where(ContentItem.project_id == pid, ContentItem.channel == "pinterest",
                                                 ContentItem.status.in_(("approved", "scheduled")))
                       .order_by(ContentItem.id)).all()
    per_day = int(project_cfg(p).get("pinterest", {}).get("csv_pins_per_day") or 3)
    return Response(pinterest.bulk_csv(items, per_day), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="pinterest-bulk-{p.domain}-{date.today().isoformat()}.csv"'})


@app.post("/p/{pid}/pins/{action}")
def pins_action(pid: int, action: str, request: Request, db: Session = Depends(get_db)):
    """approve_all: approve every pin awaiting approval; uploaded: mark CSV-exported pins as published."""
    u = me(request)
    q = select(ContentItem).where(ContentItem.project_id == pid, ContentItem.channel == "pinterest")
    n = 0
    if action == "approve_all":
        for it in db.scalars(q.where(ContentItem.status == "pending_approval")):
            it.status, it.approved_by = "approved", u.id
            enqueue(db, "publish_content", pid, content_id=it.id, user_id=u.id)
            n += 1
    elif action == "uploaded":
        for it in db.scalars(q.where(ContentItem.status.in_(("approved", "scheduled")))):
            it.status, it.published_by = "published", u.id
            it.data = {**(it.data or {}), "via": "bulk csv"}
            n += 1
    elif action == "build":
        enqueue(db, "build_pins", pid)
    else:
        raise HTTPException(404)
    db.add(Event(project_id=pid, user_id=u.id, level="info", message=f"Pins {action}: {n}"))
    db.commit()
    return RedirectResponse(f"/p/{pid}/queue?view=approve&show=pins", status_code=303)


@app.post("/p/{pid}/articles")
def new_article(pid: int, request: Request, topic: str = Form(...), target_url: str = Form(""),
                db: Session = Depends(get_db)):
    _project(db, pid)
    enqueue(db, "draft_article", pid, topic=topic, target_url=target_url, user_id=me(request).id)
    db.commit()
    return _back(pid, "queue")


@app.post("/p/{pid}/content/{cid}/test_email")
def test_email(pid: int, cid: int, request: Request, title: str = Form(""), body: str = Form(""),
               db: Session = Depends(get_db)):
    """Send a [TEST] copy of an email draft to the logged-in user. Saves edits first; the real contact is untouched."""
    from app import outreach

    c = db.get(ContentItem, cid)
    if not c or c.project_id != pid or c.channel not in ("outreach_email", "email"):
        raise HTTPException(404)
    u = me(request)
    if title or body:
        c.title, c.body = title or c.title, body or c.body
    ok, msg, _ = outreach.send_email(db, _project(db, pid), c, test_to=u.email)
    db.add(Event(project_id=pid, user_id=u.id, level="info" if ok else "warn",
                 message=f"Test email to {u.email}: " + ("sent, check your inbox" if ok else msg)))
    db.commit()
    return _back(pid, "queue")


@app.post("/p/{pid}/content/{cid}/publish")
def republish(pid: int, cid: int, request: Request, db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    if c and c.project_id == pid and c.status in ("approved", "scheduled", "failed"):
        c.status = "approved"
        enqueue(db, "publish_content", pid, content_id=cid, user_id=me(request).id)
        db.commit()
    return _back(pid, "queue")


PLATFORM_CHOICES = list(HUB_PLATFORMS) + ["social_engine"] + sorted(set(COMPOSE_URLS) | {"imap_inbox"})


def _social_engine(db: Session, pid: int):
    from app import social

    return social.engine_account(db, pid)


def social_engine_call(acct, method: str, path: str, payload: dict | None = None) -> dict:
    from app import social

    return social.call(acct, method, path, payload)


@app.post("/p/{pid}/social/scan")
def social_scan(pid: int, request: Request, db: Session = Depends(get_db)):
    from app import social

    acct = _social_engine(db, pid)
    if acct:
        social.push(db, _project(db, pid))  # engine always scans with the dashboard's current settings
        res = social_engine_call(acct, "POST", "/api/scan")
        audit(db, me(request).id, f"Social engine scan: {res}", pid)
        db.commit()
    return _back(pid)


@app.get("/p/{pid}/accounts", response_class=HTMLResponse)
def accounts_page(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _project(db, pid)
    accts = db.scalars(select(PlatformAccount).where(PlatformAccount.project_id == pid)).all()
    return templates.TemplateResponse(request, "accounts.html", {
        "p": p, "accts": accts, "platforms": PLATFORM_CHOICES, "tab": "accounts"})


@app.post("/p/{pid}/accounts")
def add_account(pid: int, request: Request, platform: str = Form(...), persona: str = Form("brand"),
                handle: str = Form(""), site_url: str = Form(""), public_url: str = Form(""), username: str = Form(""),
                password: str = Form(""), host: str = Form(""), db: Session = Depends(get_db)):
    _project(db, pid)
    if platform not in PLATFORM_CHOICES:
        raise HTTPException(400)
    db.add(PlatformAccount(project_id=pid, platform=platform, persona=persona, handle=handle,
                           secret=encrypt(json.dumps({"username": username, "password": password})) if password else "",
                           data={"site_url": site_url.strip(), "public_url": public_url.strip(), "host": host.strip()}))
    audit(db, me(request).id, f"Connected account {platform} {handle or site_url}", pid)
    db.commit()
    if platform == "social_engine":  # hand the engine this project's settings right away
        from app import social

        p = _project(db, pid)
        if not ((p.settings or {}).get("social") or {}).get("queries"):
            enqueue(db, "suggest_social", pid)  # Claude fills targets, then pushes them
            db.commit()
        else:
            social.push(db, p)
    return _back(pid, "accounts")


@app.post("/p/{pid}/accounts/{aid}/{action}")
def account_action(pid: int, aid: int, action: str, request: Request, db: Session = Depends(get_db)):
    a = db.get(PlatformAccount, aid)
    if not a or a.project_id != pid:
        raise HTTPException(404)
    if action == "test" and a.platform in HUB_PLATFORMS:
        a.data = {**a.data, "last_test": test_hub(a)}
    elif action == "toggle":
        a.active = not a.active
    elif action == "delete":
        audit(db, me(request).id, f"Deleted account {a.platform} {a.handle}", pid)
        db.delete(a)
    db.commit()
    return _back(pid, "accounts")


@app.post("/p/{pid}/content/{cid}")
def content_action(pid: int, cid: int, request: Request, action: str = Form(...), title: str = Form(""),
                   body: str = Form(""), published_url: str = Form(""), category: str = Form(None),
                   contact_id: int = Form(0), view: str = Form(""), db: Session = Depends(get_db)):
    c = db.get(ContentItem, cid)
    before = c.status if c else None
    if not c or c.project_id != pid:
        raise HTTPException(404)
    u = me(request)
    if action == "approve":
        cfg = project_cfg(_project(db, pid))
        if not authz.at_least(u, "manager") and not cfg["automation"].get("builders_can_approve", True):
            raise HTTPException(403, "A manager must approve this project's content")
        c.approved_by = u.id
    if category is not None:
        c.data = {**(c.data or {}), "category": category.strip()}
    if contact_id:
        from app.models import Contact

        ct = db.get(Contact, contact_id)
        if not ct or ct.project_id != pid:
            raise HTTPException(400, "Unknown contact")
        c.contact_id = ct.id
    if action == "save":
        c.title, c.body = title, body
    elif action == "approve":
        c.title, c.body, c.status = title or c.title, body or c.body, "approved"
        if get_channel(c.channel).mode == "api":  # approved -> publish via API (within daily limits)
            enqueue(db, "publish_content", pid, content_id=c.id, user_id=u.id)
    elif action == "reject":
        c.status = "rejected"
    elif action == "restore":  # rejected/failed back to the approval list
        c.status = "pending_approval"
        c.data = {k: v for k, v in (c.data or {}).items() if k != "error"}
    elif action == "published":
        published_url = published_url.strip()
        if not published_url.startswith(("https://", "http://")):
            raise HTTPException(400, "Paste the live page URL (starting with https://) before clicking Mark published")
        is_mail = c.channel in ("email", "outreach_email")
        if c.status != "published" or not is_mail:  # sent emails stay 'sent'; we only attach the editor's page
            c.status, c.published_by = "published", c.published_by or u.id
        c.published_url = c.published_url or published_url
        _add_earned_link(db, pid, published_url, c.target_url, "outreach" if is_mail else "self_publish", u.id, c.id)
        db.add(Event(project_id=pid, user_id=u.id, level="win",
                     message=f"{u.name or u.email} {'got a link from' if is_mail else 'published on'} "
                             f"{c.channel}: {published_url}"))
    db.commit()
    from urllib.parse import quote

    if c.status != before:
        dest = next((k for k, (_, sts) in QUEUE_VIEWS.items() if c.status in sts), "")
        return RedirectResponse(f"/p/{pid}/queue?view={quote(view)}&moved={dest}", status_code=303)
    return RedirectResponse(f"/p/{pid}/queue?view={quote(view)}", status_code=303)


def _add_earned_link(db: Session, pid: int, url: str, target: str, kind: str, uid: int | None,
                     content_id: int | None = None, note: str = "") -> EarnedLink:
    """Create (or reuse) the earned-link row for a page and queue its analysis."""
    el = db.scalar(select(EarnedLink).where(EarnedLink.project_id == pid, EarnedLink.source_url == url))
    if el is None:
        el = EarnedLink(project_id=pid, source_url=url, target_url=target or "", kind=kind, status="pending",
                        content_item_id=content_id, credited_to=uid, audit={"note": note} if note else None)
        db.add(el)
        db.flush()
    enqueue(db, "check_links", pid, link_id=el.id)
    return el


def _links_query(db: Session, pid: int, request: Request, status: str, kind: str, search: str, person: int):
    q = select(EarnedLink).where(EarnedLink.project_id == pid)
    if _builder_only_own(me(request)) and me(request).role != "client":
        person = me(request).id
    if person:
        q = q.where(EarnedLink.credited_to == person)
    if status:
        q = q.where(EarnedLink.status == status)
    if kind:
        q = q.where(EarnedLink.kind == kind)
    if search.strip():
        q = q.where(EarnedLink.source_url.ilike(f"%{search.strip()[:100]}%"))
    return q.order_by(EarnedLink.created_at.desc())


def _link_rows(el: EarnedLink) -> list[dict]:
    """One row per individual link on the page (falls back to the page itself before it's analysed)."""
    a = el.audit or {}
    links = a.get("links") or ([{"url": el.target_url, "anchor": el.anchor or "", "dofollow": el.dofollow,
                                 "in_content": a.get("in_content")}] if el.anchor else [])
    return links or [{"url": "", "anchor": "", "dofollow": None, "in_content": None}]


@app.get("/p/{pid}/links", response_class=HTMLResponse)
def links_page(pid: int, request: Request, status: str = "", kind: str = "", search: str = "", person: int = 0,
               page: int = 1, db: Session = Depends(get_db)):
    from app.classify import root_domain

    p = _project(db, pid)
    rows = db.scalars(_links_query(db, pid, request, status, kind, search, person)).all()
    groups: dict[str, list[EarnedLink]] = {}
    for el in rows:
        groups.setdefault(root_domain(domain_of(el.source_url)), []).append(el)
    doms = sorted(groups.items(), key=lambda kv: (-max((e.score or 0) for e in kv[1]), kv[0]))
    page = max(1, page)
    shown = doms[(page - 1) * PER_PAGE: page * PER_PAGE]
    pager = {"page": page, "pages": max(1, -(-len(doms) // PER_PAGE)), "total": len(doms)}
    external = [e for e in rows if not (e.audit or {}).get("internal")]
    scored = [e.score for e in external if e.score is not None]
    summary = {
        "domains": len({root_domain(domain_of(e.source_url)) for e in external}),
        "pages": len(external),
        "links": sum((e.audit or {}).get("link_count") or (1 if e.status == "live" else 0) for e in external),
        "live": sum(1 for e in external if e.status == "live"),
        "lost": sum(1 for e in external if e.status in ("lost", "not_found")),
        "dofollow": sum(1 for e in external if e.dofollow),
        "avg": round(sum(scored) / len(scored)) if scored else None,
        "internal": len(rows) - len(external),
    }
    from urllib.parse import urlencode

    qs = urlencode({k: v for k, v in {"status": status, "kind": kind, "search": search,
                                      "person": person or ""}.items() if v})
    return templates.TemplateResponse(request, "links.html", {
        "p": p, "tab": "links", "groups": shown, "pager": pager, "summary": summary, "qs": ("&" + qs) if qs else "",
        "f": {"status": status, "kind": kind, "search": search, "person": person},
        "kinds": sorted({e.kind for e in rows if e.kind} | {"self_publish", "outreach", "pr", "other"}),
        "team": _team(db, pid), "names": {u.id: u.name or u.email for u in db.scalars(select(User))},
        "is_manager": authz.at_least(me(request), "manager"), "rows": _link_rows})


@app.get("/p/{pid}/links.csv")
def links_csv(pid: int, request: Request, status: str = "", kind: str = "", search: str = "", person: int = 0,
              db: Session = Depends(get_db)):
    import csv
    import io

    from fastapi.responses import Response

    from app.classify import root_domain

    p = _project(db, pid)
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["referring_domain", "page_url", "page_status", "page_score", "links_on_page", "link_to", "anchor",
                "dofollow", "placement", "type", "credited_to", "published", "last_checked", "issues"])
    for el in db.scalars(_links_query(db, pid, request, status, kind, search, person)):
        a = el.audit or {}
        for ln in _link_rows(el):
            w.writerow([root_domain(domain_of(el.source_url)), el.source_url, el.status,
                        "" if el.score is None else int(el.score), a.get("link_count", ""), ln.get("url", ""),
                        ln.get("anchor", ""), {True: "dofollow", False: "nofollow"}.get(ln.get("dofollow"), ""),
                        {True: "in content", False: "nav/footer/sidebar"}.get(ln.get("in_content"), ""), el.kind,
                        names.get(el.credited_to, ""), el.created_at.strftime("%Y-%m-%d"),
                        el.last_checked.strftime("%Y-%m-%d") if el.last_checked else "", "; ".join(a.get("issues", []))])
    fname = f"earned-links-{p.domain}-{date.today().isoformat()}.csv"
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/p/{pid}/links")
def add_link(pid: int, request: Request, url: str = Form(...), kind: str = Form("outreach"), note: str = Form(""),
             db: Session = Depends(get_db)):
    """Record a link earned outside the publishing flow (editor placed it, PR mention, partner...)."""
    _project(db, pid)
    url = url.strip()
    if not url.startswith(("https://", "http://")):
        raise HTTPException(400, "URL must start with https://")
    if kind not in ("self_publish", "outreach", "pr", "other"):
        kind = "other"
    u = me(request)
    _add_earned_link(db, pid, url, "", kind, u.id, note=note.strip()[:300])
    db.add(Event(project_id=pid, user_id=u.id, level="win", message=f"{u.name or u.email} added earned link: {url}"))
    db.commit()
    return RedirectResponse(f"/p/{pid}/links", status_code=303)


@app.post("/p/{pid}/links/{lid}/{action}")
def link_action(pid: int, lid: int, action: str, request: Request, db: Session = Depends(get_db)):
    el = db.get(EarnedLink, lid)
    if not el or el.project_id != pid:
        raise HTTPException(404)
    u = me(request)
    if action == "recheck":
        if not authz.at_least(u, "manager") and el.credited_to != u.id:
            raise HTTPException(403)
        enqueue(db, "check_links", pid, link_id=el.id)
    elif action == "delete":
        if not authz.at_least(u, "manager"):
            raise HTTPException(403, "Only managers can delete earned links")
        audit(db, u.id, f"Deleted earned link {el.source_url}")
        db.delete(el)
    else:
        raise HTTPException(404)
    db.commit()
    return RedirectResponse(request.headers.get("referer") or f"/p/{pid}/links", status_code=303)


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
    eff = project_cfg(p)
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
    p.type = form.get("type") if form.get("type") in PROJECT_TYPES else p.type
    p.stage = form.get("stage") or p.stage
    p.client, p.niche, p.updated_at = form.get("client", ""), form.get("niche", ""), utcnow()
    audit(db, me(request).id, "Changed project settings", pid)
    db.commit()
    from app import social

    social.push(db, p)
    return RedirectResponse(f"/p/{pid}/settings?saved=1", status_code=303)


SECRET_LABELS = [("anthropic_api_key", "Anthropic API key"), ("ahrefs_api_key", "Ahrefs API key"),
                 ("dataforseo_login", "DataForSEO login"), ("dataforseo_password", "DataForSEO password"),
                 ("brevo_api_key", "Brevo API key (outreach sending)"), ("hunter_api_key", "Hunter.io API key (optional contact finder)")]


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
def api_opps(pid: int, request: Request, kind: str = "", db: Session = Depends(get_db)):
    q = select(Opportunity).where(Opportunity.project_id == pid)
    if _builder_only_own(me(request)):
        q = q.where(Opportunity.assigned_to == me(request).id)
    if kind:
        q = q.where(Opportunity.kind == kind)
    return [{"id": o.id, "kind": o.kind, "title": o.title, "domain": o.domain, "platform": o.platform,
             "score": o.score, "status": o.status, "competitors": o.competitors_count, "data": o.data}
            for o in db.scalars(q.order_by(Opportunity.score.desc()).limit(500))]



# ------------------------------------------------------------------ my account: password + 2FA
@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, need2fa: int = 0, msg: str = "", setup: str = ""):
    u = me(request)
    uri = qr = grouped = ""
    if setup and re.fullmatch(r"[A-Z2-7]{16,64}", setup):
        import segno

        uri = authz.otpauth_uri(setup, f"{u.email} ({setup[-4:]})", get_settings().app_name)
        qr = segno.make(uri, error="m").svg_inline(scale=5, dark="#000", light="#fff")
        grouped = " ".join(setup[i:i + 4] for i in range(0, len(setup), 4))
    return templates.TemplateResponse(request, "account.html", {
        "u": u, "need2fa": need2fa, "msg": msg, "setup": setup, "uri": uri, "qr": qr, "grouped": grouped})


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
def audit_page(request: Request, page: int = 1, db: Session = Depends(get_db)):
    rows, pager = paginate(select(Event).where(Event.level == "audit").order_by(Event.created_at.desc()), page, db)
    names = {u.id: u.name or u.email for u in db.scalars(select(User))}
    return templates.TemplateResponse(request, "audit.html", {"rows": rows, "names": names, "pager": pager})



# ------------------------------------------------------------------ outreach & PR
@app.get("/p/{pid}/outreach", response_class=HTMLResponse)
def outreach_page(pid: int, request: Request, page: int = 1, status: str = "", label: str = "", search: str = "",
                  linked: str = "", db: Session = Depends(get_db)):
    p = _project(db, pid)
    q = select(Contact).where(Contact.project_id == pid)
    if status:
        q = q.where(Contact.status == status)
    if search.strip():
        from sqlalchemy import or_

        like = f"%{search.strip()[:100]}%"
        q = q.where(or_(Contact.email.ilike(like), Contact.name.ilike(like), Contact.domain.ilike(like)))
    if linked == "yes":
        q = q.where(Contact.opportunity_id.is_not(None))
    elif linked == "no":
        q = q.where(Contact.opportunity_id.is_(None))
    if label:  # label lives in JSON; filter in Python (only replied contacts carry one)
        rows = [c for c in db.scalars(q.where(Contact.status == "replied").order_by(Contact.updated_at.desc()))
                if (c.data or {}).get("label") == label]
        page = max(1, page)
        contacts = rows[(page - 1) * PER_PAGE: page * PER_PAGE]
        pager = {"page": page, "pages": max(1, -(-len(rows) // PER_PAGE)), "total": len(rows)}
    else:
        contacts, pager = paginate(q.order_by(Contact.updated_at.desc()), page, db)
    copps = {o.id: o for o in db.scalars(select(Opportunity).where(
        Opportunity.id.in_([c.opportunity_id for c in contacts if c.opportunity_id] or [0])))}
    from urllib.parse import urlencode

    qs = urlencode({k: v for k, v in {"status": status, "label": label, "search": search, "linked": linked}.items() if v})
    prs = db.scalars(select(Opportunity).where(Opportunity.project_id == pid, Opportunity.kind == "pr_request",
                     Opportunity.status.in_(("new", "approved", "in_progress"))).order_by(Opportunity.created_at.desc()).limit(50)).all()
    counts = dict(db.execute(select(Contact.status, func.count()).where(Contact.project_id == pid).group_by(Contact.status)).all())
    cfg = project_cfg(p)
    ready = {"brevo": bool(get_settings().brevo_api_key), "sender": bool(cfg["sender"].get("email")),
             "address": bool(cfg["sender"].get("postal_address")),
             "inbox": bool(db.scalar(select(PlatformAccount).where(PlatformAccount.project_id == pid,
                                                                    PlatformAccount.platform == "imap_inbox")))}
    return templates.TemplateResponse(request, "outreach.html", {
        "p": p, "contacts": contacts, "prs": prs, "counts": counts, "ready": ready, "tab": "outreach", "pager": pager,
        "f": {"status": status, "label": label, "search": search, "linked": linked}, "qs": ("&" + qs) if qs else "",
        "copps": copps, "labels": ["interested", "question", "wants_payment", "link_placed", "not_interested",
                                   "out_of_office", "other"],
        "full_contacts": authz.at_least(me(request), "manager")})


@app.post("/p/{pid}/outreach/{jtype}")
def outreach_job(pid: int, jtype: str, request: Request, db: Session = Depends(get_db)):
    if jtype not in ("check_inbox", "draft_followups"):
        raise HTTPException(404)
    enqueue(db, jtype, pid, user_id=me(request).id)
    db.commit()
    return _back(pid, "outreach")


@app.post("/p/{pid}/contacts")
def add_contact(pid: int, request: Request, email: str = Form(...), name: str = Form(""), opportunity_id: str = Form(""),
                db: Session = Depends(get_db)):
    import secrets as _s

    e = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", e):
        raise HTTPException(400, "Invalid email")
    if not db.scalar(select(Contact).where(Contact.project_id == pid, Contact.email == e)):
        opp = db.get(Opportunity, int(opportunity_id)) if opportunity_id else None
        db.add(Contact(project_id=pid, email=e, name=name, source="manual", domain=e.split("@")[1],
                       opportunity_id=opp.id if opp and opp.project_id == pid else None, unsub_token=_s.token_urlsafe(24)))
        db.commit()
    return _back(pid, "outreach")


@app.post("/p/{pid}/contacts/import")
async def import_contacts(pid: int, request: Request, file: UploadFile = File(...), create_opps: str = Form(""),
                          db: Session = Depends(get_db)):
    from app import outreach

    if not authz.at_least(me(request), "manager"):
        raise HTTPException(403, "Only managers can bulk-import contacts")
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(400, "File too large (max 2 MB, about 20,000 rows)")
    p = _project(db, pid)
    r = outreach.import_contacts_csv(db, p, raw.decode("utf-8", errors="replace"), create_opps=bool(create_opps))
    db.add(Event(project_id=pid, user_id=me(request).id, level="action",
                 message=(f"Imported {r['added']} contacts ({r['linked']} linked to opportunities, "
                          f"{r['new_opportunities']} new sites added); {r['duplicates']} duplicates and "
                          f"{r['invalid']} invalid rows skipped.")))
    db.commit()
    return _back(pid, "outreach")


@app.get("/u/{token}", response_class=HTMLResponse)
@app.post("/u/{token}", response_class=HTMLResponse)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    c = db.scalar(select(Contact).where(Contact.unsub_token == token)) if len(token) > 20 else None
    if c:
        c.status = "unsubscribed"
        db.commit()
    return HTMLResponse("<p style='font-family:sans-serif;padding:40px'>You're unsubscribed. We won't email you again.</p>")



@app.get("/team/{uid}/links", response_class=HTMLResponse)
def person_links(uid: int, request: Request, page: int = 1, db: Session = Depends(get_db)):
    person = db.get(User, uid)
    if person is None:
        raise HTTPException(404)
    q = select(EarnedLink).where(EarnedLink.credited_to == uid).order_by(EarnedLink.created_at.desc())
    links, pager = paginate(q, page, db)
    projects = {p.id: p.name for p in db.scalars(select(Project))}
    scored = [l.score for l in db.scalars(select(EarnedLink).where(EarnedLink.credited_to == uid)) if l.score is not None]
    return templates.TemplateResponse(request, "person_links.html", {
        "person": person, "links": links, "pager": pager, "projects": projects,
        "avg": round(sum(scored) / len(scored)) if scored else None})


@app.post("/team/{uid}/links/recheck")
def person_links_recheck(uid: int, request: Request, db: Session = Depends(get_db)):
    pids = set(db.scalars(select(EarnedLink.project_id).where(EarnedLink.credited_to == uid)))
    for pid in pids:
        enqueue(db, "check_links", pid, credited_to=uid)
    audit(db, me(request).id, f"Re-checked links of user {uid}")
    db.commit()
    return RedirectResponse(f"/team/{uid}/links", status_code=303)
