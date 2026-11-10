"""Auto-generated settings form from config.DEFAULTS.

Every key in DEFAULTS becomes a form field (bool -> checkbox, number -> number input,
list -> comma text, dict -> nested group). Only values that differ from the defaults are
stored as project overrides, so new defaults reach every project automatically.
"""
from __future__ import annotations

import json

from app.config import DEFAULTS

SECTION_LABELS = {
    "market": "Market", "discovery": "Discovery & API cost", "quality": "Quality filter & scoring",
    "automation": "Automation", "sender": "Sender (emails & signatures)",
    "business": "Business profile (directory submissions)", "publishing": "Publishing (blog hub)",
    "outreach": "Outreach & PR", "limits": "Frequency limits (anti-spam)", "alerts": "Alerts",
    "social": "Social & Community (Reddit + Quora answers in Telegram)",
    "pinterest": "Pinterest (pins from your products)",
    "agent": "AI teammate",
}
HELP = {
    "discovery.providers": "Order to try data sources, comma separated (ahrefs, dataforseo).",
    "discovery.max_competitors": "Max competitors to auto-discover.",
    "discovery.backlinks_per_competitor": "Rows pulled per competitor. Cost scales with this.",
    "discovery.min_link_dr": "Skip linking sites below this DR (filtered at the provider, so not paid for).",
    "discovery.include_traffic": "Fetch each linking site's traffic. Costs +10 Ahrefs units per row.",
    "discovery.pull_own_backlinks": "Also pull links to our own site (spam is always filtered out).",
    "discovery.refresh_days": "Don't re-pull a competitor more often than this.",
    "discovery.monthly_unit_budget": "Ahrefs units per month for this project. Jobs stop when reached. 0 = no limit.",
    "discovery.min_competitor_refdomains": "A competitor needs at least this many referring domains to be useful.",
    "discovery.never_competitors": "Domains never treated as competitors.",
    "quality.exclude_tlds": "Country domains outside your market. Empty for international brands.",
    "quality.spam_tokens": "Reject linking domains containing any of these words.",
    "quality.relevance_terms": "Words that make a link relevant to your niche.",
    "quality.blocklist": "Domains to always skip.",
    "automation.default_mode": "approve = review queue, auto = publish without review, off = disabled.",
    "automation.channels": "Per-channel override, JSON, e.g. {\"pinterest\": \"auto\"}.",
    "limits.default_per_day": "Daily cap for channels not listed below.",
    "sender.name": "Your name, used to sign outreach emails.",
    "business.business_name": "Public/trading name used on every listing (Google, Trustpilot, Birdeye, deal sites). Empty = project name.",
    "business.legal_name": "Registered company that owns the brand. Use only where a form asks for the legal entity (BBB, Crunchbase, affiliate payouts).",
    "business.company_number": "Company registration number (e.g. UK Companies House number), for legal fields only.",
    "sender.email": "From address (must be a verified sender in Brevo), e.g. hello@outreach.yourdomain.com.",
    "sender.postal_address": "Physical mailing address shown in email footers (legally required).",
    "publishing.own_blog_status": "What Approve does for blog articles: publish live, or save as draft in your CMS.",
    "quality.skip_categories": "Link categories ignored for this project (set by project type).",
    "limits.jitter_minutes": "Random gap between actions, min,max minutes.",
    "limits.business_hours": "Only act between these hours (start,end), local time.",
    "limits.email_ramp.bounce_pause_pct": "Pause an inbox if bounces exceed this %.",
    "social.brand_offer": "One sentence: what the brand sells/does and for whom. Leave the social fields empty and click "
                          "'Suggest targets' on Overview to let Claude fill them.",
    "social.relevant": "Which posts count as relevant (e.g. 'asking for gift ideas or funny shirt recommendations').",
    "social.looking_now": "What 'actively looking' means for this brand.",
    "social.persona": "Who the answers are written as (honest, never a fake customer).",
    "social.rules": "Extra rules for every answer: claims to avoid, tone, compliance.",
    "social.link_line": "Disclosure line before the link, e.g. 'Full disclosure, I work with this shop:'.",
    "social.queries": "Reddit search phrases (newest posts across Reddit).",
    "social.subreddits": "Subreddits to watch for new posts (no r/ prefix).",
    "social.avoid_subreddits": "Read these but never include a link there (self-promo banned).",
    "social.blocked_subreddits": "Never draft for these (you were banned/removed, or they forbid brands). The Social tab's 'Banned here' button adds to this.",
    "social.reject_topics": "Never draft for posts mentioning these.",
    "social.pages": "Site paths answers may link to, e.g. /, /product-category/halloween/.",
    "social.quora": "Also find Quora questions (uses DataForSEO, about $0.002 per phrase per scan).",
    "social.quora_queries": "Quora search phrases (empty = first 6 Reddit phrases).",
    "social.link_every_nth": "Include a link in at most 1 of every N posted answers.",
    "agent.display_name": "Name shown on the Team page and activity feed (internal only; emails are always signed by the real sender).",
    "agent.daily_budget_usd": "Max Claude spend per day for this project's AI teammate runs. It stops and reports when reached.",
    "agent.auto_send": "Let the teammate approve drafts itself on the channels below (sending still respects limits and business hours).",
    "agent.auto_channels": "Channels it may approve: outreach_email, own_blog, pinterest. Everything else waits for a human.",
    "agent.max_pitches_per_run": "Max new outreach pitches per run.",
    "pinterest.enabled": "Build pins automatically for this project (new projects get a first batch after the brand voice).",
    "pinterest.boards": "Board names. Empty = Claude proposes boards on the first build.",
    "pinterest.pins_per_build": "How many new pins each 'Build pins' makes (one per product/collection page not pinned yet).",
    "pinterest.csv_pins_per_day": "Spacing for the bulk-upload CSV (Pinterest schedules them).",
}
CHOICES = {"automation.default_mode": ["approve", "auto", "off"], "publishing.own_blog_status": ["publish", "draft"]}


