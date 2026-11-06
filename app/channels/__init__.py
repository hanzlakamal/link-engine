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

    def publish(self, item, account=None) -> PublishResult:
        return PublishResult(False, message="Assisted channel: open compose page, paste, then save the live URL.")


def get_channel(name: str) -> Channel:
    try:
        return channels.get(name)()
    except KeyError:
        ch = Channel()
        ch.name = name
        return ch


for _n in list(COMPOSE_URLS) + ["email", "instagram", "tiktok", "facebook", "youtube", "x", "profile", "directory", "forum"]:
    channels.register(_n)(type(f"{_n.title()}Channel", (Channel,), {}))
