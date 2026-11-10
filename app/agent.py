"""AI teammate: Claude works through one project using the engine's own actions as tools.

Started by a person ("Run AI teammate"), never on a schedule. Every run:
  inbox -> pick opportunities -> contacts -> pitches -> review & approve (within autonomy rules) -> social scan
  -> pins -> hand human-only work to the assigned employee -> leave a briefing.

Guardrails (enforced in code, not just in the prompt):
- daily spend cap per project (all Claude calls during the run are metered)
- auto-approve only for channels listed in settings (default: outreach email, own blog, pins) and only when
  the draft has no placeholders, the sender has a real name/address, and an email has a recipient
- sending still goes through the normal jobs, so frequency limits, warm-up and business hours apply
- never creates accounts or posts on Reddit/Quora/directories: those are handed to a human
- Stop button: checked before every step
"""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai, pipeline
from app.config import get_settings, project_cfg
from app.models import (ApiUsage, Contact, ContentItem, EarnedLink, Job, Opportunity, PlatformAccount, Project,
                        ProjectMember, Task, User, utcnow)

AGENT_EMAIL = "ai-teammate@agent.invalid"
MAIL = ("outreach_email", "email")
PLACEHOLDER_RE = re.compile(r"\[[^\]\n]{1,60}\]|\{\{?[^}\n]{1,60}\}?\}|<\s*(name|first name|your name|company)\s*>|"
                            r"\b(your name|first name here|insert [a-z ]+|lorem ipsum|TBD|XXX+)\b", re.I)


def placeholders(text: str) -> list[str]:
    return sorted({m.group(0) for m in PLACEHOLDER_RE.finditer(text or "")})[:5]


def agent_user(s: Session, project: Project) -> User:
    name = project_cfg(project).get("agent", {}).get("display_name") or "AI teammate"
    u = s.scalar(select(User).where(User.email == AGENT_EMAIL))
    if u is None:  # cannot log in: no valid password hash
        u = User(email=AGENT_EMAIL, name=name, role="builder", password_hash="!", active=True)
        s.add(u)
        s.flush()
    elif u.name != name:
        u.name = name
    return u


def spent_today(s: Session, pid: int) -> float:
    start = datetime.combine(utcnow().date(), time(0), tzinfo=timezone.utc)
    return float(s.scalar(select(func.coalesce(func.sum(ApiUsage.units), 0)).where(
        ApiUsage.project_id == pid, ApiUsage.provider == "claude_agent", ApiUsage.created_at >= start)) or 0)


