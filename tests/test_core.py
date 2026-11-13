from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from app import pipeline
from app.classify import classify, score
from app.config import merged_settings
from app.db import session_scope
from app.limits import allow, daily_cap, record
from app.models import Competitor, Opportunity, Project, Task
from app.playbooks.launch import Launch72h
from app.providers.ahrefs import AhrefsProvider
from app.providers.base import BacklinkProvider, CompetitorInfo, DomainMetrics, RawBacklink
from app.registry import providers
from app.seasons import moments, upcoming
from app.security import decrypt, encrypt

Q = merged_settings({})["quality"]


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("url,acq,platform", [
    ("https://medium.com/@x/best-funny-shirts-123", "self_publish", "Medium"),
    ("https://someone.medium.com/post", "self_publish", "Medium"),
    ("https://www.quora.com/What-are-funny-shirts", "self_publish", "Quora"),
    ("https://www.pinterest.com/pin/123", "self_publish", "Pinterest"),
    ("https://www.knoji.com/questions/crazy-dog", "self_publish", "Knoji"),
    ("https://www.buzzfeed.com/funny-shirts", "pr", "BuzzFeed"),
    ("https://momblog.com/christmas-gift-guide-2025", "outreach", "momblog.com"),
    ("https://randomsite.com/write-for-us", "skip", ""),
    ("https://best-casino-wins.com/page", "skip", ""),
    ("https://craftforum.org/threads/shirt-printing.55", "self_publish", "craftforum.org"),
])
def test_classify(url, acq, platform):
    c = classify(url, quality=Q)
    assert c.acquisition == acq
    assert c.platform == platform


def test_classify_gift_guide_subtype():
    assert classify("https://momblog.com/christmas-gift-guide", quality=Q).subtype == "gift_guide"


def test_spam_flag_respected():
    assert classify("https://ok.com/a", is_spam=True, quality=Q).acquisition == "skip"


def test_score_bounds():
    w = Q["weights"]
    hi = score(dr=100, traffic=10**6, competitors_count=3, total_competitors=3, rel=1, dofollow_share=1, weights=w)
    lo = score(dr=0, traffic=0, competitors_count=0, total_competitors=3, rel=0, dofollow_share=0, weights=w)
    assert hi == 100 and lo == 0


# ---------------------------------------------------------------- settings / security / limits
def test_settings_merge_keeps_defaults():
    m = merged_settings({"limits": {"per_channel_per_day": {"reddit": 1}}})
    assert m["limits"]["per_channel_per_day"]["reddit"] == 1
    assert m["limits"]["per_channel_per_day"]["quora"] == 3  # untouched default survives
    assert m["quality"]["min_dr"] == 10


def test_encrypt_roundtrip():
    t = encrypt("hunter2")
    assert t != "hunter2" and decrypt(t) == "hunter2"


def test_email_ramp():
    cfg = merged_settings({})
    assert daily_cap(cfg, "email", 0) == 5
    assert daily_cap(cfg, "email", 14) == 17
    assert daily_cap(cfg, "email", 400) == 30


def test_rate_limit_blocks():
    cfg = merged_settings({"limits": {"per_channel_per_day": {"reddit": 2}}})
    with session_scope() as s:
        for _ in range(2):
            assert allow(s, cfg, 1, "reddit")[0]
            record(s, 1, "reddit")
        s.flush()
        ok, msg = allow(s, cfg, 1, "reddit")
        assert not ok and "2/2" in msg


# ---------------------------------------------------------------- seasons / playbooks
def test_thanksgiving_2026():
    tg = next(m for m in moments(2026) if m.key == "thanksgiving")
    assert tg.date == date(2026, 11, 26)


def test_launch_playbook_is_season_aware():
    p = Project(id=1, name="T-Shirt Crisis", domain="tshirtcrisis.com", stage="launch")
    tasks = Launch72h().tasks(p, date(2026, 11, 6))
    keys = [m.key for m in upcoming(date(2026, 11, 6))]
    assert "thanksgiving" in keys and "halloween" not in keys
    offer = next(t for t in tasks if "landing page" in t.title)
    assert "BFCM" in offer.detail  # BFCM within 28 days -> no %-off launch
    assert {t.module for t in tasks} >= {"measure", "links", "creators", "pr", "ads", "social"}


def test_playbook_apply_creates_tasks():
    with session_scope() as s:
        p = Project(name="X", domain="x.com")
        s.add(p)
        s.flush()
        n = Launch72h().apply(s, p, date(2026, 11, 6))
        s.flush()
        assert n == len(s.scalars(select(Task)).all()) > 15


# ---------------------------------------------------------------- pipeline end-to-end (fake provider)
@providers.register("fake")
class FakeProvider(BacklinkProvider):
    @classmethod
    def configured(cls):
        return True

    def competitors(self, domain, country="us", limit=20):
        return [] if domain == "tshirtcrisis.com" else [CompetitorInfo("other.com")]

    def metrics(self, domain, country="us"):
        return DomainMetrics(domain, 40, {"crazydogtshirts.com": 900, "teesrus.com": 300}.get(domain, 3))

    def backlinks(self, domain, limit=300, min_dr=0, include_traffic=False):
        if domain == "tshirtcrisis.com":
            return [RawBacklink("https://linktr.ee/tc", "linktr.ee")]
        common = [
            RawBacklink("https://medium.com/@a/funny-shirt-gifts", "medium.com", domain_rating=95, traffic=10**6, dofollow=False),
            RawBacklink("https://momblog.com/christmas-gift-guide", "momblog.com", title="Funny shirt gifts", domain_rating=45, traffic=20000),
            RawBacklink("https://cheap-casino.com/x", "cheap-casino.com", domain_rating=50),
        ]
        if domain == "crazydogtshirts.com":
            common.append(RawBacklink("https://www.quora.com/q/funny-tees", "quora.com", domain_rating=93, traffic=10**6))
        return common


