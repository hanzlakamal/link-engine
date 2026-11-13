"""Launch Kit: catalog seeding, converters, parasite scoring, link cleaning, autopilot, tier 2, learning, web."""
import json

import pytest

from app.db import SessionLocal
from app.models import ContentItem, EarnedLink, Opportunity, PlatformAccount, Project


def _project(s, **kw):
    p = Project(name=kw.pop("name", "T-Shirt Crisis"), domain=kw.pop("domain", "tshirtcrisis.com"),
                type=kw.pop("type", "ecommerce"), settings=kw.pop("settings", {}), **kw)
    s.add(p)
    s.flush()
    return p


def test_seed_is_idempotent_and_type_aware():
    from app import launchkit

    with SessionLocal() as s:
        shop = _project(s)
        n = launchkit.seed(s, shop)
        s.flush()
        assert n > 60 and launchkit.seed(s, shop) == 0
        keys = {k for (k,) in s.query(Opportunity.key).filter_by(project_id=shop.id, kind="launch_site")}
        assert "redbubble.com" in keys and "producthunt.com" not in keys  # shop gets POD, not SaaS directories
        saas = _project(s, name="Tool", domain="tool.io", type="saas")
        launchkit.seed(s, saas)
        s.flush()
        skeys = {k for (k,) in s.query(Opportunity.key).filter_by(project_id=saas.id)}
        assert "producthunt.com" in skeys and "redbubble.com" not in skeys


def test_html_converters():
    from app.htmlconv import to_markdown, to_telegraph_nodes

    html = '<h2>Intro</h2><p>Read <a href="https://x.com/a">this</a> and <strong>that</strong>.</p><ul><li>one</li><li>two</li></ul>'
    md = to_markdown(html)
    assert "## Intro" in md and "[this](https://x.com/a)" in md and "**that**" in md and "- one" in md
    nodes = to_telegraph_nodes(html)
    assert nodes[0]["tag"] == "h3"  # h2 is not allowed on Telegraph
    assert any(c.get("tag") == "a" and c["attrs"]["href"] == "https://x.com/a" for c in nodes[1]["children"] if isinstance(c, dict))


def test_score_serp_prefers_platform_results():
    from app.launch_engine import score_serp
    from app.search import Result

    weak = [Result(url=f"https://{d}/x", title="", rank=i, domain=d) for i, d in
            enumerate(["medium.com", "www.reddit.com", "bigbrand.com", "foo.blogspot.com"], 1)]
    strong = [Result(url=f"https://{d}/x", title="", rank=i, domain=d) for i, d in enumerate(["amazon.com", "etsy.com"], 1)]
    a, b = score_serp(weak, 200, 10), score_serp(strong, 200, 10)
    assert a["weak_count"] == 3 and a["best_channel"] in ("medium", "blogger") and a["score"] > b["score"]
    assert b["weak_count"] == 0


def test_clean_links_keeps_one_money_link(monkeypatch):
    from app import launch_engine

    monkeypatch.setattr(launch_engine, "_alive", lambda u: "dead" not in u)
    html = ('<p>a <a href="https://tshirtcrisis.com/x">shop</a> b <a href="https://www.tshirtcrisis.com/y">again</a></p>'
            '<p><a href="https://cdc.gov/">cdc</a> <a href="https://dead.example/">dead</a> '
            '<a href="https://nih.gov/">nih</a> <a href="https://bbc.com/">bbc</a> <a href="/rel">rel</a></p>')
    out, kept = launch_engine.clean_links(html, "tshirtcrisis.com", "https://tshirtcrisis.com/money", "T-Shirt Crisis", 2)
    assert out.count("tshirtcrisis.com") == 1 and "https://tshirtcrisis.com/money" in out
    assert kept == ["https://cdc.gov/", "https://nih.gov/"] and "dead.example" not in out and "bbc.com" not in out
    out2, _ = launch_engine.clean_links("<p>no links</p>", "t.com", "https://t.com/", "T", 2)
    assert 'href="https://t.com/"' in out2


