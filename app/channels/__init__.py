"""Publishing channels.

v1: every channel works in *assisted* mode — the tool drafts the content, you approve,
then click "Open & copy" which opens the platform with text on your clipboard, and paste
the published URL back (the link monitor takes over from there).

TODO(upgrade): API publishers — Tumblr, Blogger, WordPress.com, DEV, Reddit, Pinterest,
LinkedIn, Brevo email — each a subclass overriding `publish()`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.registry import channels

COMPOSE_URLS = {
    "medium": "https://medium.com/new-story",
    "quora": "https://www.quora.com/answer",
    "reddit": "https://www.reddit.com/submit",
    "pinterest": "https://www.pinterest.com/pin-creation-tool/",
    "tumblr": "https://www.tumblr.com/new/text",
    "blogger": "https://www.blogger.com/",
    "linkedin": "https://www.linkedin.com/article/new/",
    "substack": "https://substack.com/",
    "behance": "https://www.behance.net/portfolio/editor",
}


@dataclass
class PublishResult:
    ok: bool
    url: str = ""
    message: str = ""


class Channel:
    name = "base"
    mode = "assisted"  # assisted | api

    def compose_url(self) -> str:
        return COMPOSE_URLS.get(self.name, "")

    def publish(self, item, account=None, cfg=None) -> PublishResult:
        return PublishResult(False, message="Assisted channel: open compose page, paste, then save the live URL.")


def get_channel(name: str) -> Channel:
    try:
        return channels.get(name)()
    except KeyError:
        ch = Channel()
        ch.name = name
        return ch


for _n in list(COMPOSE_URLS) + ["instagram", "tiktok", "facebook", "youtube", "x", "profile", "directory", "forum"]:
    channels.register(_n)(type(f"{_n.title()}Channel", (Channel,), {}))


HUB_PLATFORMS = ("wordpress_hub", "shopify_hub")


@channels.register("own_blog")
class OwnBlog(Channel):
    """The client's own blog (content hub): WordPress (REST + application password) or Shopify (Admin API)."""

    mode = "api"

    def publish(self, item, account=None, cfg=None) -> PublishResult:
        import json

        import httpx

        from app.auth import assert_public_url
        from app.security import decrypt

        if account is None:
            return PublishResult(False, message="No blog hub connected (Accounts tab: wordpress_hub or shopify_hub).")
        creds = json.loads(decrypt(account.secret) or "{}")
        site = (account.data or {}).get("site_url", "").rstrip("/")
        pub = (cfg or {}).get("publishing", {})
        live = pub.get("own_blog_status", "publish") == "publish"
        try:
            assert_public_url(site)
        except ValueError as e:
            return PublishResult(False, message=str(e))
        with httpx.Client(timeout=60, headers={"User-Agent": "BuzzScoutsEngine/2.0"}) as c:
            if account.platform == "shopify_hub":
                ver = pub.get("shopify_api_version", "2026-01")
                h = {"X-Shopify-Access-Token": creds.get("password", ""), "Content-Type": "application/json"}
                blogs = c.get(f"{site}/admin/api/{ver}/blogs.json", headers=h)
                if blogs.status_code >= 300 or not blogs.json().get("blogs"):
                    return PublishResult(False, message=f"Shopify blogs {blogs.status_code}: {blogs.text[:160]}")
                want = pub.get("shopify_blog_handle")
                blog = next((b for b in blogs.json()["blogs"] if b["handle"] == want), blogs.json()["blogs"][0])
                r = c.post(f"{site}/admin/api/{ver}/blogs/{blog['id']}/articles.json", headers=h,
                           json={"article": {"title": item.title, "body_html": item.body, "published": live}})
                if r.status_code >= 300:
                    return PublishResult(False, message=f"Shopify {r.status_code}: {r.text[:200]}")
                a = r.json()["article"]
                public = (account.data or {}).get("public_url", "").rstrip("/") or site
                return PublishResult(True, url=f"{public}/blogs/{blog['handle']}/{a['handle']}", message=f"Shopify article {a['id']}")
            auth = (creds.get("username", ""), creds.get("password", ""))
            payload = {"title": item.title, "content": item.body, "status": "publish" if live else "draft"}
            cat = pub.get("own_blog_category")
            if cat:
                r = c.get(f"{site}/wp-json/wp/v2/categories", params={"search": cat}, auth=auth)
                if r.status_code == 200 and r.json():
                    payload["categories"] = [r.json()[0]["id"]]
            r = c.post(f"{site}/wp-json/wp/v2/posts", json=payload, auth=auth)
        if r.status_code >= 300:
            return PublishResult(False, message=f"WordPress {r.status_code}: {r.text[:200]}")
        d = r.json()
        return PublishResult(True, url=d.get("link", ""), message=f"WordPress post {d.get('id')} ({d.get('status')})")


def test_hub(account) -> str:
    import json

    import httpx

    from app.auth import assert_public_url
    from app.security import decrypt

    creds = json.loads(decrypt(account.secret) or "{}")
    site = (account.data or {}).get("site_url", "").rstrip("/")
    try:
        assert_public_url(site)
        if account.platform == "shopify_hub":
            r = httpx.get(f"{site}/admin/api/2026-01/shop.json", timeout=30,
                          headers={"X-Shopify-Access-Token": creds.get("password", "")})
            return "OK: " + r.json()["shop"]["name"] if r.status_code == 200 else f"FAILED {r.status_code}"
        r = httpx.get(f"{site}/wp-json/wp/v2/users/me", timeout=30, auth=(creds.get("username", ""), creds.get("password", "")))
        return "OK as " + r.json().get("name", "") if r.status_code == 200 else f"FAILED {r.status_code}"
    except (ValueError, httpx.HTTPError, KeyError) as e:
        return f"FAILED: {e}"


@channels.register("outreach_email")
class OutreachEmail(Channel):
    """Personal outreach email sent through Brevo with compliance footer."""

    mode = "api"


channels.register("email")(type("LegacyEmailChannel", (OutreachEmail,), {}))  # drafts made before the upgrade