def test_new_site_asks_for_competitor_then_runs():
    with session_scope() as s:
        p = Project(name="T-Shirt Crisis", domain="tshirtcrisis.com", settings={"discovery": {"providers": ["fake"]}})
        s.add(p)
        s.flush()
        r = pipeline.discover_competitors(s, p)
        assert r["status"] == "needs_input" and "competitor" in p.needs_input

        s.add(Competitor(project_id=p.id, domain="crazydogtshirts.com", source="manual", confirmed=True))
        s.add(Competitor(project_id=p.id, domain="teesrus.com", source="manual", confirmed=True))
        s.flush()
        s.refresh(p)
        assert pipeline.discover_competitors(s, p)["status"] == "ok" and not p.needs_input

        assert pipeline.pull_backlinks(s, p)["new_backlinks"] == 8  # 4 + 3 + ours 1 (spam filtered provider-side)
        s.flush()
        assert pipeline.pull_backlinks(s, p)["new_backlinks"] == 0  # competitors cached 30 days; ours deduped
        s.flush()
        out = pipeline.build_opportunities(s, p)
        s.flush()
        opps = {(o.kind, o.key): o for o in s.scalars(select(Opportunity))}
        assert ("self_publish", "medium") in opps and ("self_publish", "quora") in opps
        assert ("gift_guide", "momblog.com") in opps
        assert opps[("gift_guide", "momblog.com")].competitors_count == 2
        assert not any("casino" in k for _, k in opps)
        assert ("self_publish", "linktree") not in opps  # our own links are not opportunities
        assert out["self_publish"] == 2


# ---------------------------------------------------------------- provider parsing
def test_ahrefs_backlink_parsing():
    def handler(req):
        assert req.url.params["aggregation"] == "1_per_domain"
        assert "traffic_domain" not in req.url.params["select"] and "is_spam" in req.url.params["where"]
        return httpx.Response(200, json={"backlinks": [{
            "url_from": "https://blog.x.com/p", "url_to": "https://c.com/", "anchor": "tees", "title": "T",
            "is_dofollow": True, "domain_rating_source": 55.0, "traffic_domain": 1200, "root_name_source": "x.com",
            "page_type_source": "/Article", "is_spam": False, "first_seen_link": "2026-01-01T00:00:00Z"}]})
    p = AhrefsProvider(client=httpx.Client(base_url="https://api.ahrefs.com/v3", transport=httpx.MockTransport(handler)))
    [b] = p.backlinks("c.com")
    assert (b.source_domain, b.domain_rating, b.traffic, b.dofollow) == ("x.com", 55.0, 1200, True)


# ---------------------------------------------------------------- web smoke
def test_web_flow():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        assert c.get("/", follow_redirects=False).status_code == 303
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        r = c.post("/projects", data={"name": "T-Shirt Crisis", "domain": "https://www.tshirtcrisis.com/",
                                      "competitors": "crazydogtshirts.com"})
        assert r.status_code == 200 and "tshirtcrisis.com" in r.text
        pid = c.get("/api/projects").json()[0]["id"]
        assert c.post(f"/p/{pid}/playbooks/launch_72h").status_code == 200
        for path in ("", "/opportunities", "/queue", "/tasks", "/competitors", "/settings"):
            assert c.get(f"/p/{pid}{path}").status_code == 200, path
        assert "Gift-guide PR sprint" in c.get(f"/p/{pid}/tasks").text


def test_csv_import_and_new_kinds():
    csv_text = "\n".join([
        "url_from,domain_rating_source,traffic_domain,is_dofollow",
        "https://www.inksoft.com/customer-success-story-x/,83,4503,1",
        "https://www.sippycupmom.com/x-t-shirt-giveaway/,55,416,1",
        "https://blog.giftya.com/article/gift-ideas-for-teens,48,20209,1",
        "https://www.gofundme.com/f/team-x,92,1491124,1",
        "https://www.wethrift.com/codes/x.com,73,279675,0",
        "https://forum.example.pl/topic/123,60,5000,0",
        "https://x.myshopify.com/,95,1,1",
    ])
    with session_scope() as s:
        p = Project(name="T", domain="t.com", stage="launch")
        s.add(p)
        s.flush()
        assert pipeline.import_backlinks_csv(s, p, csv_text, "x.com")["imported"] == 7
        s.flush()
        pipeline.build_opportunities(s, p)
        s.flush()
        kinds = {o.key: o.kind for o in s.scalars(select(Opportunity))}
        assert kinds["inksoft.com"] == "vendor_case_study"
        assert kinds["sippycupmom.com"] == "blogger_review"
        assert kinds["giftya.com"] == "gift_guide"
        assert kinds["gofundme.com"] == "charity"
        assert kinds["wethrift"] == "self_publish"
        assert not any("example.pl" in k or "shopify" in k for k in kinds)


def test_marketplaces_are_not_competitors():
    from app.pipeline import is_platform_not_competitor

    cfg = merged_settings({})
    assert is_platform_not_competitor("amazon.com", cfg) and is_platform_not_competitor("etsy.com", cfg)
    assert not is_platform_not_competitor("threadheads.com", cfg)


def test_settings_form_roundtrip():
    from app.config import DEFAULTS
    from app.web import forms

    # Unchanged form -> no overrides stored
    flat = {}

    def walk(fs):
        for f in fs:
            if f["type"] == "group":
                walk(f["children"])
            elif f["type"] != "bool" or f["value"]:
                flat[f["path"]] = "on" if f["type"] == "bool" else str(f["value"])
    walk(forms.fields(merged_settings({})))
    assert forms.parse(flat) == {}
    flat["discovery.monthly_unit_budget"] = "5000"
    flat.pop("discovery.pull_own_backlinks")
    flat["quality.exclude_tlds"] = ""
    assert forms.parse(flat) == {"discovery": {"monthly_unit_budget": 5000, "pull_own_backlinks": False},
                                 "quality": {"exclude_tlds": []}}
    assert DEFAULTS["discovery"]["monthly_unit_budget"] == 10000


