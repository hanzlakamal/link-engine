"""Outreach & PR: contact finding, compliant sending via Brevo, inbox processing.

Every send passes: contact not unsubscribed/bounced -> daily cap (email warm-up ramp) ->
business hours -> unsubscribe link + postal address + List-Unsubscribe header.
"""
from __future__ import annotations

import email
import imaplib
import json
import re
import secrets
from datetime import datetime, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import assert_public_url
from app.classify import domain_of, root_domain
from app.config import get_settings, project_cfg
from app.models import ActionLog, Contact, ContentItem, Opportunity, PlatformAccount, Project, utcnow
from app.security import decrypt

EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK = ("example.", "sentry", "wixpress", ".png", ".jpg", ".gif", "noreply", "no-reply", "privacy@", "abuse@", "u003e")
PREFER = ("editor", "hello", "contact", "press", "pr@", "media", "partnership", "info", "team")


# ------------------------------------------------------------------ contacts
def find_emails_on_site(url: str) -> list[str]:
    base = f"https://{domain_of(url)}"
    found: list[str] = []
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 BuzzScoutsEngine"}) as c:
        for u in (url, base + "/contact", base + "/contact-us", base + "/about", base + "/about-us"):
            try:
                assert_public_url(u)
                r = c.get(u)
            except (ValueError, httpx.HTTPError):
                continue
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            cands = [a["href"][7:].split("?")[0] for a in soup.find_all("a", href=True) if a["href"].startswith("mailto:")]
            cands += EMAIL_RX.findall(soup.get_text(" "))
            for e in cands:
                e = e.strip().lower().rstrip(".")
                if EMAIL_RX.fullmatch(e) and not any(j in e for j in JUNK) and e not in found:
                    found.append(e)
    dom = root_domain(domain_of(url))
    found.sort(key=lambda e: (dom not in e, not any(p in e for p in PREFER)))
    return found


def hunter_emails(domain: str) -> list[tuple[str, str]]:
    key = get_settings().hunter_api_key
    if not key:
        return []
    r = httpx.get("https://api.hunter.io/v2/domain-search", params={"domain": domain, "limit": 5, "api_key": key}, timeout=20)
    if r.status_code != 200:
        return []
    return [(e["value"], " ".join(x for x in (e.get("first_name"), e.get("last_name")) if x))
            for e in r.json().get("data", {}).get("emails", []) if e.get("value")]


def find_contacts(s: Session, project: Project, opp: Opportunity) -> int:
    cfg = project_cfg(project)
    limit = cfg["outreach"]["max_contacts_per_site"]
    found = [(e, "", "page") for e in find_emails_on_site(opp.url or f"https://{opp.domain}")]
    if not found:
        found = [(e, n, "hunter") for e, n in hunter_emails(opp.domain)]
    n = 0
    for e, name, src in found[:limit]:
        if s.scalar(select(Contact).where(Contact.project_id == project.id, Contact.email == e)):
            continue
        s.add(Contact(project_id=project.id, opportunity_id=opp.id, email=e, name=name, domain=opp.domain, source=src,
                      unsub_token=secrets.token_urlsafe(24)))
        n += 1
    opp.data = {**(opp.data or {}), "contacts_found": n}
    return n


# ------------------------------------------------------------------ sending
def _ramp_age_days(s: Session, project_id: int) -> int:
    first = s.scalar(select(func.min(ActionLog.created_at)).where(ActionLog.project_id == project_id, ActionLog.channel == "email"))
    if first is None:
        return 0
    if first.tzinfo is None:
        from datetime import timezone

        first = first.replace(tzinfo=timezone.utc)
    return (utcnow() - first).days


def in_business_hours(cfg: dict) -> bool:
    start, end = cfg["limits"]["business_hours"]
    now = datetime.now(ZoneInfo(cfg["outreach"]["timezone"]))
    return now.weekday() < 5 and start <= now.hour < end


GENERIC_LOCALS = {"info", "hello", "contact", "contacts", "admin", "support", "sales", "office", "team", "mail",
                  "enquiries", "inquiries", "help", "webmaster", "press", "media", "editor", "editors", "news",
                  "marketing", "advertising", "ads", "partnerships", "hi", "general", "service", "noreply", "no-reply"}


