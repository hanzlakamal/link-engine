"""Launch Kit: a preloaded list of self-publish sites every new project starts with.

Sources: the vetted part of a real launch backlink profile (ytdownloader.io export, Nov 2026:
~100 usable domains out of 673, the rest was spam / hacked pages / shorteners) plus well-known
fast-indexing platforms. Each project gets the sites that fit its type as `launch_site`
opportunities; niche-specific sites come from app/niche.py.

Tiers (how the site is used in the tiered-link plan, see app/tricks.py):
  content   - full articles with a contextual link (parasite SEO target, tier 1)
  web2      - mini-site / hub that links to our tier-1 articles and the money site
  docs      - PDF / document hosts (lookbook, guide)
  video     - video hosts (description links + embeds)
  visual    - image / design communities
  social    - social profiles (posts point at tier-1 articles = tier 2)
  curation  - bookmark / curation boards (tier 2)
  citation  - business listings, entity signals
  pr        - free press release sites
  launchdir - launch / alternative directories (apps, tools, SaaS)
  profile   - brand / entity profiles (sameAs; mostly nofollow)

`link` is what we expect; "verify" means the rel attribute changes over time, so the link
monitor confirms it on the first live link. `posting`: api = the engine can publish by itself
once the account is connected (Accounts tab), assisted = copy & open.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Opportunity, Project

ALL = ("ecommerce", "affiliate", "local", "saas")
ECOM = ("ecommerce",)
LOCAL = ("local",)
SAAS = ("saas",)
CONTENT_SITES = ("affiliate", "saas")


@dataclass(frozen=True)
class Site:
    domain: str
    name: str
    tier: str
    link: str = "nofollow"
    speed: str = "medium"  # very fast | fast | medium
    posting: str = "assisted"  # api | assisted
    fit: tuple[str, ...] = ALL
    url: str = ""  # sign-up / compose page
    notes: str = ""
    channel: str = ""  # engine channel name when it can publish there


S = Site
SITES: list[Site] = [
    # ---------------- content platforms (tier 1, parasite SEO) ----------------
    S("blogger.com", "Blogger", "content", "dofollow", "very fast", "api", url="https://www.blogger.com/",
      notes="Google-owned, indexes in hours. Best API target.", channel="blogger"),
    S("telegra.ph", "Telegraph", "content", "dofollow", "fast", "api", url="https://telegra.ph/",
      notes="No account needed: the engine creates one automatically.", channel="telegraph"),
    S("wordpress.com", "WordPress.com", "content", "dofollow", "fast", "api", url="https://wordpress.com/start",
      notes="Free subdomain blog; connect an OAuth token.", channel="wordpress_com"),
    S("tumblr.com", "Tumblr", "content", "verify", "fast", "api", url="https://www.tumblr.com/register",
      notes="Good for image-led posts.", channel="tumblr"),
    S("write.as", "Write.as", "content", "verify", "medium", "api", url="https://write.as/",
      notes="Anonymous posts work without an account.", channel="writeas"),
    S("hashnode.com", "Hashnode", "content", "nofollow", "fast", "api", CONTENT_SITES, "https://hashnode.com/onboard",
      "Tech/business angle only.", "hashnode"),
    S("dev.to", "DEV", "content", "nofollow", "fast", "api", SAAS, "https://dev.to/enter", "Tech angle only.", "devto"),
    S("medium.com", "Medium", "content", "nofollow", "very fast", "assisted", url="https://medium.com/new-story",
      notes="Use 'Import a story' with our post URL (keeps canonical).", channel="medium"),
    S("linkedin.com", "LinkedIn Articles", "content", "nofollow", "very fast", "assisted",
      url="https://www.linkedin.com/article/new/", notes="Founder profile; high trust, ranks for long-tail.", channel="linkedin"),
    S("substack.com", "Substack", "content", "verify", "fast", "assisted", url="https://substack.com/", channel="substack"),
    S("vocal.media", "Vocal", "content", "verify", "medium", url="https://vocal.media/"),
    S("hubpages.com", "HubPages", "content", "nofollow", "medium", url="https://hubpages.com/", notes="Editorial review; quality only."),
    S("velog.io", "Velog", "content", "verify", "medium", fit=SAAS, url="https://velog.io/"),
    S("stck.me", "Stck.me", "content", "verify", "medium", url="https://stck.me/"),
    S("justpaste.it", "JustPaste.it", "content", "verify", "fast", url="https://justpaste.it/"),
    S("notion.site", "Notion public page", "content", "nofollow", "medium", url="https://www.notion.so/"),
    S("quora.com", "Quora Space", "content", "nofollow", "fast", url="https://www.quora.com/spaces", channel="quora"),
    S("reddit.com", "Reddit profile posts", "content", "nofollow", "very fast", url="https://www.reddit.com/submit",
      notes="u/ profile posts; obey sub rules elsewhere.", channel="reddit"),
    S("amebaownd.com", "Ameba Ownd", "content", "dofollow", "medium", url="https://www.amebaownd.com/",
      notes="One sign-up gives sites on 5 domains (localinfo.jp, shopinfo.jp, themedia.jp, storeinfo.jp, theblog.me)."),
    S("checkli.com", "Checkli", "content", "verify", "medium", url="https://www.checkli.com/", notes="Publish a useful checklist."),
    S("elephantjournal.com", "Elephant Journal", "content", "verify", "medium", url="https://www.elephantjournal.com/"),
    S("instapaper.com", "Instapaper", "curation", "verify", "medium", url="https://www.instapaper.com/"),
    # ---------------- web 2.0 hubs ----------------
    S("sites.google.com", "Google Sites", "web2", "dofollow", "very fast", url="https://sites.google.com/new",
      notes="Google stacking hub: embed the Doc, Slides and My Map here."),
    S("docs.google.com", "Google Docs (publish to web)", "web2", "nofollow", "fast", url="https://docs.google.com/",
      notes="Google stacking: published doc linking to tier-1 articles."),
    S("google.com/maps/d", "Google My Maps", "web2", "nofollow", "fast", url="https://www.google.com/maps/d/",
      notes="Brand pin + description + links."),
    S("github.io", "GitHub Pages", "web2", "dofollow", "fast", "api", url="https://github.com/signup",
      notes="Engine builds and updates a hub page via the GitHub API.", channel="github_pages"),
    S("netlify.app", "Netlify", "web2", "dofollow", url="https://app.netlify.com/"),
    S("vercel.app", "Vercel", "web2", "dofollow", url="https://vercel.com/"),
    S("pages.dev", "Cloudflare Pages", "web2", "dofollow", url="https://pages.cloudflare.com/"),
    S("weebly.com", "Weebly", "web2", "dofollow", url="https://www.weebly.com/"),
    S("wixsite.com", "Wix", "web2", "dofollow", url="https://www.wix.com/"),
    S("jimdosite.com", "Jimdo", "web2", "dofollow", url="https://www.jimdo.com/"),
    S("webnode.page", "Webnode", "web2", "dofollow", url="https://www.webnode.com/"),
    S("mystrikingly.com", "Strikingly", "web2", "dofollow", url="https://www.strikingly.com/"),
    S("carrd.co", "Carrd", "web2", "dofollow", url="https://carrd.co/"),
    S("tilda.ws", "Tilda", "web2", "dofollow", url="https://tilda.cc/"),
    S("canva.site", "Canva Sites", "web2", "nofollow", url="https://www.canva.com/websites/"),
    S("github.com", "GitHub profile/repo", "profile", "nofollow", "fast", url="https://github.com/"),
    S("gitlab.com", "GitLab", "profile", "nofollow", url="https://gitlab.com/"),
    # ---------------- documents ----------------
    S("issuu.com", "Issuu", "docs", "nofollow", "fast", url="https://issuu.com/", notes="Lookbook / catalog PDF."),
    S("scribd.com", "Scribd + SlideShare", "docs", "nofollow", "fast", url="https://www.scribd.com/"),
    S("speakerdeck.com", "Speaker Deck", "docs", "nofollow", url="https://speakerdeck.com/"),
    S("calameo.com", "Calameo", "docs", "verify", url="https://www.calameo.com/"),
    S("yumpu.com", "Yumpu", "docs", "verify", url="https://www.yumpu.com/"),
    S("fliphtml5.com", "FlipHTML5", "docs", "verify", url="https://fliphtml5.com/"),
    S("anyflip.com", "AnyFlip", "docs", "nofollow", url="https://anyflip.com/"),
    # ---------------- video ----------------
    S("youtube.com", "YouTube", "video", "nofollow", "very fast", url="https://studio.youtube.com/"),
    S("vimeo.com", "Vimeo", "video", "nofollow", "fast", url="https://vimeo.com/upload"),
    S("dailymotion.com", "Dailymotion", "video", "nofollow", "fast", url="https://www.dailymotion.com/"),
    S("rumble.com", "Rumble", "video", "verify", url="https://rumble.com/upload.php"),
    S("bitchute.com", "BitChute", "video", "verify", url="https://www.bitchute.com/"),
    # ---------------- visual ----------------
    S("pinterest.com", "Pinterest", "visual", "nofollow", "very fast", "api", ECOM + ("affiliate",),
      "https://www.pinterest.com/", "Already automated (Pins).", "pinterest"),
    S("behance.net", "Behance", "visual", "nofollow", "fast", fit=ECOM, url="https://www.behance.net/", channel="behance"),
    S("dribbble.com", "Dribbble", "visual", "nofollow", "fast", fit=ECOM, url="https://dribbble.com/"),
    S("deviantart.com", "DeviantArt", "visual", "nofollow", "fast", fit=ECOM, url="https://www.deviantart.com/"),
    S("flickr.com", "Flickr", "visual", "nofollow", url="https://www.flickr.com/"),
    S("designspiration.com", "Designspiration", "visual", "nofollow", fit=ECOM, url="https://www.designspiration.com/"),
    S("sketchfab.com", "Sketchfab", "visual", "nofollow", fit=ECOM, url="https://sketchfab.com/"),
    S("lightroom.adobe.com", "Adobe Lightroom share", "visual", "verify", fit=ECOM, url="https://lightroom.adobe.com/"),
    S("redbubble.com", "Redbubble artist profile", "visual", "nofollow", fit=ECOM, url="https://www.redbubble.com/"),
    S("teepublic.com", "TeePublic artist profile", "visual", "nofollow", fit=ECOM, url="https://www.teepublic.com/"),
    S("spreadshirt.com", "Spreadshirt shop", "visual", "nofollow", fit=ECOM, url="https://www.spreadshirt.com/"),
    # ---------------- social (tier 2 pointers) ----------------
    S("bsky.app", "Bluesky", "social", "nofollow", "very fast", "api", url="https://bsky.app/", channel="bluesky"),
    S("mastodon.social", "Mastodon", "social", "nofollow", "fast", "api", url="https://mastodon.social/",
      notes="rel=me verified profile link.", channel="mastodon"),
    S("x.com", "X", "social", "nofollow", "very fast", url="https://x.com/", channel="x"),
    S("threads.net", "Threads", "social", "nofollow", "fast", url="https://www.threads.net/"),
    S("facebook.com", "Facebook Page", "social", "nofollow", "fast", url="https://www.facebook.com/pages/create", channel="facebook"),
    S("instagram.com", "Instagram", "social", "nofollow", "fast", fit=ECOM, url="https://www.instagram.com/", channel="instagram"),
    S("tiktok.com", "TikTok", "social", "nofollow", "fast", fit=ECOM, url="https://www.tiktok.com/", channel="tiktok"),
    S("telegram.me", "Telegram channel", "social", "verify", url="https://telegram.org/"),
    S("mixcloud.com", "Mixcloud", "social", "nofollow", url="https://www.mixcloud.com/"),
    S("audiomack.com", "Audiomack", "social", "verify", url="https://audiomack.com/"),
    # ---------------- curation (tier 2) ----------------
    S("flipboard.com", "Flipboard magazine", "curation", "nofollow", "fast", url="https://flipboard.com/"),
    S("scoop.it", "Scoop.it", "curation", "verify", url="https://www.scoop.it/"),
    S("pearltrees.com", "Pearltrees", "curation", "verify", url="https://www.pearltrees.com/"),
    S("diigo.com", "Diigo", "curation", "nofollow", url="https://www.diigo.com/"),
    S("wakelet.com", "Wakelet", "curation", "nofollow", "fast", url="https://wakelet.com/"),
    S("allmyfaves.com", "AllMyFaves", "curation", "nofollow", url="https://allmyfaves.com/"),
    S("wibki.com", "Wibki", "curation", "nofollow", url="https://wibki.com/"),
    # ---------------- citations / entity ----------------
    S("google.com/business", "Google Business Profile", "citation", "nofollow", "very fast", fit=ECOM + LOCAL,
      url="https://business.google.com/", notes="Strongest entity signal; posts index fast."),
    S("bingplaces.com", "Bing Places", "citation", "nofollow", "fast", fit=ECOM + LOCAL, url="https://www.bingplaces.com/"),
    S("businessconnect.apple.com", "Apple Business Connect", "citation", "verify", fit=ECOM + LOCAL,
      url="https://businessconnect.apple.com/"),
    S("trustpilot.com", "Trustpilot", "citation", "nofollow", "fast", fit=ECOM + SAAS, url="https://business.trustpilot.com/"),
    S("crunchbase.com", "Crunchbase", "citation", "nofollow", "fast", url="https://www.crunchbase.com/"),
    S("yelp.com", "Yelp", "citation", "nofollow", "fast", fit=LOCAL, url="https://biz.yelp.com/"),
    S("foursquare.com", "Foursquare", "citation", "nofollow", fit=LOCAL, url="https://foursquare.com/"),
    S("hotfrog.com", "Hotfrog", "citation", "verify", fit=ECOM + LOCAL, url="https://www.hotfrog.com/"),
    S("brownbook.net", "Brownbook", "citation", "verify", fit=LOCAL, url="https://www.brownbook.net/"),
    S("cylex.us.com", "Cylex", "citation", "verify", fit=LOCAL, url="https://www.cylex.us.com/"),
    S("walkscore.com", "Walk Score", "citation", "verify", fit=LOCAL, url="https://www.walkscore.com/"),
    S("askmap.net", "AskMap", "citation", "nofollow", fit=LOCAL, url="https://askmap.net/"),
    S("profiles.xero.com", "Xero profile", "citation", "verify", url="https://www.xero.com/"),
    # ---------------- PR ----------------
    S("prlog.org", "PRLog", "pr", "nofollow", "fast", url="https://www.prlog.org/"),
    S("openpr.com", "OpenPR", "pr", "nofollow", "fast", url="https://www.openpr.com/"),
    S("pr.com", "PR.com", "pr", "nofollow", url="https://www.pr.com/"),
    S("1888pressrelease.com", "1888PressRelease", "pr", "verify", url="https://www.1888pressrelease.com/"),
    # ---------------- launch directories ----------------
    S("producthunt.com", "Product Hunt", "launchdir", "nofollow", "fast", fit=SAAS, url="https://www.producthunt.com/"),
    S("betalist.com", "BetaList", "launchdir", "verify", fit=SAAS, url="https://betalist.com/"),
    S("alternativeto.net", "AlternativeTo", "launchdir", "nofollow", "fast", fit=SAAS, url="https://alternativeto.net/"),
    S("saashub.com", "SaaSHub", "launchdir", "verify", fit=SAAS, url="https://www.saashub.com/"),
    S("indiehackers.com", "Indie Hackers", "launchdir", "nofollow", "fast", url="https://www.indiehackers.com/"),
    # ---------------- brand profiles (entity / sameAs) ----------------
    *[S(d, n, "profile", lk, url=u) for d, n, lk, u in [
        ("gravatar.com", "Gravatar", "nofollow", "https://gravatar.com/"),
        ("linktr.ee", "Linktree", "nofollow", "https://linktr.ee/"),
        ("about.me", "about.me", "nofollow", "https://about.me/"),
        ("disqus.com", "Disqus", "nofollow", "https://disqus.com/"),
        ("hub.docker.com", "Docker Hub", "nofollow", "https://hub.docker.com/"),
        ("goodreads.com", "Goodreads", "nofollow", "https://www.goodreads.com/"),
        ("heylink.me", "HeyLink.me", "nofollow", "https://heylink.me/"),
        ("allmylinks.com", "AllMyLinks", "nofollow", "https://allmylinks.com/"),
        ("bio.site", "Bio Sites", "verify", "https://bio.site/"),
        ("mez.ink", "Mezink", "verify", "https://mez.ink/"),
        ("s.id", "s.id", "verify", "https://s.id/"),
        ("joy.link", "joy.link", "verify", "https://joy.link/"),
        ("biolinky.co", "Biolinky", "verify", "https://biolinky.co/"),
        ("linksta.cc", "LinkStack", "nofollow", "https://linksta.cc/"),
        ("magicly.bio", "Magic.ly", "nofollow", "https://magic.ly/"),
        ("hopp.bio", "Hopp", "verify", "https://hopp.co/"),
        ("leetcode.com", "LeetCode", "verify", "https://leetcode.com/"),
        ("habr.com", "Habr Q&A", "nofollow", "https://qna.habr.com/"),
        ("speedrun.com", "Speedrun.com", "nofollow", "https://www.speedrun.com/"),
        ("myminifactory.com", "MyMiniFactory", "verify", "https://www.myminifactory.com/"),
        ("pinshape.com", "Pinshape", "verify", "https://pinshape.com/"),
        ("facer.io", "Facer", "nofollow", "https://www.facer.io/"),
        ("talkshoe.com", "TalkShoe", "verify", "https://app.talkshoe.com/"),
        ("babelcube.com", "Babelcube", "verify", "https://www.babelcube.com/"),
        ("investagrams.com", "Investagrams", "verify", "https://www.investagrams.com/"),
        ("bigoven.com", "BigOven", "nofollow", "https://www.bigoven.com/"),
        ("tawk.to", "tawk.to", "nofollow", "https://www.tawk.to/"),
        ("files.fm", "Files.fm", "nofollow", "https://files.fm/"),
        ("notebook.ai", "Notebook.ai", "verify", "https://www.notebook.ai/"),
        ("ggather.com", "GGather", "verify", "https://web.ggather.com/"),
        ("truckymods.io", "TruckyMods", "verify", "https://truckymods.io/"),
        ("ficwad.com", "FicWad", "nofollow", "https://ficwad.com/"),
        ("mateball.com", "Mateball", "nofollow", "https://mateball.com/"),
        ("divephotoguide.com", "DivePhotoGuide", "verify", "https://www.divephotoguide.com/"),
        ("findaspring.org", "Find A Spring", "verify", "https://www.findaspring.org/"),
        ("tooter.in", "Tooter", "nofollow", "https://tooter.in/"),
        ("undrtone.com", "Undrtone", "verify", "https://undrtone.com/"),
        ("giveawayoftheday.com", "Giveaway of the Day forum", "nofollow", "https://www.giveawayoftheday.com/forums/"),
    ]],
]
BY_DOMAIN = {s.domain: s for s in SITES}
TIER_LABELS = {
    "content": "Content platforms (tier 1: articles)", "web2": "Web 2.0 hubs", "docs": "Documents / PDFs",
    "video": "Video", "visual": "Visual / design", "social": "Social (tier 2 pointers)", "curation": "Curation (tier 2)",
    "citation": "Business listings", "pr": "Press releases", "launchdir": "Launch directories",
    "profile": "Brand profiles (entity)", "learned": "Proven on other projects (learned)",
    "niche": "Niche sites (found for this brand)",
}
TIER_ORDER = list(TIER_LABELS)
SPEED_RANK = {"very fast": 3, "fast": 2, "medium": 1}


def site_score(site: Site) -> float:
    """Rough priority: tier-1 content and fast-indexing dofollow sites first."""
    tier = {"content": 40, "web2": 30, "citation": 25, "social": 20, "docs": 15, "video": 15, "visual": 15,
            "curation": 10, "launchdir": 15, "pr": 8, "profile": 10}.get(site.tier, 5)
    return tier + SPEED_RANK.get(site.speed, 0) * 8 + (12 if site.link == "dofollow" else 0) + (10 if site.posting == "api" else 0)


def sites_for(project: Project) -> list[Site]:
    t = project.type or "ecommerce"
    return [s for s in SITES if t in s.fit]


def seed(s: Session, project: Project) -> int:
    """Create launch_site opportunities for this project (idempotent; never resets statuses)."""
    have = set(s.scalars(select(Opportunity.key).where(Opportunity.project_id == project.id,
                                                        Opportunity.kind == "launch_site")).all())
    n = 0
    for site in sites_for(project):
        if site.domain in have:
            continue
        s.add(Opportunity(project_id=project.id, kind="launch_site", key=site.domain, title=site.name,
                          domain=site.domain, url=site.url or f"https://{site.domain}/", platform=site.name,
                          score=site_score(site), reason=site.notes,
                          data={"tier": site.tier, "link": site.link, "speed": site.speed, "posting": site.posting,
                                "channel": site.channel, "category": site.tier}))
        have.add(site.domain)
        n += 1
    return n + seed_learned(s, project, have)


def seed_learned(s: Session, project: Project, have: set[str]) -> int:
    """Add sites other projects proved (live links / completed) that fit this project (app/learning.py)."""
    from app import learning

    learning.learn(s)
    s.flush()
    n = 0
    for ls in learning.suggestions(s, project):
        if ls.domain in have or ls.domain in BY_DOMAIN:
            continue
        s.add(Opportunity(project_id=project.id, kind="launch_site", key=ls.domain, title=ls.name or ls.domain,
                          domain=ls.domain, url=ls.url or f"https://{ls.domain}/", platform=ls.name or ls.domain,
                          score=min(95.0, 40 + ls.score),
                          reason=f"Learned from {ls.projects} other project(s): {ls.wins} done, {ls.live_links} live link(s)"
                                 f"{f', {ls.dofollow_links} dofollow' if ls.dofollow_links else ''}.",
                          data={"tier": "learned", "learned": True, "type": ls.kind, "link": "dofollow" if ls.dofollow_links
                                else "verify", "speed": "", "posting": "assisted", "channel": "", "category": "learned"}))
        have.add(ls.domain)
        n += 1
    return n