def test_global_settings_ui_overrides_env():
    from fastapi.testclient import TestClient

    from app.config import get_settings, invalidate_settings
    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        assert c.get("/settings").status_code == 200
        c.post("/settings", data={"ahrefs_api_key": "ui-key-123", "model_default": "claude-haiku-5-5",
                                  "worker_poll_seconds": "7", "job_max_attempts": "1"})
        invalidate_settings()
        s = get_settings()
        assert (s.ahrefs_api_key, s.model_default, s.worker_poll_seconds) == ("ui-key-123", "claude-haiku-5-5", 7)
        assert "ui-key-123" not in c.get("/settings").text  # never echoed back
        r = c.post("/p/0/settings", data={})
        assert r.status_code == 404
    invalidate_settings()


def test_security_roles_csrf_2fa_lockout():
    from fastapi.testclient import TestClient

    from app import auth as authz
    from app.db import session_scope as ss
    from app.main import app
    from app.models import ProjectMember, User

    authz._fails.clear()
    with TestClient(app) as admin:
        assert admin.post("/login", data={"email": "boss@test.com", "password": "wrong"}).url.path == "/login"
        admin.post("/login", data={"email": "boss@test.com", "password": "pw"})  # first run -> admin
        r = admin.get("/")
        assert r.status_code == 200 and r.headers["x-frame-options"] == "DENY" and "frame-ancestors" in r.headers["content-security-policy"]
        admin.post("/projects", data={"name": "A", "domain": "a.com"})
        admin.post("/projects", data={"name": "B", "domain": "b.com"})
        # forged cross-site POST is blocked
        assert admin.post("/projects", data={"name": "X", "domain": "x.com"},
                          headers={"origin": "https://evil.example"}).status_code == 403
        # weak passwords rejected for new users
        assert "error" in str(admin.post("/team", data={"email": "w@test.com", "password": "short", "role": "builder"}).url)
        with ss() as s:
            pa = s.scalar(select(Project).where(Project.domain == "a.com")).id
            pb = s.scalar(select(Project).where(Project.domain == "b.com")).id
            u = User(email="b@test.com", name="Builder", role="builder", password_hash=authz.hash_password("builder-pass-123"))
            s.add(u)
            s.flush()
            s.add(ProjectMember(user_id=u.id, project_id=pa))
    with TestClient(app) as b:
        b.post("/login", data={"email": "b@test.com", "password": "builder-pass-123"})
        assert b.get(f"/p/{pa}").status_code == 200
        assert b.get(f"/p/{pb}").status_code == 403          # not a member
        assert b.get("/team").status_code == 403             # admin only
        assert b.get("/settings").status_code == 403
        assert b.post(f"/p/{pa}/settings", data={}).status_code == 403  # managers only
        assert b.post("/projects", data={"name": "Y", "domain": "y.com"}).status_code == 403
        # 2FA: enable, then login requires the code
        secret = authz.new_totp_secret()
        b.post("/account", data={"action": "2fa_enable", "secret": secret, "code": authz.totp_now(secret),
                                 "current": "builder-pass-123"})
    with TestClient(app) as b2:
        assert b2.post("/login", data={"email": "b@test.com", "password": "builder-pass-123"}).url.params.get("error") == "need_code"
        b2.post("/login", data={"email": "b@test.com", "password": "builder-pass-123", "code": authz.totp_now(secret)})
        assert b2.get(f"/p/{pa}").status_code == 200
    # lockout after 5 failures for an email
    with TestClient(app) as x:
        for _ in range(5):
            x.post("/login", data={"email": "b@test.com", "password": "nope"})
        assert x.post("/login", data={"email": "b@test.com", "password": "builder-pass-123"}).url.params.get("error") == "locked"
    authz._fails.clear()


def test_ssrf_guard_and_totp():
    from app import auth as authz

    for bad in ("http://127.0.0.1/", "http://169.254.169.254/latest", "file:///etc/passwd", "http://10.0.0.5/"):
        with pytest.raises(ValueError):
            authz.assert_public_url(bad)
    s = authz.new_totp_secret()
    assert authz.verify_totp(s, authz.totp_now(s)) and not authz.verify_totp(s, "000000" if authz.totp_now(s) != "000000" else "111111")


def test_types_hub_outreach_smoke(monkeypatch):
    from fastapi.testclient import TestClient

    from app import outreach
    from app.config import project_cfg
    from app.main import app
    from app.models import Contact, ContentItem

    # affiliate projects skip deal/affiliate-network links
    aff = Project(name="P", domain="p.com", type="affiliate", settings={})
    q = project_cfg(aff)["quality"]
    assert classify("https://www.wethrift.com/codes/x.com", quality=q).acquisition == "skip"
    assert classify("https://www.wethrift.com/codes/x.com", quality=project_cfg(Project(name="E", domain="e.com", settings={}))["quality"]).acquisition == "self_publish"
    # outreach compliance gates
    with session_scope() as s:
        p = Project(name="T", domain="t.com", settings={"sender": {"email": "a@t.com", "postal_address": ""}})
        s.add(p)
        s.flush()
        c = Contact(project_id=p.id, email="ed@site.com", unsub_token="x" * 30, status="unsubscribed")
        s.add(c)
        s.flush()
        it = ContentItem(project_id=p.id, channel="outreach_email", title="Hi", body="Body", contact_id=c.id)
        s.add(it)
        s.flush()
        ok, msg, _ = outreach.send_email(s, p, it)
        assert not ok and "unsubscribed" in msg
        c.status = "new"
        ok, msg, _ = outreach.send_email(s, p, it)
        assert not ok and ("Brevo" in msg or "postal" in msg)
    with TestClient(app) as cl:
        cl.post("/login", data={"email": "admin@test.com", "password": "pw"})
        cl.post("/projects", data={"name": "Aff", "domain": "aff.com", "type": "affiliate"})
        pid = [x for x in cl.get("/api/projects").json() if x["domain"] == "aff.com"][0]["id"]
        for path in ("/outreach", "/accounts", "/queue", ""):
            assert cl.get(f"/p/{pid}{path}").status_code == 200, path
        assert "Affiliate / content site launch" in cl.get(f"/p/{pid}").text
        assert "72-hour launch sprint" not in cl.get(f"/p/{pid}").text
        assert cl.get("/u/" + "x" * 30).status_code == 200  # public unsubscribe works without login