def test_anchor_mix_and_money_page():
    from app import launch_engine

    with SessionLocal() as s:
        p = _project(s)
        types = []
        for _ in range(10):
            t, _txt = launch_engine.pick_anchor(s, p, "funny dad shirts for fathers day")
            types.append(t)
            s.add(ContentItem(project_id=p.id, channel="telegraph", content_type="parasite_article", data={"anchor_type": t}))
            s.flush()
        assert types.count("brand") >= 4 and "partial" in types and len(set(types)) >= 3
        assert launch_engine.money_page(p, "funny dad shirts", ["/", "/product-category/dad-shirts/", "/about"]) \
            == "https://tshirtcrisis.com/product-category/dad-shirts/"


def test_autopilot_writes_and_queues(monkeypatch):
    from app import ai, launch_engine, search, worker
    from app.models import Job

    monkeypatch.setattr(search, "autocomplete", lambda seed, expand=True, limit=60: [f"{seed} ideas for dad {i}" for i in range(5)])
    monkeypatch.setattr(launch_engine, "_alive", lambda u: True)
    monkeypatch.setattr(worker, "_site_pages", lambda d, limit=60: ["/", "/dad-shirts/"])
    monkeypatch.setattr(launch_engine, "ensure_telegraph_account", lambda s, p: None)

    def fake_json(prompt, fields, **kw):
        if "keywords" in fields:
            return {"keywords": ["funny shirts", "dad gifts"]}
        return {"title": "Funny Dad Shirt Ideas", "body": "<h2>Ideas</h2><p>Try <a href=\"https://tshirtcrisis.com/\">x</a>.</p>",
                "meta_description": "m", "tags": ["dad"]}
    monkeypatch.setattr(ai, "complete_json", fake_json)
    with SessionLocal() as s:
        p = _project(s, settings={"launch": {"articles_per_run": 3, "parasite_platforms": ["telegraph", "medium"]}})
        out = launch_engine.autopilot(s, p)
        s.flush()
        assert out["keywords"]["added"] >= 3 and out["articles"]["written"] == 3
        items = s.query(ContentItem).filter_by(project_id=p.id, content_type="parasite_article").all()
        assert all(i.data["tier"] == 1 and i.target_url.startswith("https://tshirtcrisis.com/") for i in items)
        assert {i.channel for i in items} <= {"telegraph", "medium"}
        jobs = s.query(Job).filter_by(project_id=p.id, type="publish_content").all()
        assert len(jobs) == sum(1 for i in items if i.channel == "telegraph") and all(i.status == "approved" for i in items
                                                                                      if i.channel == "telegraph")
        assert s.query(Job).filter_by(project_id=p.id, type="launch_indexer").count() == 1
        s.rollback()


