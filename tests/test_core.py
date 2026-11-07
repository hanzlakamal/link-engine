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

    def backlinks(self, domain, limit=1000):
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

        assert pipeline.pull_backlinks(s, p)["new_backlinks"] == 8  # 4 + 3 + ours 1
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
        c.post("/login", data={"password": "pw"})
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