def test_ai_and_worker_modules_import():
    import app.ai  # noqa: F401  (catches syntax/import errors the web tests don't touch)
    import app.outreach  # noqa: F401
    from app import worker

    assert {"draft_for_opportunity", "profile_kit", "send_email", "check_inbox", "check_links"} <= set(worker.HANDLERS)


def test_builder_sees_only_assigned_and_filters_survive():
    from fastapi.testclient import TestClient

    from app import auth as authz
    from app.main import app
    from app.models import ProjectMember, User

    authz._fails.clear()
    with session_scope() as s:
        p = Project(name="P", domain="p.com")
        s.add(p)
        s.flush()
        s.add(User(email="adm@test.com", name="A", role="admin", password_hash=authz.hash_password("admin-pass-1234")))
        b = User(email="bb@test.com", name="B", role="builder", password_hash=authz.hash_password("builder-pass-123"))
        s.add(b)
        s.flush()
        s.add(ProjectMember(user_id=b.id, project_id=p.id))
        s.add(Opportunity(project_id=p.id, kind="gift_guide", key="mine.com", title="MINE", assigned_to=b.id))
        s.add(Opportunity(project_id=p.id, kind="gift_guide", key="other.com", title="OTHER"))
        s.flush()
        pid, other = p.id, s.scalar(select(Opportunity).where(Opportunity.key == "other.com")).id
    with TestClient(app) as a:
        a.post("/login", data={"email": "adm@test.com", "password": "admin-pass-1234"})
        r = a.post(f"/p/{pid}/opportunities/{other}", data={"action": "assign", "user_id": ""},
                   headers={"referer": f"http://testserver/p/{pid}/opportunities?kind=gift_guide&status=new"})
        assert "kind=gift_guide" in str(r.url)  # filter preserved after assigning
    with TestClient(app) as c:
        c.post("/login", data={"email": "bb@test.com", "password": "builder-pass-123"})
        html = c.get(f"/p/{pid}/opportunities").text
        assert "MINE" in html and "OTHER" not in html
        assert c.post(f"/p/{pid}/opportunities/{other}", data={"action": "draft"}).status_code == 403
    authz._fails.clear()


def test_masking_pagination_person_links():
    from fastapi.testclient import TestClient

    from app import auth as authz
    from app.main import app, mask_email
    from app.models import Contact, EarnedLink, ProjectMember, User

    assert mask_email("editor@site.com") == "ed" + chr(0x2022) * 3 + "@site.com"
    authz._fails.clear()
    with session_scope() as s:
        s.add(User(email="adm2@test.com", name="A", role="admin", password_hash=authz.hash_password("admin-pass-1234")))
        b = User(email="b2@test.com", name="B", role="builder", password_hash=authz.hash_password("builder-pass-123"))
        p = Project(name="P", domain="p.com")
        s.add_all([b, p])
        s.flush()
        s.add(ProjectMember(user_id=b.id, project_id=p.id))
        s.add(Contact(project_id=p.id, email="editor@site.com", unsub_token="t" * 30))
        for i in range(60):
            s.add(Opportunity(project_id=p.id, kind="link_gap", key=f"d{i}.com", title=f"Site {i}", score=i))
        s.add(EarnedLink(project_id=p.id, source_url="https://x.com/post", credited_to=b.id, score=80, status="live"))
        s.flush()
        pid, bid = p.id, b.id
    with TestClient(app) as c:
        c.post("/login", data={"email": "b2@test.com", "password": "builder-pass-123"})
        html = c.get(f"/p/{pid}/outreach").text
        assert mask_email("editor@site.com") in html and "editor@site.com</small>" not in html
    with TestClient(app) as a:
        a.post("/login", data={"email": "adm2@test.com", "password": "admin-pass-1234"})
        assert "editor@site.com</small>" in a.get(f"/p/{pid}/outreach").text
        o = a.get(f"/p/{pid}/opportunities?status=new").text
        assert "page 1 of 2" in o and "Site 59" in o and "Site 0<" not in o
        assert "Site 0" in a.get(f"/p/{pid}/opportunities?status=new&page=2").text
        pl = a.get(f"/team/{bid}/links").text
        assert "https://x.com/post" in pl and "avg quality 80" in pl
    authz._fails.clear()