# ------------------------------------------------------------------ tools
TOOLS = [
    {"name": "get_status", "description": "Project snapshot: opportunity counts, drafts waiting, replies, links, social, pins, "
     "sender readiness, autonomy rules and budget left. Call first.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "check_inbox", "description": "Read the reply inbox: classifies replies, drafts responses, captures journalist "
     "requests.", "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_opportunities", "description": "Best untouched opportunities (status new). Optional kind filter "
     "(link_gap, gift_guide, roundup, blogger_review, pr_target, charity, vendor_case_study, outreach_list, self_publish).",
     "input_schema": {"type": "object", "properties": {"kind": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "find_contacts", "description": "Find editor emails for an outreach opportunity (not for self_publish).",
     "input_schema": {"type": "object", "properties": {"opportunity_id": {"type": "integer"}}, "required": ["opportunity_id"]}},
    {"name": "draft_pitch", "description": "Draft the outreach email for an opportunity that has a contact. Returns the draft id "
     "and text so you can review it.", "input_schema": {"type": "object", "properties": {"opportunity_id": {"type": "integer"}},
                                                        "required": ["opportunity_id"]}},
    {"name": "list_drafts", "description": "Drafts waiting for approval (emails, replies, blog articles, posts).",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "revise_draft", "description": "Rewrite a waiting draft's subject/body yourself (fix placeholders, tone, facts).",
     "input_schema": {"type": "object", "properties": {"item_id": {"type": "integer"}, "title": {"type": "string"},
                                                       "body": {"type": "string"}}, "required": ["item_id", "body"]}},
    {"name": "approve_draft", "description": "Approve a waiting draft so it sends/publishes through the normal limits. Refused "
     "if the channel isn't allowed for auto-approval, it has placeholders, or sender details are missing.",
     "input_schema": {"type": "object", "properties": {"item_id": {"type": "integer"}}, "required": ["item_id"]}},
    {"name": "reject_draft", "description": "Reject a weak or off-target draft.",
     "input_schema": {"type": "object", "properties": {"item_id": {"type": "integer"}, "reason": {"type": "string"}},
                      "required": ["item_id"]}},
    {"name": "draft_blog_article", "description": "Draft one article for the brand's own blog (topic you choose from the season "
     "and brand). Use at most once per run.", "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}},
                                                               "required": ["topic"]}},
    {"name": "build_pins", "description": "Create Pinterest pins from product pages not pinned yet (max 10 per call).",
     "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    {"name": "approve_pins", "description": "Approve all pins waiting (placeholder-checked).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "scan_social", "description": "Start a Reddit/Quora scan; drafts land in the Social tab for a human to post.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "hand_to_human", "description": "Assign an opportunity that needs a person (sign-up, Reddit/Quora, directory, "
     "phone, samples) to the project's human teammate with a short instruction.",
     "input_schema": {"type": "object", "properties": {"opportunity_id": {"type": "integer"}, "note": {"type": "string"}},
                      "required": ["opportunity_id", "note"]}},
    {"name": "finish", "description": "End the run with a briefing for the team: what you did, what's waiting for approval, "
     "what needs a human (and why), and recommended next steps. Plain sentences, no placeholders.",
     "input_schema": {"type": "object", "properties": {"briefing": {"type": "string"},
                                                       "needs_human": {"type": "array", "items": {"type": "string"}}},
                      "required": ["briefing"]}},
]


class Run:
    def __init__(self, s: Session, project: Project, job_id: int | None, started_by: int | None):
        self.s, self.p, self.job_id, self.started_by = s, project, job_id, started_by
        self.cfg = project_cfg(project)
        self.acfg = self.cfg.get("agent", {})
        self.me = agent_user(s, project)
        self.log: list[str] = []
        self.brief: dict | None = None
        self.counts = {"pitches": 0, "approved": 0, "articles": 0}

    # ---- helpers
    def _humans(self) -> list[User]:
        ids = set(self.s.scalars(select(ProjectMember.user_id).where(ProjectMember.project_id == self.p.id)))
        return [u for u in self.s.scalars(select(User).where(User.id.in_(ids or {0}), User.active.is_(True)))
                if u.email != AGENT_EMAIL and u.role == "builder"]

    def _sender_ready(self) -> list[str]:
        snd, miss = self.cfg["sender"], []
        if not (snd.get("name") or "").strip():
            miss.append("sender name")
        if not snd.get("email"):
            miss.append("sender email")
        if not snd.get("postal_address"):
            miss.append("postal address")
        if not get_settings().brevo_api_key:
            miss.append("Brevo API key")
        return miss

    def _item(self, iid: int) -> ContentItem:
        it = self.s.get(ContentItem, int(iid))
        if not it or it.project_id != self.p.id:
            raise ValueError("draft not found in this project")
        return it

    def _opp(self, oid: int) -> Opportunity:
        o = self.s.get(Opportunity, int(oid))
        if not o or o.project_id != self.p.id:
            raise ValueError("opportunity not found in this project")
        return o

    # ---- tools
    def get_status(self) -> dict:
        s, pid = self.s, self.p.id
        opp = dict(s.execute(select(Opportunity.status, func.count()).where(Opportunity.project_id == pid)
                             .group_by(Opportunity.status)).all())
        new_by_kind = dict(s.execute(select(Opportunity.kind, func.count()).where(
            Opportunity.project_id == pid, Opportunity.status == "new").group_by(Opportunity.kind)).all())
        content = dict(s.execute(select(ContentItem.status, func.count()).where(ContentItem.project_id == pid)
                                 .group_by(ContentItem.status)).all())
        return {
            "brand": self.cfg["business"].get("business_name") or self.p.name, "domain": self.p.domain,
            "stage": self.p.stage, "type": self.p.type, "niche": self.p.niche,
            "today": utcnow().date().isoformat(),
            "opportunities": opp, "new_by_kind": new_by_kind, "drafts": content,
            "replied_contacts": s.scalar(select(func.count()).select_from(Contact).where(
                Contact.project_id == pid, Contact.status == "replied")) or 0,
            "live_links": s.scalar(select(func.count()).select_from(EarnedLink).where(
                EarnedLink.project_id == pid, EarnedLink.status == "live")) or 0,
            "open_tasks": s.scalar(select(func.count()).select_from(Task).where(
                Task.project_id == pid, Task.status.in_(("todo", "doing")))) or 0,
            "inbox_connected": bool(s.scalar(select(PlatformAccount.id).where(
                PlatformAccount.project_id == pid, PlatformAccount.platform == "imap_inbox").limit(1))),
            "social_connected": bool(s.scalar(select(PlatformAccount.id).where(
                PlatformAccount.project_id == pid, PlatformAccount.platform == "social_engine").limit(1))),
            "sender_missing": self._sender_ready(),
            "auto_send": bool(self.acfg.get("auto_send", True)), "auto_channels": self.acfg.get("auto_channels", []),
            "max_pitches_per_run": int(self.acfg.get("max_pitches_per_run", 5)),
            "human_teammates": [u.name or u.email for u in self._humans()],
            "budget_left_usd": round(float(self.acfg.get("daily_budget_usd", 2)) - spent_today(s, pid), 2),
        }

    def check_inbox(self) -> dict:
        from app.worker import HANDLERS

        return HANDLERS["check_inbox"](self.s, self.p, {})

    def list_opportunities(self, kind: str = "", limit: int = 10) -> list[dict]:
        q = select(Opportunity).where(Opportunity.project_id == self.p.id, Opportunity.status == "new")
        if kind:
            q = q.where(Opportunity.kind == kind)
        rows = self.s.scalars(q.order_by(Opportunity.score.desc()).limit(min(int(limit or 10), 20))).all()
        has = set(self.s.scalars(select(Contact.opportunity_id).where(Contact.opportunity_id.in_([o.id for o in rows] or [0]))))
        return [{"id": o.id, "kind": o.kind, "domain": o.domain, "title": o.title[:120], "score": round(o.score or 0, 1),
                 "why": (o.reason or "")[:160], "has_contact": o.id in has, "assigned": bool(o.assigned_to),
                 "category": (o.data or {}).get("category")} for o in rows]

    def find_contacts(self, opportunity_id: int) -> dict:
        from app import outreach

        o = self._opp(opportunity_id)
        if o.kind == "self_publish":
            return {"error": "self_publish sites need a human sign-up; use hand_to_human"}
        return {"found": outreach.find_contacts(self.s, self.p, o)}

    def draft_pitch(self, opportunity_id: int) -> dict:
        from app.worker import HANDLERS

        if self.counts["pitches"] >= int(self.acfg.get("max_pitches_per_run", 5)):
            return {"error": "pitch limit for this run reached"}
        o = self._opp(opportunity_id)
        if not self.s.scalar(select(Contact.id).where(Contact.opportunity_id == o.id).limit(1)):
            return {"error": "no contact yet: call find_contacts first (or skip this one)"}
        HANDLERS["draft_for_opportunity"](self.s, self.p, {"opportunity_id": o.id, "user_id": self.me.id})
        self.s.flush()
        it = self.s.scalar(select(ContentItem).where(ContentItem.opportunity_id == o.id)
                           .order_by(ContentItem.id.desc()).limit(1))
        self.counts["pitches"] += 1
        return {"item_id": it.id, "subject": it.title, "body": it.body, "placeholders": placeholders(it.title + " " + it.body)}

    def list_drafts(self, limit: int = 15) -> list[dict]:
        rows = self.s.scalars(select(ContentItem).where(ContentItem.project_id == self.p.id,
                              ContentItem.status == "pending_approval", ContentItem.channel != "pinterest")
                              .order_by(ContentItem.created_at).limit(min(int(limit or 15), 25))).all()
        out = []
        for it in rows:
            c = self.s.get(Contact, it.contact_id) if it.contact_id else None
            out.append({"id": it.id, "channel": it.channel, "type": it.content_type, "title": it.title,
                        "body": it.body[:2500], "to": (c.name or c.email.split("@")[0]) if c else None,
                        "placeholders": placeholders(it.title + " " + it.body)})
        return out

    def revise_draft(self, item_id: int, body: str, title: str = "") -> dict:
        it = self._item(item_id)
        if it.status != "pending_approval":
            return {"error": f"draft is {it.status}"}
        it.body, it.title = body, title or it.title
        return {"ok": True, "placeholders": placeholders(it.title + " " + it.body)}

    def approve_draft(self, item_id: int) -> dict:
        from app.worker import enqueue

        it = self._item(item_id)
        if it.status != "pending_approval":
            return {"error": f"draft is {it.status}"}
        allowed = set(self.acfg.get("auto_channels") or [])
        if it.channel == "email":
            allowed |= {"email"} if "outreach_email" in allowed else set()
        if not self.acfg.get("auto_send", True) or it.channel not in allowed:
            return {"left_for_human": f"{it.channel} needs human approval (Settings > AI teammate)"}
        bad = placeholders(it.title + " " + it.body)
        if bad:
            return {"refused": f"placeholders found {bad}; revise first"}
        if it.channel in MAIL:
            miss = self._sender_ready()
            if miss:
                return {"refused": "sender not ready: " + ", ".join(miss) + " (Settings > Sender)"}
            c = self.s.get(Contact, it.contact_id) if it.contact_id else None
            if not c or c.status in ("unsubscribed", "bounced"):
                return {"refused": "no valid recipient"}
        it.status, it.approved_by = "approved", self.me.id
        enqueue(self.s, "publish_content", self.p.id, content_id=it.id, user_id=self.me.id)
        self.counts["approved"] += 1
        return {"approved": True, "note": "sends/publishes within daily limits and business hours"}

    def reject_draft(self, item_id: int, reason: str = "") -> dict:
        it = self._item(item_id)
        it.status = "rejected"
        it.data = {**(it.data or {}), "rejected_reason": f"AI teammate: {reason}"[:300]}
        return {"ok": True}

    def draft_blog_article(self, topic: str) -> dict:
        from app.worker import HANDLERS

        if self.counts["articles"]:
            return {"error": "one article per run"}
        HANDLERS["draft_article"](self.s, self.p, {"topic": topic[:200], "user_id": self.me.id})
        self.s.flush()
        it = self.s.scalar(select(ContentItem).where(ContentItem.project_id == self.p.id, ContentItem.channel == "own_blog")
                           .order_by(ContentItem.id.desc()).limit(1))
        self.counts["articles"] += 1
        return {"item_id": it.id, "title": it.title, "placeholders": placeholders(it.title + " " + it.body)}

    def build_pins(self, n: int = 10) -> dict:
        from app import pinterest

        if not self.cfg.get("pinterest", {}).get("enabled", True):
            return {"error": "Pinterest disabled for this project"}
        return pinterest.build_pins(self.s, self.p, max(1, min(int(n or 10), 10)))

    def approve_pins(self) -> dict:
        from app.worker import enqueue

        if "pinterest" not in (self.acfg.get("auto_channels") or []) or not self.acfg.get("auto_send", True):
            return {"left_for_human": "pins need human approval"}
        n = 0
        for it in self.s.scalars(select(ContentItem).where(ContentItem.project_id == self.p.id,
                                 ContentItem.channel == "pinterest", ContentItem.status == "pending_approval")):
            if placeholders(it.title + " " + it.body):
                continue
            it.status, it.approved_by = "approved", self.me.id
            enqueue(self.s, "publish_content", self.p.id, content_id=it.id, user_id=self.me.id)
            n += 1
        return {"approved": n}

    def scan_social(self) -> dict:
        from app import social

        acct = social.engine_account(self.s, self.p.id)
        if not acct:
            return {"error": "social engine not connected"}
        social.push(self.s, self.p)
        return social.call(acct, "POST", "/api/scan")

    def hand_to_human(self, opportunity_id: int, note: str) -> dict:
        o = self._opp(opportunity_id)
        humans = self._humans()
        if humans:  # least-loaded human on this project
            load = {u.id: self.s.scalar(select(func.count()).select_from(Opportunity).where(
                Opportunity.assigned_to == u.id, Opportunity.status.in_(("new", "approved", "in_progress")))) or 0 for u in humans}
            o.assigned_to = min(load, key=load.get)
        o.data = {**(o.data or {}), "ai_note": note[:400]}
        return {"assigned_to": next((u.name or u.email for u in humans if u.id == o.assigned_to), None) or "nobody (no human builder on this project)"}

    def finish(self, briefing: str, needs_human: list[str] | None = None) -> dict:
        self.brief = {"briefing": briefing[:4000], "needs_human": [n[:300] for n in (needs_human or [])][:15]}
        return {"ok": True}


SYSTEM = """You are the AI teammate for {brand} ({domain}), working inside the Buzz Scouts link & growth engine.
Goal: earn real, relevant links and community visibility for the brand, safely. Quality over volume.

Work through this order, using the tools:
1. get_status. 2. check_inbox (if connected) and approve good reply drafts. 3. Pick up to {pitches} of the best outreach
opportunities (gift guides, roundups, link gaps, PR targets, bloggers); find_contacts, draft_pitch, then READ each draft:
revise it so it is specific to that site, honest, short, has no placeholders and no invented facts, then approve_draft
(if allowed) or leave it. 4. Review other waiting drafts the same way. 5. One own-blog article if none is waiting and it
fits the season. 6. build_pins then approve_pins (if Pinterest enabled). 7. scan_social (if connected).
8. For self_publish sites, directories, Reddit/Quora and anything needing an account, phone or samples: hand_to_human
with a one-line instruction. 9. finish with a briefing.

Hard rules:
- Never invent people, quotes, statistics, reviews, prices, discounts, shipping promises or "made in USA" claims.
- Emails are signed by the real sender configured in Settings; never sign as anyone else; never leave [placeholders].
- Never create accounts or post on third-party sites yourself; that's a human job.
- If sender details are missing, don't approve emails; say exactly what to fill in, in the briefing.
- Be cost-aware: stop early when there's nothing valuable left. Budget left today: ${budget}.
Today is {today}."""


def run(s: Session, project: Project, job_id: int | None = None, started_by: int | None = None) -> dict:
    cfg = project_cfg(project).get("agent", {})
    cap = float(cfg.get("daily_budget_usd", 2))
    r = Run(s, project, job_id, started_by)
    if spent_today(s, project.id) >= cap:
        pipeline.event(s, project.id, f"AI teammate: today's budget (${cap:.2f}) is used up. Raise it in Settings > AI teammate.", "warn")
        return {"stopped": "budget"}
    meter: list[float] = []
    token = ai.METER.set(meter)
    st = get_settings()
    model = st.model_default
    messages = [{"role": "user", "content": "Start today's run for this project."}]
    system = SYSTEM.format(brand=r.cfg["business"].get("business_name") or project.name, domain=project.domain,
                           pitches=int(cfg.get("max_pitches_per_run", 5)), today=utcnow().date().isoformat(),
                           budget=f"{cap - spent_today(s, project.id):.2f}")
    stop_reason = "done"
    try:
        for step in range(int(cfg.get("max_steps", 40))):
            if job_id:  # Stop button + heartbeat (keeps the stale-job sweeper away)
                j = s.get(Job, job_id)
                s.refresh(j)
                if j.status == "stopping":
                    stop_reason = "stopped by user"
                    break
                j.result = {"step": step, "log": r.log[-5:]}
            if spent_today(s, project.id) + sum(meter) >= cap:
                stop_reason = "budget reached"
                break
            resp = ai._client().messages.create(model=model, max_tokens=16000, system=system, tools=TOOLS,
                                                messages=messages, output_config={"effort": "medium"})
            meter.append(ai.cost(model, resp.usage))
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "end_turn" or r.brief:
                break
            if resp.stop_reason not in ("tool_use", "pause_turn"):
                stop_reason = resp.stop_reason
                break
            results = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                try:
                    fn = getattr(r, b.name)
                    out = fn(**(b.input or {}))
                    s.commit()
                    r.log.append(f"{b.name}: ok")
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out, default=str)[:6000]})
                except Exception as e:  # noqa: BLE001
                    s.rollback()
                    r.log.append(f"{b.name}: {str(e)[:80]}")
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": str(e)[:500]})
            if results:
                messages.append({"role": "user", "content": results})
            if r.brief:
                break
    finally:
        ai.METER.reset(token)
        spend = round(sum(meter), 4)
        s.add(ApiUsage(project_id=project.id, provider="claude_agent", endpoint="ai_teammate", units=spend))
        brief = r.brief or {"briefing": f"Run ended early ({stop_reason}). Steps: {', '.join(r.log[-10:]) or 'none'}.",
                            "needs_human": []}
        pipeline.event(s, project.id, brief["briefing"], "brief", user_id=r.me.id, needs_human=brief["needs_human"],
                       spend=spend, stop=stop_reason, counts=r.counts, started_by=started_by)
        s.commit()
    return {"stop": stop_reason, "spend_usd": spend, **r.counts}