def is_generic(email: str) -> bool:
    return (email or "").split("@")[0].lower() in GENERIC_LOCALS


def best_contact(contacts):
    """Pick who to email: a named person beats a role inbox; never unsubscribed/bounced."""
    ok = [c for c in contacts if c.status not in ("unsubscribed", "bounced")]
    return sorted(ok, key=lambda c: (is_generic(c.email), not c.name, c.id))[0] if ok else None


def send_email(s: Session, project: Project, item: ContentItem, test_to: str = "") -> tuple[bool, str, str]:
    """Returns (ok, message, message_id). Caller handles limits/approval state."""
    cfg = project_cfg(project)
    st = get_settings()
    snd = cfg["sender"]
    contact = s.get(Contact, item.contact_id) if item.contact_id else None
    if test_to:  # preview copy to a teammate; never touches the real contact
        from types import SimpleNamespace

        contact = SimpleNamespace(email=test_to, name="", status="new", unsub_token="test-preview")
    if contact is None:
        return False, "No contact on this email. Click 'Find contact' on the opportunity first.", ""
    if contact.status in ("unsubscribed", "bounced"):
        return False, f"Contact is {contact.status}; not sending.", ""
    if not st.brevo_api_key or not snd.get("email"):
        return False, "Set Brevo API key (Global settings) and sender email (project Settings).", ""
    if not snd.get("postal_address"):
        return False, "Set sender postal address in project Settings (legally required in commercial email).", ""
    unsub = f"{st.public_base_url.rstrip('/')}/u/{contact.unsub_token}"
    body = item.body.strip()
    text = f"{body}\n\n--\n{snd['postal_address']}\nNot interested? One click and we won't email again: {unsub}"
    html = "".join(f"<p>{line}</p>" for line in body.split("\n\n")).replace("\n", "<br>")
    html += (f'<p style="color:#888;font-size:12px">{snd["postal_address"]}<br>'
             f'Not interested? <a href="{unsub}">Click here</a> and we won\'t email again.</p>')
    payload = {
        "sender": {"name": snd.get("name") or project.name, "email": snd["email"]},
        "to": [{"email": contact.email, "name": contact.name or contact.email}],
        "subject": ("[TEST] " if test_to else "") + item.title, "htmlContent": html, "textContent": text,
        "headers": {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"},
    }
    if snd.get("reply_to"):
        payload["replyTo"] = {"email": snd["reply_to"]}
    r = httpx.post("https://api.brevo.com/v3/smtp/email", json=payload, timeout=30,
                   headers={"api-key": st.brevo_api_key, "accept": "application/json"})
    if r.status_code >= 300:
        return False, f"Brevo {r.status_code}: {r.text[:200]}", ""
    contact.status, contact.last_contacted = "contacted", utcnow()
    return True, f"Sent to {contact.email}", r.json().get("messageId", "")


def due_followups(s: Session, project: Project) -> list[ContentItem]:
    cfg = project_cfg(project)
    ramp = cfg["limits"]["email_ramp"]
    if not ramp.get("followups"):
        return []
    cutoff = utcnow() - timedelta(days=ramp.get("followup_days", 5))
    out = []
    for it in s.scalars(select(ContentItem).where(ContentItem.project_id == project.id, ContentItem.channel.in_(("email", "outreach_email")),
                        ContentItem.status == "published", ContentItem.updated_at <= cutoff)):
        d = it.data or {}
        if d.get("step", 1) > ramp["followups"] or d.get("followed_up"):
            continue
        c = s.get(Contact, it.contact_id) if it.contact_id else None
        if c and c.status == "contacted":
            out.append(it)
    return out


# ------------------------------------------------------------------ inbox
def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return (part.get_payload(decode=True) or b"").decode(errors="replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return BeautifulSoup((part.get_payload(decode=True) or b"").decode(errors="replace"), "html.parser").get_text(" ")
        return ""
    return (msg.get_payload(decode=True) or b"").decode(errors="replace")


def read_inbox(account: PlatformAccount, wanted, days: int = 14, skip_ids: set | None = None) -> list[dict]:
    """Read-only: never changes read/unread flags (it may be a person's real inbox).

    Headers are peeked first; full bodies are fetched only for senders `wanted(from_addr)` accepts
    (known contacts, journalist-request services). `skip_ids` = Message-IDs already processed.
    """
    creds = json.loads(decrypt(account.secret) or "{}")
    host = (account.data or {}).get("host") or "imap.gmail.com"
    m = imaplib.IMAP4_SSL(host, 993, timeout=30)
    m.login(creds.get("username", ""), creds.get("password", ""))
    m.select("INBOX", readonly=True)
    since = (utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, ids = m.search(None, f'(SINCE "{since}")')
    out = []
    for i in (ids[0].split() if ids and ids[0] else [])[-300:]:
        _, data = m.fetch(i, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)])")
        head = email.message_from_bytes(data[0][1])
        sender, mid = parseaddr(head.get("From", ""))[1].lower(), head.get("Message-ID", "").strip()
        if (skip_ids and mid in skip_ids) or not wanted(sender):
            continue
        _, data = m.fetch(i, "(BODY.PEEK[])")
        msg = email.message_from_bytes(data[0][1])
        out.append({"from": sender, "subject": str(msg.get("Subject", "")), "body": _body(msg)[:6000],
                    "message_id": mid})
    m.logout()
    return out


EMAIL_RE = re.compile(r"[^@\s,;<>]+@[^@\s,;<>]+\.[a-z]{2,}", re.I)


def import_contacts_csv(s: Session, project: Project, text: str, create_opps: bool = True, max_rows: int = 20000) -> dict:
    """Bulk-add contacts from a CSV (or one email per line).

    Columns (any subset, any order, case-insensitive): email, name / first_name + last_name, website / url / domain,
    outlet / publication, notes. Each contact is linked to the opportunity for the same site (matched by root domain)
    so Opportunities and Outreach stay in sync. Sites with no opportunity get one (kind 'outreach_list') when
    create_opps is on, so you can Draft from either tab.
    """
    import csv
    import io
    import secrets as _s

    from app.classify import domain_of, root_domain
    from app.models import Opportunity

    text = text.lstrip("\ufeff")
    first = text.splitlines()[0] if text.strip() else ""
    has_header = "@" not in first
    rows = csv.DictReader(io.StringIO(text)) if has_header else ({"email": ln} for ln in text.splitlines())
    opps = {}
    for o in s.scalars(select(Opportunity).where(Opportunity.project_id == project.id,
                                                 Opportunity.status != "rejected").order_by(Opportunity.score)):
        if o.domain:
            opps[root_domain(domain_of(o.domain))] = o  # highest score wins (ordered ascending)
    existing = {e.lower() for e in s.scalars(select(Contact.email).where(Contact.project_id == project.id))}
    out = {"added": 0, "linked": 0, "new_opportunities": 0, "duplicates": 0, "invalid": 0}
    for i, row in enumerate(rows):
        if i >= max_rows:
            break
        low = {(k or "").strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items() if k}
        m = EMAIL_RE.search(low.get("email") or low.get("email_address") or low.get("e-mail") or "")
        if not m:
            out["invalid"] += 1
            continue
        e = m.group(0).lower()
        if e in existing:
            out["duplicates"] += 1
            continue
        existing.add(e)
        name = low.get("name") or " ".join(x for x in (low.get("first_name", ""), low.get("last_name", "")) if x)
        site = low.get("website") or low.get("url") or low.get("domain") or low.get("site") or ""
        host = domain_of(site) if site else e.split("@")[1]
        rd = root_domain(host)
        opp = opps.get(rd)
        if opp is None and create_opps and site:
            opp = Opportunity(project_id=project.id, kind="outreach_list", key=rd, domain=host,
                              url=site if "://" in site else f"https://{host}", score=50,
                              title=low.get("outlet") or low.get("publication") or host,
                              reason=low.get("notes", "")[:500] or "Imported contact list", data={"source": "import"})
            s.add(opp)
            s.flush()
            opps[rd] = opp
            out["new_opportunities"] += 1
        s.add(Contact(project_id=project.id, email=e, name=name[:200], domain=host, source="import",
                      opportunity_id=opp.id if opp else None, unsub_token=_s.token_urlsafe(24),
                      data={"outlet": low.get("outlet") or low.get("publication", ""), "notes": low.get("notes", "")[:500]}))
        out["added"] += 1
        out["linked"] += 1 if opp else 0
    return out
