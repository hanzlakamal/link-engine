"""Claude-powered writing: brand voice + content drafts.

All prompts live here so they can be tuned without touching pipeline code.
"""
from __future__ import annotations

import json
import re

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings


class AIUnavailable(RuntimeError):
    pass


def _client():
    s = get_settings()
    if not s.anthropic_api_key:
        raise AIUnavailable("ANTHROPIC_API_KEY not set")
    import anthropic

    return anthropic.Anthropic(api_key=s.anthropic_api_key)


def complete(prompt: str, *, system: str = "", premium: bool = False, max_tokens: int = 2000) -> str:
    s = get_settings()
    msg = _client().messages.create(
        model=s.model_premium if premium else s.model_default,
        max_tokens=max_tokens,
        system=system or "You are a senior brand marketer and copywriter.",
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _schema(fields: dict) -> dict:
    """fields: name -> "str" | "list" | "bool" | dict(nested object list item fields)."""
    def one(v):
        if v == "list":
            return {"type": "array", "items": {"type": "string"}}
        if v == "bool":
            return {"type": "boolean"}
        if isinstance(v, dict):
            return {"type": "array", "items": _schema(v)}
        return {"type": "string"}
    return {"type": "object", "properties": {k: one(v) for k, v in fields.items()},
            "required": list(fields), "additionalProperties": False}


# Spend metering: while an AI-teammate run is active, every Claude call adds its cost (USD) to METER.
import contextvars

METER: contextvars.ContextVar = contextvars.ContextVar("claude_meter", default=None)
PRICES = {"claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5": (2.0, 10.0),
          "claude-opus-5": (5.0, 25.0)}  # USD per million input / output tokens


def cost(model: str, usage) -> float:
    pin, pout = PRICES.get(model, (5.0, 25.0))  # unknown model: assume the expensive tier
    inp = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * 1.25
    inp += (getattr(usage, "cache_read_input_tokens", 0) or 0) * 0.1
    return (inp * pin + (getattr(usage, "output_tokens", 0) or 0) * pout) / 1_000_000


def _meter(model: str, usage) -> None:
    m = METER.get()
    if m is not None:
        m.append(cost(model, usage))


def complete_json(prompt: str, fields: dict, *, system: str = "", premium: bool = False, max_tokens: int = 16000,
                  effort: str = "") -> dict:
    """Structured outputs (output_config.format): the API guarantees valid JSON matching the schema.

    Current models think before answering and thinking counts toward max_tokens, so keep it generous
    and use lower effort for routine copywriting (premium tasks get medium)."""
    s = get_settings()
    effort = effort or ("medium" if premium else "low")
    msg = _client().messages.create(
        model=s.model_premium if premium else s.model_default,
        max_tokens=max(max_tokens, 16000),
        system=system or "You are a senior brand marketer and copywriter.",
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": _schema(fields)}},
        messages=[{"role": "user", "content": prompt}],
    )
    _meter(s.model_premium if premium else s.model_default, msg.usage)
    if msg.stop_reason in ("refusal", "max_tokens"):
        raise ValueError(f"AI stopped early ({msg.stop_reason})")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"Model did not return JSON (got {len(text)} chars: {text[:120]!r})")
    return json.loads(m.group(0))


def fetch_site_text(domain: str, paths=("/", "/about", "/about-us", "/pages/about", "/pages/about-us")) -> str:
    from app.auth import assert_public_url

    assert_public_url(f"https://{domain}/")
    chunks = []
    with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": "LinkEngineBot/2.0"}) as c:
        for p in paths:
            try:
                r = c.get(f"https://{domain}{p}")
            except httpx.HTTPError:
                continue
            if r.status_code == 200 and "text/html" in r.headers.get("content-type", ""):
                soup = BeautifulSoup(r.text, "html.parser")
                for t in soup(["script", "style", "noscript", "svg"]):
                    t.decompose()
                chunks.append(f"## {p}\n" + " ".join(soup.get_text(" ").split())[:6000])
    return "\n\n".join(chunks)


BRAND_VOICE_PROMPT = """Build a brand voice profile for {domain} from its website text below.
Return ONLY JSON with keys:
  positioning (1 sentence), audience (list), tone (list of adjectives), humor_style,
  do_words (list), dont_words (list), signature_phrases (list), products_to_feature (list),
  content_pillars (list), example_social_post, example_quora_answer_opening, cta_style,
  compliance_notes (list, e.g. FTC disclosure for gifted creators).
Keep every list to at most 8 short items. No markdown, no commentary: the JSON object only.

WEBSITE TEXT:
{text}
"""