def test_opportunity_search_and_done_returns_to_queue():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "S", "domain": "s.com"})
        pid = c.get("/api/projects").json()[0]["id"]
        with session_scope() as s:
            s.add(Opportunity(project_id=pid, kind="self_publish", key="birdeye", title="Birdeye: x", domain="birdeye.com"))
            s.add(Opportunity(project_id=pid, kind="self_publish", key="bbb", title="BBB: x", domain="bbb.org"))
            s.flush()
            oid = s.scalar(select(Opportunity).where(Opportunity.key == "birdeye")).id
        html = c.get(f"/p/{pid}/opportunities?search=bird&status=").text
        assert "Birdeye" in html and "BBB: x" not in html
        r = c.post(f"/p/{pid}/opportunities/{oid}", data={"action": "done"},
                   headers={"referer": f"http://testserver/p/{pid}/queue"})
        assert r.url.path == f"/p/{pid}/queue"
        assert "Undo" in c.get(f"/p/{pid}/opportunities?status=done").text


def test_best_contact_prefers_named_person():
    from types import SimpleNamespace as N

    from app.outreach import best_contact
    cs = [N(id=1, email="info@site.com", name="", status="new"),
          N(id=2, email="amy.j@site.com", name="", status="new"),
          N(id=3, email="bob@site.com", name="Bob", status="unsubscribed")]
    assert best_contact(cs).id == 2


def test_playbook_apply_is_idempotent():
    from sqlalchemy import func, select

    from app.db import SessionLocal, init_db
    from app.models import Project, Task
    from app.registry import playbooks
    import app.playbooks  # noqa: F401
    init_db()
    s = SessionLocal()
    p = Project(name="PB", domain="pb-idem.com", type="ecommerce")
    s.add(p)
    s.flush()
    pb = playbooks.get("launch_72h")()
    first = pb.apply(s, p)
    s.flush()
    assert first > 0 and pb.apply(s, p) == 0
    assert s.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id)) == first
    s.rollback()


def test_playbook_apply_collapses_existing_duplicates():
    from sqlalchemy import func, select

    from app.db import SessionLocal, init_db
    from app.models import Project, Task
    from app.registry import playbooks
    import app.playbooks  # noqa: F401
    init_db()
    s = SessionLocal()
    p = Project(name="PB2", domain="pb-dup.com", type="ecommerce")
    s.add(p)
    s.flush()
    pb = playbooks.get("launch_72h")()
    n = pb.apply(s, p)
    first = s.scalars(select(Task).where(Task.project_id == p.id)).first()
    s.add(Task(project_id=p.id, playbook=pb.name, module=first.module, day=first.day, title=first.title, status="done"))
    s.flush()
    assert pb.apply(s, p) == 0
    assert s.scalar(select(func.count()).select_from(Task).where(Task.project_id == p.id)) == n
    assert s.scalar(select(Task.status).where(Task.project_id == p.id, Task.title == first.title)) == "done"
    assert pb.reset(s, p) == n
    s.rollback()


def test_contact_csv_import_links_to_opportunities():
    from sqlalchemy import select

    from app.db import SessionLocal, init_db
    from app.models import Contact, Opportunity, Project
    from app.outreach import import_contacts_csv
    init_db()
    s = SessionLocal()
    p = Project(name="Imp", domain="imp-test.com", type="ecommerce")
    s.add(p)
    s.flush()
    s.add(Opportunity(project_id=p.id, kind="link_gap", key="mag", domain="www.coolmag.com", url="https://www.coolmag.com/x"))
    s.flush()
    csv_text = ("Email,Name,Website,Outlet\n"
                "amy@coolmag.com,Amy,https://coolmag.com,Cool Mag\n"
                "bob@newblog.net,Bob,newblog.net,New Blog\n"
                "AMY@coolmag.com,Dup,,\n"
                "not-an-email,X,,\n")
    r = import_contacts_csv(s, p, csv_text)
    assert r == {"added": 2, "linked": 2, "new_opportunities": 1, "duplicates": 1, "invalid": 1}
    amy = s.scalar(select(Contact).where(Contact.project_id == p.id, Contact.email == "amy@coolmag.com"))
    assert s.get(Opportunity, amy.opportunity_id).key == "mag"
    assert import_contacts_csv(s, p, "carl@solo.org\n")["added"] == 1
    s.rollback()


def test_outreach_filters_import_and_queue_pages():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import Contact

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "F", "domain": "f-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "f-test.com"][0]["id"]
        r = c.post(f"/p/{pid}/contacts/import", data={"create_opps": "1"},
                   files={"file": ("c.csv", b"email,name,website\nzed@zmag.com,Zed,zmag.com\nyan@ymag.com,Yan,ymag.com\n")})
        assert r.status_code == 200
        with session_scope() as s:
            s.scalar(select(Contact).where(Contact.email == "zed@zmag.com")).status = "replied"
        html = c.get(f"/p/{pid}/outreach?status=replied").text
        assert "zmag.com" in html and "ymag.com" not in html
        assert "Draft pitch" in c.get(f"/p/{pid}/outreach?search=ymag").text
        assert c.get(f"/p/{pid}/queue?show=emails&page=2").status_code == 200


PAGE = """<html><body><header><nav><a href="https://brand.com/">Brand</a></nav></header>
<article><p>{words}</p><p>See <a href="https://www.brand.com/product/a">Tee A</a> and
<a href="https://brand.com/collection/b" rel="nofollow">Collection B</a> and <a href="/about">Self</a>
<a href="https://other.com/x">Other</a></p></article><footer><a href="https://brand.com/">Brand</a></footer></body></html>"""


def test_linkaudit_finds_every_link_and_scores_best(monkeypatch):
    import httpx

    from app import linkaudit

    class R:
        status_code = 200
        headers = {"content-type": "text/html"}
        url = "https://blog.example.org/post"
        text = PAGE.format(words="shirt " * 400)

    monkeypatch.setattr(linkaudit, "assert_public_url", lambda u: None)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    a = linkaudit.analyse("https://blog.example.org/post", "brand.com", ["shirt"])
    urls = [x["url"] for x in a["links"]]
    assert a["link_count"] == 3 and "https://www.brand.com/product/a" in urls  # nav+footer homepage deduped
    assert a["in_content_count"] == 2 and a["dofollow_count"] == 2
    assert a["in_content"] and a["dofollow"] and a["anchor"] == "Tee A" and not a["internal"]
    assert a["score"] >= 90


