"""Platform catalog: which linking domains we can get a link from ourselves, and how.

Each entry: domain suffix -> Platform. `acquisition`:
  self_publish  we can create the link (post, profile, listing, answer)
  outreach      needs a human editor to say yes (handled by link-gap strategy)
  pr            needs a journalist (handled by PR strategy)
  skip          not worth it / spam / impossible

`posting`: api | assisted (we prepare, human pastes) | manual
`link`: typical link attribute on that platform (dofollow/nofollow/ugc) — nofollow is
still worth it for traffic, brand search and entity signals; scoring just weights it lower.

Extend freely; order does not matter (longest suffix wins). Project settings can add
custom entries under settings["catalog_extra"].
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Platform:
    name: str
    category: str
    acquisition: str = "self_publish"
    posting: str = "assisted"
    link: str = "nofollow"
    content_types: tuple[str, ...] = ()
    notes: str = ""
    tags: tuple[str, ...] = field(default=())


P = Platform
CATALOG: dict[str, Platform] = {
    # --- blog / article platforms ------------------------------------------------
    "medium.com": P("Medium", "blog_platform", posting="assisted", content_types=("article",),
                    notes="Import API is closed to new integrations; assisted via 'Import a story' from our own blog URL keeps canonical."),
    "substack.com": P("Substack", "blog_platform", content_types=("newsletter", "article")),
    "blogspot.com": P("Blogger", "blog_platform", posting="api", link="dofollow", content_types=("article",)),
    "blogger.com": P("Blogger", "blog_platform", posting="api", link="dofollow", content_types=("article",)),
    "wordpress.com": P("WordPress.com", "blog_platform", posting="api", link="dofollow", content_types=("article",)),
    "tumblr.com": P("Tumblr", "blog_platform", posting="api", link="dofollow", content_types=("image_post", "article")),
    "dev.to": P("DEV", "blog_platform", posting="api", content_types=("article",), notes="Only for tech-angle stories (e.g. how we built the store)."),
    "hashnode.dev": P("Hashnode", "blog_platform", posting="api", content_types=("article",)),
    "hubpages.com": P("HubPages", "blog_platform", content_types=("article",)),
    "vocal.media": P("Vocal", "blog_platform", content_types=("article",)),
    "linkedin.com": P("LinkedIn", "social", posting="api", content_types=("article", "post")),
    "weebly.com": P("Weebly", "web2", link="dofollow", content_types=("mini_site",)),
    "wixsite.com": P("Wix", "web2", link="dofollow", content_types=("mini_site",)),
    "sites.google.com": P("Google Sites", "web2", link="dofollow", content_types=("mini_site",)),
    "notion.site": P("Notion", "web2", content_types=("mini_site",)),
    "telegra.ph": P("Telegraph", "web2", content_types=("article",)),
    # --- Q&A / community -----------------------------------------------------------
    "quora.com": P("Quora", "qa", content_types=("answer", "space_post"), notes="No API: assisted posting. Founder persona performs best."),
    "reddit.com": P("Reddit", "community", posting="api", link="ugc", content_types=("comment", "post"),
                    notes="Value-first. Follow each subreddit's self-promo rules; max ~10% promotional."),
    "stackexchange.com": P("StackExchange", "qa", acquisition="skip", notes="Strict anti-promo."),
    "producthunt.com": P("Product Hunt", "launch_site", content_types=("launch",)),
    "indiehackers.com": P("Indie Hackers", "community", content_types=("post",)),
    # --- visual / social ----------------------------------------------------------
    "pinterest.com": P("Pinterest", "visual", posting="api", content_types=("pin",), notes="Huge for apparel search; use product catalog + Rich Pins."),
    "flickr.com": P("Flickr", "visual", content_types=("photo",)),
    "behance.net": P("Behance", "visual", content_types=("portfolio",), notes="Design-story posts for original artwork."),
    "dribbble.com": P("Dribbble", "visual", content_types=("shot",)),
    "deviantart.com": P("DeviantArt", "visual", content_types=("artwork",)),
    "instagram.com": P("Instagram", "social", posting="api", content_types=("reel", "post")),
    "tiktok.com": P("TikTok", "social", posting="api", content_types=("video",)),
    "youtube.com": P("YouTube", "social", posting="api", content_types=("short", "video")),
    "facebook.com": P("Facebook", "social", posting="api", content_types=("post", "reel")),
    "x.com": P("X", "social", posting="api", content_types=("post",)),
    "twitter.com": P("X", "social", posting="api", content_types=("post",)),
    "threads.net": P("Threads", "social", content_types=("post",)),
    "linktr.ee": P("Linktree", "profile", content_types=("profile",)),
    "about.me": P("about.me", "profile", content_types=("profile",)),
    "gravatar.com": P("Gravatar", "profile", content_types=("profile",)),
    # --- marketplaces / POD (presence + product discovery) -----------------------
    "etsy.com": P("Etsy", "marketplace", content_types=("shop",), notes="Mirror best sellers; shop 'About' links home."),
    "amazon.com": P("Amazon", "marketplace", acquisition="skip", notes="Merch on Demand is a sales channel, not a link."),
    "redbubble.com": P("Redbubble", "marketplace", content_types=("artist_profile",)),
    "teepublic.com": P("TeePublic", "marketplace", content_types=("artist_profile",)),
    "spreadshirt.com": P("Spreadshirt", "marketplace", content_types=("shop",)),
    "zazzle.com": P("Zazzle", "marketplace", content_types=("shop",)),
    "society6.com": P("Society6", "marketplace", content_types=("artist_profile",)),
    "threadless.com": P("Threadless", "marketplace", content_types=("artist_shop",)),
    # --- business profiles / directories / reviews ----------------------------------
    "crunchbase.com": P("Crunchbase", "directory", content_types=("profile",)),
    "trustpilot.com": P("Trustpilot", "reviews", content_types=("profile",), notes="Claim profile; invite real buyers only."),
    "sitejabber.com": P("Sitejabber", "reviews", content_types=("profile",)),
    "bbb.org": P("BBB", "directory", content_types=("profile",)),
    "yelp.com": P("Yelp", "directory", content_types=("profile",)),
    "f6s.com": P("F6S", "directory", content_types=("profile",)),
    "shopify.com": P("Shopify (blog/showcase)", "editorial", acquisition="outreach", link="dofollow"),
    "knoji.com": P("Knoji", "deals", content_types=("brand_profile",), notes="Brand Q&A + coupon pages; common on DTC apparel."),
    "dealspotr.com": P("Dealspotr", "deals", content_types=("brand_profile",)),
    "retailmenot.com": P("RetailMeNot", "deals", content_types=("coupon",)),
    "couponfollow.com": P("CouponFollow", "deals", content_types=("coupon",)),
    "slickdeals.net": P("Slickdeals", "deals", content_types=("deal_post",), notes="Post real BFCM deals only."),
    # --- news / PR (never self-publish) ---------------------------------------------
    "buzzfeed.com": P("BuzzFeed", "news", acquisition="pr", link="dofollow"),
    "forbes.com": P("Forbes", "news", acquisition="pr"),
    "nytimes.com": P("NYTimes", "news", acquisition="pr"),
    "bustle.com": P("Bustle", "news", acquisition="pr", link="dofollow"),
    "boredpanda.com": P("Bored Panda", "news", acquisition="pr", notes="Loves funny-design roundups; pitch or submit a post."),
    # --- obvious skips ----------------------------------------------------------------
    "google.com": P("Google", "infra", acquisition="skip"),
    "wikipedia.org": P("Wikipedia", "wiki", acquisition="skip", notes="Do not spam Wikipedia."),
    "archive.org": P("Archive", "infra", acquisition="skip"),
}

# URL path/title hints for editorial pages on unknown domains -> opportunity sub-type.
EDITORIAL_HINTS: list[tuple[str, str]] = [
    ("gift-guide", "gift_guide"), ("gift guide", "gift_guide"), ("gifts-for", "gift_guide"), ("gifts for", "gift_guide"),
    ("best-", "listicle"), ("top-", "listicle"), ("best ", "listicle"),
    ("resources", "resource_page"), ("links", "resource_page"),
    ("review", "review"), ("coupon", "deals"), ("promo-code", "deals"),
    ("forum", "forum"), ("/threads/", "forum"), ("/community", "forum"), ("/t/", "forum"),
    ("podcast", "podcast"), ("interview", "interview"),
    ("write-for-us", "guest_post_sales"), ("sponsored", "guest_post_sales"), ("guest-post", "guest_post_sales"),
]


def lookup(domain: str, extra: dict[str, dict] | None = None) -> tuple[str, Platform] | None:
    """Longest-suffix match of domain against catalog (+ project extras)."""
    domain = domain.lower().lstrip(".")
    merged = dict(CATALOG)
    for k, v in (extra or {}).items():
        merged[k] = Platform(**v) if isinstance(v, dict) else v
    best: tuple[str, Platform] | None = None
    for suffix, plat in merged.items():
        if domain == suffix or domain.endswith("." + suffix):
            if best is None or len(suffix) > len(best[0]):
                best = (suffix, plat)
    return best