def test_publish_creates_tier2_and_skips_tier2_backlinks(monkeypatch):
    from app import ai, launch_engine, worker
    from app.channels import PublishResult, get_channel

    calls = []
    tg = type(get_channel("telegraph"))
    monkeypatch.setattr(tg, "publish", lambda self, item, acct=None, cfg=None: (calls.append(item.channel),
                        PublishResult(True, url=f"https://telegra.ph/p-{len(calls)}", message="ok"))[1])
    monkeypatch.setattr(launch_engine, "ensure_telegraph_account", lambda s, p: None)
    monkeypatch.setattr(ai, "complete_json", lambda *a, **k: {"posts": ["nice read"]})
    with SessionLocal() as s:
        p = _project(s)
        it = ContentItem(project_id=p.id, channel="telegraph", content_type="parasite_article", title="T", body="<p>x</p>",
                         target_url="https://tshirtcrisis.com/", status="approved", data={"tier": 1, "autopilot": True})
        s.add(it)
        s.flush()
        r = worker._publish(s, p, {"content_id": it.id})
        s.flush()
        assert r["ok"] and s.query(EarnedLink).filter_by(project_id=p.id).count() == 1
        t2 = s.query(ContentItem).filter_by(project_id=p.id, content_type="tier2_pointer").all()
        assert len(t2) == 0  # telegraph -> telegraph pointer is skipped (same channel)
        s.add(PlatformAccount(project_id=p.id, platform="bluesky", handle="x.bsky.social"))
        it2 = ContentItem(project_id=p.id, channel="telegraph", content_type="parasite_article", title="T2", body="<p>y</p>",
                          target_url="https://tshirtcrisis.com/", status="approved", data={"tier": 1, "autopilot": True})
        s.add(it2)
        s.flush()
        worker._publish(s, p, {"content_id": it2.id})
        s.flush()
        t2 = s.query(ContentItem).filter_by(project_id=p.id, content_type="tier2_pointer").one()
        assert t2.channel == "bluesky" and it2.published_url in t2.body and t2.data["tier"] == 2
        t2.status = "approved"
        s.flush()
        bsky = type(get_channel("bluesky"))
        monkeypatch.setattr(bsky, "publish", lambda self, item, acct=None, cfg=None: PublishResult(True, url="https://bsky.app/p/1"))
        worker._publish(s, p, {"content_id": t2.id})
        s.flush()
        assert s.query(EarnedLink).filter_by(project_id=p.id).count() == 2  # tier-2 post is not a backlink to us
        s.rollback()


def test_daily_limit_retries_tomorrow():
    from app import worker
    from app.models import ActionLog, Job

    with SessionLocal() as s:
        p = _project(s, settings={"limits": {"per_channel_per_day": {"telegraph": 1}}})
        s.add(ActionLog(project_id=p.id, channel="telegraph"))
        it = ContentItem(project_id=p.id, channel="telegraph", content_type="parasite_article", title="T", body="<p>x</p>",
                         status="approved", data={"tier": 1, "autopilot": True})
        s.add(it)
        s.flush()
        r = worker._publish(s, p, {"content_id": it.id})
        s.flush()
        assert r.get("retry") == "tomorrow" and it.status == "scheduled"
        assert s.query(Job).filter_by(project_id=p.id, type="publish_content").count() == 1
        s.rollback()


def test_learning_shares_proven_sites_across_projects():
    from app import launchkit, learning

    with SessionLocal() as s:
        a = _project(s, niche="funny graphic t-shirts")
        s.add(Opportunity(project_id=a.id, kind="niche_site", key="teeforum.com", domain="teeforum.com", title="Tee Forum",
                          url="https://teeforum.com/", status="done", data={"type": "forum", "tier": "niche"}))
        s.add(EarnedLink(project_id=a.id, source_url="https://teeforum.com/u/tsc", status="live", dofollow=True, score=70))
        s.add(Opportunity(project_id=a.id, kind="niche_site", key="spamfarm.com", domain="spamfarm.com", status="rejected",
                          data={"type": "ugc_blog"}))
        s.flush()
        assert learning.learn(s) == 2
        s.flush()
        b = _project(s, name="Other tees", domain="othertees.com", niche="vintage graphic t-shirts")
        launchkit.seed(s, b)
        s.flush()
        got = s.query(Opportunity).filter_by(project_id=b.id, key="teeforum.com").one()
        assert got.data["learned"] and got.data["link"] == "dofollow" and "1 other project" in got.reason
        assert s.query(Opportunity).filter_by(project_id=b.id, key="spamfarm.com").count() == 0
        c = _project(s, name="Pest", domain="pest.com", type="local", niche="termite pest control")
        launchkit.seed(s, c)
        s.flush()
        assert s.query(Opportunity).filter_by(project_id=c.id, key="teeforum.com").count() == 0  # niche mismatch
        s.rollback()


def test_same_as_collects_profiles():
    from app import launch_engine

    with SessionLocal() as s:
        p = _project(s, settings={"business": {"instagram": "https://instagram.com/tsc"}})
        s.add(Opportunity(project_id=p.id, kind="launch_site", key="gravatar.com", status="done",
                          data={"profile_url": "https://gravatar.com/tsc"}))
        s.flush()
        sa = launch_engine.same_as(s, p)
        assert sa["sameAs"] == ["https://instagram.com/tsc", "https://gravatar.com/tsc"] and sa["@type"] == "Organization"
        s.rollback()