def build_brand_voice(domain: str) -> dict:
    text = fetch_site_text(domain)
    if not text:
        raise RuntimeError(f"Could not fetch any pages from {domain}")
    return complete_json(BRAND_VOICE_PROMPT.format(domain=domain, text=text[:20000]), {"positioning": "str", "audience": "list", "tone": "list", "humor_style": "str", "do_words": "list", "dont_words": "list", "signature_phrases": "list", "products_to_feature": "list", "content_pillars": "list", "example_social_post": "str", "example_quora_answer_opening": "str", "cta_style": "str", "compliance_notes": "list"}, premium=True, max_tokens=6000)


CONTENT_PROMPT = """Write a {content_type} for {platform} on behalf of {brand} ({domain}).

BRAND VOICE (follow strictly):
{voice}

GOAL: {goal}
PLATFORM RULES: {rules}
Link to include (only where it genuinely helps the reader): {target_url}
SENDER / AUTHOR: {sender}
Never leave placeholders like [Name] or [Your Name]. If a detail is unknown, write around it.

Return ONLY JSON: {{"title": "...", "body": "...", "notes_for_reviewer": "..."}}
"""

PLATFORM_RULES = {
    "reddit": "Value first. No marketing tone. Disclose you're the founder if linking. Max 1 link. Follow subreddit rules.",
    "quora": "Answer the question directly in the first 2 lines. Personal, helpful. 1 link max, near the end, only if relevant.",
    "medium": "800-1200 words, story-driven, scannable headers. Link naturally 1-2 times.",
    "pinterest": "Title <100 chars keyword-rich; description 2-3 sentences with gift intent keywords.",
    "email": "Under 120 words. Personal, specific reason for contacting. One clear ask. No attachments.",
    "profile": "Brand description 150-300 chars + long version 500-800 chars. Consistent with other profiles.",
    "own_blog": ("900-1400 word SEO article for the brand's own blog. Body must be clean HTML only "
                 "(<h2>, <h3>, <p>, <ul>, <li>, <a>, <strong>), no <html>/<body>, no markdown. "
                 "Link to relevant pages on the brand's site 2-4 times."),
}

PROFILE_KIT_PROMPT = """Create a reusable profile kit for {brand} ({domain}) to paste into directory, review,
business-data, deal and affiliate-network sign-ups. Brand voice: {voice}
Return ONLY JSON: {{"tagline": "<60 chars", "short": "150-250 chars", "medium": "400-600 chars",
"long": "900-1200 chars", "categories": ["..."], "keywords": ["..."], "founder_bio": "300 chars"}}"""


def profile_kit(brand: str, domain: str, voice: dict) -> dict:
    return complete_json(PROFILE_KIT_PROMPT.format(brand=brand, domain=domain, voice=json.dumps(voice)[:3000]), {"tagline": "str", "short": "str", "medium": "str", "long": "str", "categories": "list", "keywords": "list", "founder_bio": "str"},
                          max_tokens=2500)


SOCIAL_PROMPT = """Set up community marketing (helpful Reddit comments and Quora answers, NOT spam) for this brand.
Brand: {brand} ({domain}). Niche: {niche}. Market: {market}.
Brand voice / profile: {voice}
Site pages we know: {pages}

Return:
- brand_offer: one sentence, what they sell/do and for whom.
- relevant: one sentence defining which posts are worth answering (people asking for ideas/recommendations/help this brand can honestly give).
- looking_now: one sentence defining "actively looking right now" for this niche.
- persona: who the answers are written as, honest (e.g. "a friendly person who loves funny gifts"), never a fake customer.
- rules: 2-4 short rules for answers (claims to avoid, compliance, tone), one paragraph.
- link_line: a short honest disclosure line used before the link.
- queries: 12-16 Reddit search phrases real people type when they need what the brand offers (short, natural).
- subreddits: 6-10 active subreddits where such questions are asked (names only, no r/).
- avoid_subreddits: the ones among them that ban self-promotion.
- reject_topics: 3-6 topics never to answer (wholesale, B2B, off-niche).
- quora_queries: 4-6 Quora-style question phrases.
- pages: 2-8 site paths answers could link to, chosen ONLY from the known pages (or "/")."""