def _label(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("_", " ").capitalize()


def fields(effective: dict, defaults: dict = DEFAULTS, prefix: str = "") -> list[dict]:
    out = []
    for k, dv in defaults.items():
        path = f"{prefix}{k}"
        v = effective.get(k, dv)
        f = {"path": path, "label": _label(path), "help": HELP.get(path, ""), "default": dv}
        if isinstance(dv, dict) and dv:
            out.append({**f, "type": "group", "children": fields(v if isinstance(v, dict) else {}, dv, path + ".")})
            continue
        if path in CHOICES:
            f.update(type="select", value=v, choices=CHOICES[path])
        elif isinstance(dv, bool):
            f.update(type="bool", value=bool(v))
        elif isinstance(dv, (int, float)):
            f.update(type="number", value=v, step="any" if isinstance(dv, float) else "1")
        elif isinstance(dv, list):
            f.update(type="list", value=", ".join(str(x) for x in v))
        elif isinstance(dv, dict):
            f.update(type="json", value=json.dumps(v))
        else:
            f.update(type="text", value=v)
        out.append(f)
    return out


def _coerce(dv, raw: str | None):
    if isinstance(dv, bool):
        return raw is not None
    raw = (raw or "").strip()
    if isinstance(dv, int) and not isinstance(dv, bool):
        return int(float(raw or 0))
    if isinstance(dv, float):
        return float(raw or 0)
    if isinstance(dv, list):
        items = [x.strip() for x in raw.split(",") if x.strip()]
        if dv and all(isinstance(x, (int, float)) for x in dv):
            return [type(dv[0])(float(x)) for x in items]
        return items
    if isinstance(dv, dict):
        return json.loads(raw or "{}")
    return raw


def parse(form, defaults: dict = DEFAULTS, prefix: str = "") -> dict:
    """Form -> overrides (only values that differ from defaults)."""
    out = {}
    for k, dv in defaults.items():
        path = f"{prefix}{k}"
        if isinstance(dv, dict) and dv:
            sub = parse(form, dv, path + ".")
            if sub:
                out[k] = sub
            continue
        v = _coerce(dv, form.get(path))
        if v != dv:
            out[k] = v
    return out
