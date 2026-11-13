"""API publishers for launch-kit platforms. Each takes an approved ContentItem and posts it.

Credentials live in PlatformAccount.secret (encrypted JSON) and .data, entered on the Accounts tab:
  telegraph     no setup: an account is created automatically on first publish (token saved)
  writeas       optional token (password field); empty = anonymous post
  blogger       data.host = blog ID; secret: username = OAuth client_id:client_secret, password = refresh token
  wordpress_com data.site_url = yoursite.wordpress.com; password = OAuth2 access token
  tumblr        handle = blog name; username = consumer_key:consumer_secret, password = token:token_secret (OAuth1)
  hashnode      data.host = publication ID; password = personal access token
  devto         password = API key
  mastodon      data.site_url = instance (https://mastodon.social); password = access token
  bluesky       handle = you.bsky.social; password = app password
  github_pages  handle = GitHub user; data.host = repo (default <user>.github.io); password = token (contents:write)

Every publisher returns PublishResult; failures never raise into the worker.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone

import httpx

from app.channels import Channel, PublishResult
from app.htmlconv import to_markdown, to_telegraph_nodes, to_text
from app.registry import channels

UA = {"User-Agent": "BuzzScoutsEngine/2.0"}


def _creds(account) -> dict:
    from app.security import decrypt

    if account is None or not account.secret:
        return {}
    try:
        return json.loads(decrypt(account.secret) or "{}")
    except (ValueError, TypeError):
        return {}


def _data(account) -> dict:
    return (account.data or {}) if account is not None else {}


def _canonical(item) -> str:
    return (item.data or {}).get("canonical_url", "")


def _http() -> httpx.Client:
    return httpx.Client(timeout=60, headers=UA, follow_redirects=True)


def _fail(name: str, r: httpx.Response) -> PublishResult:
    text = r.text or ""
    if "<html" in text[:500].lower():  # error/challenge page: keep its title, not the markup
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
        title = re.sub(r"&[a-z#0-9]+;", " ", m.group(1)).strip() if m else "HTML error page"
        hint = " (site may be down or blocking automated posts; Retry later)" if r.status_code >= 500 else ""
        return PublishResult(False, message=f"{name} {r.status_code}: {' '.join(title.split())}{hint}")
    return PublishResult(False, message=f"{name} {r.status_code}: {text[:200]}")


class ApiChannel(Channel):
    mode = "api"
    needs_account = True

    def publish(self, item, account=None, cfg=None) -> PublishResult:
        if self.needs_account and account is None:
            return PublishResult(False, message=f"Connect a {self.name} account on the Accounts tab first.")
        try:
            return self._publish(item, account, cfg or {})
        except httpx.HTTPError as e:
            return PublishResult(False, message=f"{self.name}: {e}")
        except (KeyError, ValueError, TypeError) as e:
            return PublishResult(False, message=f"{self.name}: unexpected response ({e})")

    def _publish(self, item, account, cfg) -> PublishResult:  # pragma: no cover - abstract
        raise NotImplementedError


@channels.register("telegraph")
class Telegraph(ApiChannel):
    needs_account = False

    def _publish(self, item, account, cfg):
        token = _creds(account).get("password", "")
        with _http() as c:
            if not token:
                token = create_telegraph_token(c, (cfg.get("business", {}) or {}).get("business_name") or "Editor")
            r = c.post("https://api.telegra.ph/createPage", data={
                "access_token": token, "title": item.title[:256] or "Untitled",
                "author_name": (cfg.get("business", {}) or {}).get("business_name", "")[:128],
                "author_url": (item.data or {}).get("author_url", ""),
                "content": json.dumps(to_telegraph_nodes(item.body))[:64000], "return_content": "false"})
            body = r.json()
        if not body.get("ok"):
            return PublishResult(False, message=f"Telegraph: {body.get('error')}")
        return PublishResult(True, url=body["result"]["url"], message="Telegraph page created")


def create_telegraph_token(c: httpx.Client, author: str) -> str:
    r = c.post("https://api.telegra.ph/createAccount", data={"short_name": author[:32], "author_name": author[:128]})
    body = r.json()
    if not body.get("ok"):
        raise ValueError(f"Telegraph account: {body.get('error')}")
    return body["result"]["access_token"]


@channels.register("writeas")
class WriteAs(ApiChannel):
    needs_account = False

    def _publish(self, item, account, cfg):
        token = _creds(account).get("password", "")
        h = {"Content-Type": "application/json", **({"Authorization": f"Token {token}"} if token else {})}
        with _http() as c:
            r = c.post("https://write.as/api/posts", headers=h,
                       json={"title": item.title, "body": to_markdown(item.body), "font": "norm"})
        if r.status_code >= 300:
            return _fail("Write.as", r)
        d = r.json()["data"]
        url = f"https://write.as/{d['id']}"
        return PublishResult(True, url=url, message="Write.as post" + ("" if token else " (anonymous)"))


@channels.register("blogger")
class Blogger(ApiChannel):
    def _publish(self, item, account, cfg):
        cr = _creds(account)
        client_id, _, client_secret = (cr.get("username") or "").partition(":")
        blog_id = _data(account).get("host", "")
        if not (client_id and client_secret and cr.get("password") and blog_id):
            return PublishResult(False, message="Blogger needs blog ID (host), client_id:client_secret (username) and refresh token (password).")
        with _http() as c:
            t = c.post("https://oauth2.googleapis.com/token", data={
                "client_id": client_id, "client_secret": client_secret, "refresh_token": cr["password"],
                "grant_type": "refresh_token"})
            if t.status_code >= 300:
                return _fail("Google OAuth", t)
            r = c.post(f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/",
                       headers={"Authorization": f"Bearer {t.json()['access_token']}"},
                       json={"kind": "blogger#post", "title": item.title, "content": item.body,
                             "labels": (item.data or {}).get("tags", [])[:5]})
        if r.status_code >= 300:
            return _fail("Blogger", r)
        return PublishResult(True, url=r.json()["url"], message="Blogger post published")


@channels.register("wordpress_com")
class WordPressCom(ApiChannel):
    def _publish(self, item, account, cfg):
        site = (_data(account).get("site_url") or "").replace("https://", "").replace("http://", "").strip("/")
        token = _creds(account).get("password", "")
        if not (site and token):
            return PublishResult(False, message="WordPress.com needs site (site_url) and OAuth token (password).")
        with _http() as c:
            r = c.post(f"https://public-api.wordpress.com/rest/v1.1/sites/{site}/posts/new",
                       headers={"Authorization": f"Bearer {token}"},
                       data={"title": item.title, "content": item.body, "status": "publish",
                             "tags": ",".join((item.data or {}).get("tags", [])[:5])})
        if r.status_code >= 300:
            return _fail("WordPress.com", r)
        return PublishResult(True, url=r.json()["URL"], message="WordPress.com post published")


@channels.register("tumblr")
class Tumblr(ApiChannel):
    def compose_url(self) -> str:
        return "https://www.tumblr.com/new/text"

    def _publish(self, item, account, cfg):
        """OAuth 1.0a (tokens never expire): username = consumer_key:consumer_secret, password = token:token_secret.
        A plain password without ':' is sent as an OAuth2 bearer token (those expire after ~40 minutes)."""
        blog = (account.handle or "").strip().removeprefix("https://www.tumblr.com/blog/").strip("/")
        cr = _creds(account)
        user, pw = cr.get("username", ""), cr.get("password", "")
        if not (blog and pw):
            return PublishResult(False, message="Tumblr needs the blog name (handle) and tokens (see Accounts help).")
        blog = blog if "." in blog else f"{blog}.tumblr.com"
        url = f"https://api.tumblr.com/v2/blog/{blog}/post"
        body = {"type": "text", "title": item.title, "body": item.body, "format": "html",
                "tags": ",".join((item.data or {}).get("tags", [])[:5])}
        if ":" in user and ":" in pw:
            ck, cs = user.split(":", 1)
            tk, ts = pw.split(":", 1)
            headers = {"Authorization": _oauth1_header("POST", url, body, ck.strip(), cs.strip(), tk.strip(), ts.strip())}
        else:
            headers = {"Authorization": f"Bearer {pw}"}
        with _http() as c:
            r = c.post(url, headers=headers, data=body)
        if r.status_code >= 300:
            return _fail("Tumblr", r)
        resp = r.json()["response"]
        pid = resp.get("id_string") or resp.get("id")
        return PublishResult(True, url=f"https://{blog}/post/{pid}", message="Tumblr post published")


def _oauth1_header(method: str, url: str, params: dict, ck: str, cs: str, tk: str, ts: str) -> str:
    import hashlib
    import hmac
    import secrets
    import time
    from urllib.parse import quote

    def enc(x) -> str:
        return quote(str(x), safe="~-._")

    oauth = {"oauth_consumer_key": ck, "oauth_nonce": secrets.token_hex(16), "oauth_signature_method": "HMAC-SHA1",
             "oauth_timestamp": str(int(time.time())), "oauth_token": tk, "oauth_version": "1.0"}
    allp = sorted((enc(k), enc(v)) for k, v in {**params, **oauth}.items())
    base = "&".join([method, enc(url), enc("&".join(f"{k}={v}" for k, v in allp))])
    sig = base64.b64encode(hmac.new(f"{enc(cs)}&{enc(ts)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in oauth.items())


@channels.register("hashnode")
class Hashnode(ApiChannel):
    def _publish(self, item, account, cfg):
        token, pub = _creds(account).get("password", ""), _data(account).get("host", "")
        if not (token and pub):
            return PublishResult(False, message="Hashnode needs publication ID (host) and a personal access token (password).")
        inp = {"title": item.title, "contentMarkdown": to_markdown(item.body), "publicationId": pub, "tags": []}
        if _canonical(item):
            inp["originalArticleURL"] = _canonical(item)
        q = "mutation P($input: PublishPostInput!){publishPost(input:$input){post{url}}}"
        with _http() as c:
            r = c.post("https://gql.hashnode.com/", headers={"Authorization": token},
                       json={"query": q, "variables": {"input": inp}})
        body = r.json()
        if r.status_code >= 300 or body.get("errors"):
            return PublishResult(False, message=f"Hashnode: {str(body.get('errors') or r.text)[:200]}")
        return PublishResult(True, url=body["data"]["publishPost"]["post"]["url"], message="Hashnode post published")


@channels.register("devto")
class DevTo(ApiChannel):
    def _publish(self, item, account, cfg):
        key = _creds(account).get("password", "")
        if not key:
            return PublishResult(False, message="DEV needs an API key (password).")
        art = {"title": item.title, "body_markdown": to_markdown(item.body), "published": True,
               "tags": [re.sub(r"[^a-z0-9]", "", t.lower()) for t in (item.data or {}).get("tags", [])][:4]}
        if _canonical(item):
            art["canonical_url"] = _canonical(item)
        with _http() as c:
            r = c.post("https://dev.to/api/articles", headers={"api-key": key}, json={"article": art})
        if r.status_code >= 300:
            return _fail("DEV", r)
        return PublishResult(True, url=r.json()["url"], message="DEV article published")


@channels.register("mastodon")
class Mastodon(ApiChannel):
    def _publish(self, item, account, cfg):
        inst = (_data(account).get("site_url") or "https://mastodon.social").rstrip("/")
        token = _creds(account).get("password", "")
        if not token:
            return PublishResult(False, message="Mastodon needs an access token (password).")
        text = to_text(item.body)[:480]
        with _http() as c:
            r = c.post(f"{inst}/api/v1/statuses", headers={"Authorization": f"Bearer {token}"}, data={"status": text})
        if r.status_code >= 300:
            return _fail("Mastodon", r)
        return PublishResult(True, url=r.json()["url"], message="Mastodon post")


@channels.register("bluesky")
class Bluesky(ApiChannel):
    def _publish(self, item, account, cfg):
        handle, pw = (account.handle or "").lstrip("@"), _creds(account).get("password", "")
        if not (handle and pw):
            return PublishResult(False, message="Bluesky needs handle and an app password (password).")
        text = to_text(item.body)[:290]
        facets = []
        for m in re.finditer(r"https?://\S+", text):
            b0 = len(text[:m.start()].encode())
            facets.append({"index": {"byteStart": b0, "byteEnd": b0 + len(m.group(0).encode())},
                           "features": [{"$type": "app.bsky.richtext.facet#link", "uri": m.group(0)}]})
        with _http() as c:
            sess = c.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                          json={"identifier": handle, "password": pw})
            if sess.status_code >= 300:
                return _fail("Bluesky login", sess)
            sd = sess.json()
            rec = {"$type": "app.bsky.feed.post", "text": text, "createdAt": datetime.now(timezone.utc).isoformat()}
            if facets:
                rec["facets"] = facets
            r = c.post("https://bsky.social/xrpc/com.atproto.repo.createRecord",
                       headers={"Authorization": f"Bearer {sd['accessJwt']}"},
                       json={"repo": sd["did"], "collection": "app.bsky.feed.post", "record": rec})
        if r.status_code >= 300:
            return _fail("Bluesky", r)
        rkey = r.json()["uri"].rsplit("/", 1)[-1]
        return PublishResult(True, url=f"https://bsky.app/profile/{handle}/post/{rkey}", message="Bluesky post")


@channels.register("github_pages")
class GitHubPages(ApiChannel):
    """Writes item.body as an HTML page into the user's Pages repo. data.path picks the file (default: slug)."""

    def _publish(self, item, account, cfg):
        user, token = (account.handle or "").strip(), _creds(account).get("password", "")
        repo = _data(account).get("host") or f"{user}.github.io"
        if not (user and token):
            return PublishResult(False, message="GitHub Pages needs your user (handle) and a token (password).")
        path = (item.data or {}).get("path") or (re.sub(r"[^a-z0-9]+", "-", item.title.lower()).strip("-")[:60] or "page") + ".html"
        html = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" "
                "content=\"width=device-width,initial-scale=1\"><title>" + item.title.replace("<", "") + "</title>"
                "<style>body{max-width:760px;margin:40px auto;padding:0 16px;font:17px/1.6 system-ui,sans-serif;color:#222}"
                "a{color:#2b59c3}</style></head><body><h1>" + item.title.replace("<", "") + "</h1>" + item.body + "</body></html>")
        api = f"https://api.github.com/repos/{user}/{repo}/contents/{path}"
        h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        with _http() as c:
            cur = c.get(api, headers=h)
            payload = {"message": f"Update {path}", "content": base64.b64encode(html.encode()).decode()}
            if cur.status_code == 200:
                payload["sha"] = cur.json()["sha"]
            r = c.put(api, headers=h, json=payload)
        if r.status_code >= 300:
            return _fail("GitHub", r)
        base = f"https://{repo}" if repo.endswith(".github.io") else f"https://{user}.github.io/{repo}"
        return PublishResult(True, url=f"{base}/{path}", message="GitHub Pages file written")


API_CHANNELS = {"telegraph", "writeas", "blogger", "wordpress_com", "tumblr", "hashnode", "devto", "mastodon", "bluesky",
                "github_pages"}