def test_queue_views_restore_and_links_report():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models import ContentItem, EarnedLink

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "Q", "domain": "q-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "q-test.com"][0]["id"]
        with session_scope() as s:
            s.add(ContentItem(project_id=pid, channel="reddit", content_type="post", title="Post one", body="hi"))
            s.flush()
            cid = s.scalar(select(ContentItem).where(ContentItem.project_id == pid)).id
        assert "Post one" in c.get(f"/p/{pid}/queue").text  # defaults to To approve
        r = c.post(f"/p/{pid}/content/{cid}", data={"action": "published", "view": "approve",
                                                    "published_url": "https://www.reddit.com/r/x/1"})
        assert "view=approve" in str(r.url) and "moved=published" in str(r.url)
        assert "moved to" in r.text
        assert "Post one" in c.get(f"/p/{pid}/queue?view=published").text
        c.post(f"/p/{pid}/content/{cid}", data={"action": "reject", "view": "published"})
        assert "Restore" in c.get(f"/p/{pid}/queue?view=rejected").text
        c.post(f"/p/{pid}/content/{cid}", data={"action": "restore", "view": "rejected"})
        assert "Post one" in c.get(f"/p/{pid}/queue?view=approve").text
        assert c.post(f"/p/{pid}/content/{cid}", data={"action": "published", "published_url": ""}).status_code == 400
        # second paste of the same URL must not crash (unique constraint)
        c.post(f"/p/{pid}/content/{cid}", data={"action": "published", "published_url": "https://www.reddit.com/r/x/1"})
        c.post(f"/p/{pid}/links", data={"url": "https://mag.example.net/gifts", "kind": "outreach", "note": "editor"})
        with session_scope() as s:
            el = s.scalar(select(EarnedLink).where(EarnedLink.source_url == "https://mag.example.net/gifts"))
            el.status, el.score = "live", 88
            el.audit = {"link_count": 2, "dofollow_count": 2, "in_content_count": 2, "issues": [],
                        "links": [{"url": "https://q-test.com/p/1", "anchor": "Tee", "dofollow": True, "in_content": True},
                                  {"url": "https://q-test.com/c/2", "anchor": "Gifts", "dofollow": True, "in_content": True}]}
            assert s.scalar(select(func.count()).select_from(EarnedLink).where(EarnedLink.project_id == pid)) == 2
        html = c.get(f"/p/{pid}/links").text
        assert "example.net" in html and "2 link(s) to you" in html
        csv_text = c.get(f"/p/{pid}/links.csv").text
        assert csv_text.count("https://mag.example.net/gifts") == 2 and "referring_domain" in csv_text


def test_social_settings_map_to_engine_and_suggest_fills_only_empty(monkeypatch):
    from app import ai, social
    from app.worker import HANDLERS

    with session_scope() as s:
        p = Project(name="Soc", domain="soc-test.com", type="ecommerce",
                    settings={"social": {"persona": "my persona", "queries": [], "pages": ["/gifts/"]}})
        s.add(p)
        s.flush()
        conf = social.engine_config(p)
        assert conf["site"] == "https://soc-test.com" and conf["brand"]["persona"] == "my persona"
        assert conf["pages"] == [{"url": "/gifts/", "about": ""}] and conf["quora"] is True and conf["queries"] == []
        monkeypatch.setattr(ai, "social_targets", lambda **k: {
            "brand_offer": "funny tees", "relevant": "r", "looking_now": "l", "persona": "AI persona", "rules": "x",
            "link_line": "disclosure:", "queries": ["gift for dad"], "subreddits": ["gifts"], "avoid_subreddits": [],
            "reject_topics": ["wholesale"], "quora_queries": ["best gift"], "pages": ["/"]})
        import app.worker as w
        monkeypatch.setattr(w, "_site_pages", lambda d, limit=60: ["/", "/gifts/"])
        HANDLERS["suggest_social"](s, p, {})
        sc = p.settings["social"]
        assert sc["persona"] == "my persona" and sc["queries"] == ["gift for dad"] and sc["pages"] == ["/gifts/"]
        assert social.push(s, p) is None  # no engine connected -> nothing to push


def test_run_job_rejects_unknown_types():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "J", "domain": "j-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "j-test.com"][0]["id"]
        assert c.post(f"/p/{pid}/jobs/rm_rf", follow_redirects=False).status_code == 404


