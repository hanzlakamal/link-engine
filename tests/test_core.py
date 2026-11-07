from datetime import date

import httpx
import pytest
from sqlalchemy import select

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