def test_launch_page_and_actions():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.post("/login", data={"email": "admin@test.com", "password": "pw"})
        c.post("/projects", data={"name": "T-Shirt Crisis", "domain": "tshirtcrisis.com"})
        pid = c.get("/api/projects").json()[0]["id"]
        r = c.get(f"/p/{pid}/launch")
        assert r.status_code == 200 and "Run launch autopilot" in r.text and "Blogger" in r.text and "Parasite SEO" in r.text
        with SessionLocal() as s:
            oid = s.query(Opportunity.id).filter_by(project_id=pid, key="gravatar.com").scalar()
        r = c.post(f"/p/{pid}/launch/opp/{oid}", data={"action": "done", "profile_url": "https://gravatar.com/tsc"})
        assert r.status_code == 200 and "https://gravatar.com/tsc" in r.text  # shows in the sameAs schema
        for what in ("autopilot", "niche", "learn"):
            assert c.post(f"/p/{pid}/launch/run/{what}").status_code == 200
        assert c.post(f"/p/{pid}/launch/asset/video").status_code == 200
        assert c.post(f"/p/{pid}/launch/run/nope").status_code == 404
        assert c.get(f"/p/{pid}/settings").status_code == 200 and "Launch Kit" in c.get(f"/p/{pid}/settings").text
        assert "github_pages" in c.get(f"/p/{pid}/accounts").text


@pytest.mark.parametrize("name", ["telegraph", "writeas", "blogger", "wordpress_com", "tumblr", "hashnode", "devto",
                                  "mastodon", "bluesky", "github_pages"])
def test_api_channels_registered_and_fail_cleanly(name):
    from app.channels import get_channel

    ch = get_channel(name)
    assert ch.mode == "api"
    if ch.needs_account:
        res = ch.publish(ContentItem(title="t", body="<p>b</p>"), None, {})
        assert not res.ok and "Accounts" in res.message


def test_publisher_payloads(monkeypatch):
    """Blogger + DEV send the right requests (HTTP mocked)."""
    import httpx

    from app.channels import publishers
    from app.security import encrypt

    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, str(req.url), req.content.decode() if req.content else ""))
        if "oauth2" in str(req.url):
            return httpx.Response(200, json={"access_token": "AT"})
        if "blogger" in str(req.url):
            return httpx.Response(200, json={"url": "https://x.blogspot.com/p.html"})
        return httpx.Response(201, json={"url": "https://dev.to/x/p"})
    real = httpx.Client
    monkeypatch.setattr(publishers, "_http", lambda: real(transport=httpx.MockTransport(handler)))
    acct = PlatformAccount(platform="blogger", secret=encrypt(json.dumps({"username": "cid:csec", "password": "RT"})),
                           data={"host": "123"})
    item = ContentItem(title="Hello", body="<h2>A</h2><p>b</p>", data={"canonical_url": "https://t.com/p"})
    r = publishers.Blogger().publish(item, acct, {})
    assert r.ok and r.url.endswith("p.html") and "blogs/123/posts" in seen[1][1]
    dev = PlatformAccount(platform="devto", secret=encrypt(json.dumps({"password": "KEY"})), data={})
    r = publishers.DevTo().publish(item, dev, {})
    body = json.loads(seen[-1][2])
    assert r.ok and body["article"]["canonical_url"] == "https://t.com/p" and "## A" in body["article"]["body_markdown"]


def test_publish_fail_html_error_shows_title():
    import httpx

    from app.channels.publishers import _fail

    r = httpx.Response(502, text="<!DOCTYPE HTML><html><head><title>A Troubling Question &mdash; Write.as</title>")
    msg = _fail("Write.as", r).message
    assert msg.startswith("Write.as 502: A Troubling Question") and "<" not in msg