def test_pinterest_build_approve_csv_flow(monkeypatch):
    from fastapi.testclient import TestClient

    from app import ai, pinterest
    from app.main import app
    from app.models import ContentItem
    from app.worker import HANDLERS

    monkeypatch.setattr(pinterest, "site_urls", lambda d, limit=400: ["https://pin-test.com/product/a", "https://pin-test.com/product/b"])
    monkeypatch.setattr(pinterest, "page_meta", lambda u: {"url": u, "image": u + ".jpg", "title": "T " + u[-1], "description": "d"})
    monkeypatch.setattr(ai, "pin_copy", lambda **k: {"boards": ["Funny Dad Shirts"], "pins": [
        {"url": p["url"], "title": "Pin " + p["url"][-1], "description": "desc", "board": "Funny Dad Shirts"} for p in k["pages"]]})
    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "Pin", "domain": "pin-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "pin-test.com"][0]["id"]
        with session_scope() as s:
            p = s.get(Project, pid)
            assert pinterest.build_pins(s, p)["created"] == 2
            assert pinterest.build_pins(s, p)["created"] == 0  # already pinned pages are skipped
            assert p.settings["pinterest"]["boards"] == ["Funny Dad Shirts"]
        html = c.get(f"/p/{pid}/queue?view=approve&show=pins").text
        assert "Pin a" in html and "Approve all 2" in html
        assert "Pin a" not in c.get(f"/p/{pid}/queue?view=approve").text  # pins don't bury emails/posts
        c.post(f"/p/{pid}/pins/approve_all")
        with session_scope() as s:
            for it in s.scalars(select(ContentItem).where(ContentItem.project_id == pid, ContentItem.channel == "pinterest")):
                assert it.status == "approved"
                HANDLERS["publish_content"](s, s.get(Project, pid), {"content_id": it.id})
                assert it.status == "approved" and "bulk CSV" in it.data["note"]  # no account -> waits for CSV
        csv_text = c.get(f"/p/{pid}/pins.csv").text
        assert csv_text.startswith("Title,Media URL,Pinterest board") and "https://pin-test.com/product/a.jpg" in csv_text
        c.post(f"/p/{pid}/pins/uploaded")
        with session_scope() as s:
            assert {i.status for i in s.scalars(select(ContentItem).where(ContentItem.project_id == pid))} == {"published"}


def test_social_scan_route_exists():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "SS", "domain": "ss-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "ss-test.com"][0]["id"]
        r = c.post(f"/p/{pid}/social/scan", follow_redirects=False)
        assert r.status_code == 303  # no engine connected -> back to overview, no "Unknown job"


def test_social_inbox_lists_items_and_credits_posted(monkeypatch):
    from fastapi.testclient import TestClient

    from app import social
    from app.main import app
    from app.models import ContentItem, PlatformAccount

    calls = []

    def fake_call(acct, method, path, payload=None):
        calls.append((method, path, payload))
        if path.startswith("/api/items?"):
            return {"total": 1, "items": [{"id": "reddit_q1", "source": "reddit", "sub": "gifts", "title": "Gift for dad?",
                                           "url": "https://reddit.com/r/gifts/q1", "draft": "Try a funny tee", "status": "pending",
                                           "withLink": True, "why": "asks for gift"}]}
        if path == "/api/stats":
            return {"brand": "Inbox Co", "byStatus": {"pending": 1}, "approved": 0, "seen": 9}
        return {"id": "reddit_q1", "status": "posted", "draft": "Try a funny tee"}

    monkeypatch.setattr(social, "call", fake_call)
    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "Inbox", "domain": "inbox-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "inbox-test.com"][0]["id"]
        assert "isn't connected" in c.get(f"/p/{pid}/social").text
        with session_scope() as s:
            s.add(PlatformAccount(project_id=pid, platform="social_engine", data={"site_url": "http://x.railway.internal:8080"}))
        html = c.get(f"/p/{pid}/social").text
        assert "Gift for dad?" in html and "Posted it" in html and "Inbox Co" in html
        r = c.post(f"/p/{pid}/social/items/reddit_q1/posted", data={
            "draft": "Try a funny tee", "title": "Gift for dad?", "thread_url": "https://reddit.com/r/gifts/q1",
            "source": "reddit", "with_link": "1", "comment_url": "https://reddit.com/r/gifts/q1/c9"})
        assert r.status_code == 200
        assert ("POST", "/api/items/reddit_q1/posted", {"by": "admin@test.com", "draft": "Try a funny tee"}) in calls
        with session_scope() as s:
            it = s.scalar(select(ContentItem).where(ContentItem.project_id == pid, ContentItem.channel == "reddit"))
            assert it.status == "published" and it.published_url.endswith("/c9") and it.published_by is not None
        assert c.post(f"/p/{pid}/social/items/bad id/posted").status_code in (404, 422)