def social_targets(*, brand: str, domain: str, niche: str, market: str, voice: dict, pages: list[str]) -> dict:
    return complete_json(SOCIAL_PROMPT.format(brand=brand, domain=domain, niche=niche or "(infer from the site)",
                         market=market, voice=json.dumps(voice or {})[:3000], pages=", ".join(pages[:60]) or "/"),
                         {"brand_offer": "str", "relevant": "str", "looking_now": "str", "persona": "str", "rules": "str",
                          "link_line": "str", "queries": "list", "subreddits": "list", "avoid_subreddits": "list",
                          "reject_topics": "list", "quora_queries": "list", "pages": "list"}, max_tokens=4000)


PIN_PROMPT = """Write Pinterest pins for {brand}. Brand voice: {voice}
Boards to use: {boards}
For EACH page below write: title (max 90 chars, keyword-rich, natural), description (150-400 chars, what it is, who it's for,
occasion/gift angle, 2-4 relevant keywords woven in, no hashtags spam, no prices or shipping promises), and board (one of the
boards, verbatim). If no boards are given, first propose 3-6 board names (keyword-style, e.g. "Funny Dad Shirts") in 'boards'
and use them. Keep each pin's 'url' exactly as given.
Pages:
{pages}"""


def pin_copy(*, brand: str, voice: dict, pages: list[dict], boards: list[str]) -> dict:
    listing = "\n".join(f"- url: {p['url']} | title: {p['title'][:120]} | about: {p['description'][:250]}" for p in pages)
    return complete_json(PIN_PROMPT.format(brand=brand, voice=json.dumps(voice or {})[:1500],
                                           boards=", ".join(boards) or "(none yet)", pages=listing),
                         {"boards": "list", "pins": {"url": "str", "title": "str", "description": "str", "board": "str"}},
                         max_tokens=8000)


def draft_content(*, brand: str, domain: str, voice: dict, platform: str, content_type: str, goal: str,
                  target_url: str = "", premium: bool = False, sender: dict | None = None,
                  categories: list[str] | None = None) -> dict:
    sd = sender or {}
    sender_txt = sd.get("signature") or ", ".join(x for x in (sd.get("name"), sd.get("title"), brand) if x)
    prompt = CONTENT_PROMPT.format(sender=sender_txt or f"The {brand} team",
        content_type=content_type, platform=platform, brand=brand, domain=domain,
        voice=json.dumps(voice or {"tone": ["friendly"]}, indent=1)[:4000], goal=goal,
        rules=PLATFORM_RULES.get(platform, "Follow the platform's norms; never spammy."),
        target_url=target_url or f"https://{domain}",
    )
    fields = {"title": "str", "body": "str", "notes_for_reviewer": "str"}
    if categories:
        prompt += "\nBlog categories (pick exactly one, verbatim, for the 'category' field): " + " | ".join(categories)
        fields["category"] = "str"
    return complete_json(prompt, fields, premium=premium, max_tokens=6000 if platform == "own_blog" else 3000)


REPLY_PROMPT = """You manage link-building outreach for {brand} ({domain}). Classify this reply and draft a response.
Original pitch subject: {subject}
Their reply:
{body}

Return ONLY JSON: {{"label": "interested|wants_payment|not_interested|out_of_office|link_placed|question|other",
"summary": "1 sentence", "draft_reply": "short reply in the brand voice, or empty if none is needed"}}
Never agree to pay for links. Sender: {sender}"""

PR_PROMPT = """Extract journalist requests relevant to {brand} ({niche}) from this digest email.
Return ONLY JSON: {{"requests": [{{"title": "...", "outlet": "...", "deadline": "...", "summary": "...",
"how_to_respond": "...", "relevant": true/false}}]}}
EMAIL:
{body}"""


def classify_reply(brand, domain, subject, body, sender) -> dict:
    return complete_json(REPLY_PROMPT.format(brand=brand, domain=domain, subject=subject, body=body[:4000],
                                              sender=sender), {"label": "str", "summary": "str", "draft_reply": "str"}, max_tokens=1500)


def extract_pr_requests(brand, niche, body) -> list[dict]:
    return complete_json(PR_PROMPT.format(brand=brand, niche=niche, body=body[:12000]), {"requests": {"title": "str", "outlet": "str", "deadline": "str", "summary": "str", "how_to_respond": "str", "relevant": "bool"}}, max_tokens=4000).get("requests", [])
