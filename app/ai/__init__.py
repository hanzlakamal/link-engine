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
    return _json(complete(BRAND_VOICE_PROMPT.format(domain=domain, text=text[:20000]), premium=True, max_tokens=6000))


CONTENT_PROMPT = """Write a {content_type} for {platform} on behalf of {brand} ({domain}).

BRAND VOICE (follow strictly):
{voice}

GOAL: {goal}
PLATFORM RULES: {rules}
Link to include (only where it genuinely helps the reader): {target_url}

Return ONLY JSON: {{"title": "...", "body": "...", "notes_for_reviewer": "..."}}
"""

PLATFORM_RULES = {
    "reddit": "Value first. No marketing tone. Disclose you're the founder if linking. Max 1 link. Follow subreddit rules.",
    "quora": "Answer the question directly in the first 2 lines. Personal, helpful. 1 link max, near the end, only if relevant.",
    "medium": "800-1200 words, story-driven, scannable headers. Link naturally 1-2 times.",
    "pinterest": "Title <100 chars keyword-rich; description 2-3 sentences with gift intent keywords.",
    "email": "Under 120 words. Personal, specific reason for contacting. One clear ask. No attachments.",
    "profile": "Brand description 150-300 chars + long version 500-800 chars. Consistent with other profiles.",
}


def draft_content(*, brand: str, domain: str, voice: dict, platform: str, content_type: str, goal: str,
                  target_url: str = "", premium: bool = False) -> dict:
    prompt = CONTENT_PROMPT.format(
        content_type=content_type, platform=platform, brand=brand, domain=domain,
        voice=json.dumps(voice or {"tone": ["friendly"]}, indent=1)[:4000], goal=goal,
        rules=PLATFORM_RULES.get(platform, "Follow the platform's norms; never spammy."),
        target_url=target_url or f"https://{domain}",
    )
    return _json(complete(prompt, premium=premium, max_tokens=3000))