def test_ai_teammate_guardrails_and_briefing(monkeypatch):
    from types import SimpleNamespace as N

    from app import agent, ai
    from app.models import ApiUsage, Contact, ContentItem, Event

    with session_scope() as s:
        p = Project(name="Agent Co", domain="agent-test.com", type="ecommerce",
                    settings={"sender": {"name": "", "email": "hi@mail.agent-test.com", "postal_address": "1 Main St"}})
        s.add(p)
        s.flush()
        c = Contact(project_id=p.id, email="ed@mag.com", name="Ed", unsub_token="t" * 24)
        s.add(c)
        s.flush()
        bad = ContentItem(project_id=p.id, channel="outreach_email", title="Hi [Name]", body="Hello [Name], ...", contact_id=c.id)
        good = ContentItem(project_id=p.id, channel="outreach_email", title="Gift guide idea", body="Hi Ed, loved your guide.", contact_id=c.id)
        reddit = ContentItem(project_id=p.id, channel="reddit", title="post", body="text")
        s.add_all([bad, good, reddit])
        s.flush()
        ids = (bad.id, good.id, reddit.id)
        script = [
            [("get_status", {})],
            [("approve_draft", {"item_id": ids[0]}), ("approve_draft", {"item_id": ids[1]}), ("approve_draft", {"item_id": ids[2]})],
            [("finish", {"briefing": "Reviewed 3 drafts. Fill in the sender name.", "needs_human": ["Set Settings > Sender name"]})],
        ]
        seen_results = []

        class FakeMessages:
            def create(self, **kw):
                if kw["messages"][-1]["role"] == "user" and isinstance(kw["messages"][-1]["content"], list):
                    seen_results.append(kw["messages"][-1]["content"])
                calls = script.pop(0)
                blocks = [N(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(calls)]
                return N(content=blocks, stop_reason="tool_use", usage=N(input_tokens=1000, output_tokens=200))

        monkeypatch.setattr(ai, "_client", lambda: N(messages=FakeMessages()))
        out = agent.run(s, p)
        results = [r["content"] for r in seen_results[1]]
        assert "placeholders" in results[0]          # [Name] refused
        assert "sender not ready" in results[1]       # no real sender name -> no sending
        assert "needs human approval" in results[2]   # reddit is never auto-approved
        assert {s.get(ContentItem, i).status for i in ids} == {"pending_approval"}
        brief = s.scalar(select(Event).where(Event.project_id == p.id, Event.level == "brief"))
        assert "sender name" in brief.message and brief.data["needs_human"] == ["Set Settings > Sender name"]
        assert out["spend_usd"] > 0 and agent.spent_today(s, p.id) == out["spend_usd"]
        # budget cap: a second run today with the cap already used stops before calling Claude
        s.add(ApiUsage(project_id=p.id, provider="claude_agent", units=5.0))
        s.flush()
        assert agent.run(s, p) == {"stopped": "budget"}
        assert agent.placeholders("Hi {first_name}, see <your name>") and not agent.placeholders("Hi Ed, thanks!")


def test_ai_teammate_approves_clean_email_when_sender_ready(monkeypatch):
    from types import SimpleNamespace as N

    from app import agent, ai
    from app.config import get_settings
    from app.models import Contact, ContentItem, Job

    monkeypatch.setattr(get_settings(), "brevo_api_key", "x", raising=False)
    with session_scope() as s:
        p = Project(name="Agent Two", domain="agent2-test.com", type="ecommerce",
                    settings={"sender": {"name": "Zayn Kye", "email": "hi@mail.agent2-test.com", "postal_address": "1 Main St"}})
        s.add(p)
        s.flush()
        c = Contact(project_id=p.id, email="ed@mag2.com", name="Ed", unsub_token="u" * 24)
        s.add(c)
        s.flush()
        it = ContentItem(project_id=p.id, channel="outreach_email", title="Gift guide idea", body="Hi Ed, loved your guide.", contact_id=c.id)
        s.add(it)
        s.flush()
        script = [[("approve_draft", {"item_id": it.id})], [("finish", {"briefing": "Approved 1 pitch."})]]

        class FakeMessages:
            def create(self, **kw):
                calls = script.pop(0)
                return N(content=[N(type="tool_use", id=f"t{i}", name=n, input=a) for i, (n, a) in enumerate(calls)],
                         stop_reason="tool_use", usage=N(input_tokens=10, output_tokens=10))

        monkeypatch.setattr(ai, "_client", lambda: N(messages=FakeMessages()))
        out = agent.run(s, p)
        assert out["approved"] == 1 and it.status == "approved" and it.approved_by is not None
        assert s.scalar(select(Job).where(Job.type == "publish_content", Job.project_id == p.id)) is not None


def test_banned_here_blocks_subreddit(monkeypatch):
    from fastapi.testclient import TestClient

    from app import social
    from app.main import app
    from app.models import PlatformAccount

    sent = []
    monkeypatch.setattr(social, "call", lambda acct, m, path, payload=None: sent.append((m, path, payload)) or {})
    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "Ban", "domain": "ban-test.com"})
        pid = [x for x in c.get("/api/projects").json() if x["domain"] == "ban-test.com"][0]["id"]
        with session_scope() as s:
            s.add(PlatformAccount(project_id=pid, platform="social_engine", data={"site_url": "http://b.railway.internal:8080"}))
            s.get(Project, pid).settings = {"social": {"subreddits": ["GiftIdeas", "gifts"]}}
        c.post(f"/p/{pid}/social/items/reddit_x/banned", data={"source": "reddit", "subreddit": "GiftIdeas"})
        with session_scope() as s:
            sc = s.get(Project, pid).settings["social"]
            assert sc["blocked_subreddits"] == ["GiftIdeas"] and sc["subreddits"] == ["gifts"]
        pushed = [p for m, path, p in sent if path == "/api/config"][0]
        assert pushed["blockedSubreddits"] == ["GiftIdeas"]
        assert ("POST", "/api/items/reddit_x/skip", {"by": "admin@test.com"}) in sent


def test_import_link_profiles_between_projects():
    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app
    from app.models import PlatformAccount, Project

    with SessionLocal() as s:
        a = Project(name="T-Shirt Crisis", domain="tshirtcrisis.com")
        b = Project(name="The Pest Help", domain="thepesthelp.com")
        s.add_all([a, b]); s.flush()
        s.add_all([
            PlatformAccount(project_id=a.id, platform="blogger", handle="Craxout", secret="enc", data={"host": "123"}),
            PlatformAccount(project_id=a.id, platform="tumblr", handle="tshirtcrisis"),  # brand-named
            PlatformAccount(project_id=a.id, platform="wordpress_hub", handle="store"),  # own site
            PlatformAccount(project_id=a.id, platform="medium", persona="founder", handle="Jane"),
            PlatformAccount(project_id=a.id, platform="devto", handle="neutral", data={"private": True}),
        ])
        s.commit()
        aid, bid = a.id, b.id
    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        page = c.get(f"/p/{bid}/accounts").text
        assert "Craxout" in page and "tshirtcrisis" not in page.split("Import link-building")[1].split("Connect an")[0]
        ids = [x.id for x in SessionLocal().query(PlatformAccount).filter_by(project_id=aid)]
        c.post(f"/p/{bid}/accounts/import", data={"aid": [str(i) for i in ids]})
        c.post(f"/p/{bid}/accounts/import", data={"aid": [str(i) for i in ids]})  # idempotent
    with SessionLocal() as s:
        got = s.query(PlatformAccount).filter_by(project_id=bid).all()
        assert [(g.platform, g.handle, g.persona, g.secret, g.data["host"]) for g in got] == [
            ("blogger", "Craxout", "network", "enc", "123")]
        assert got[0].data["imported_from"]["project_id"] == aid
