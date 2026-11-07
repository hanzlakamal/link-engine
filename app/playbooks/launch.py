"""Launch & growth playbooks.

`launch_72h` is the ChatGPT 72-hour plan, rebuilt:
  + Day 0 measurement + free channels GPT skipped (Merchant Center free listings, GSC,
    Pinterest catalog, pixel/CAPI, UTMs) — without these you can't tell what worked.
  + Links run in parallel from Day 1 (brand profiles = entity signals + first links).
  + Creator outreach gets discovery, per-creator codes (attribution) and UGC rights.
  + Season-aware: angles and PR pick the next US retail moments automatically.
  + Discount discipline: if BFCM is close, the launch offer is a free gift/bundle rather
    than %-off, so the BFCM sale still feels like an event.
  + Gift-guide PR is time-boxed: editors fill holiday guides early.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.models import Project
from app.playbooks.base import Playbook, TaskSpec
from app.registry import playbooks
from app.seasons import upcoming


def _brand(p: Project) -> str:
    return p.name or p.domain


@playbooks.register("launch_72h")
class Launch72h(Playbook):
    label = "72-hour launch sprint"
    description = "Make the brand visible, get first social proof and first links in 72 hours (+ day-0 setup)."
    stage = "launch"
    days = 3
    types = ("ecommerce",)

    def tasks(self, project, start):
        b = _brand(project)
        moms = upcoming(start, 60)
        season = ", ".join(f"{m.name} ({m.date:%b %d})" for m in moms[:3]) or "evergreen humor"
        bfcm = next((m for m in moms if m.key == "bfcm"), None)
        bfcm_close = bfcm is not None and (bfcm.date - start).days <= 28
        offer = ("Launch offer: FREE sticker pack / 2nd-shirt bundle + free US shipping (keep %-off for BFCM "
                 f"on {bfcm.date:%b %d})") if bfcm_close else "Launch offer: 15% off selected designs + free US shipping, 72h only"
        T = TaskSpec
        return [
            # ---------- Day 0: foundation (GPT skipped this) ----------
            T(0, "measure", "Install tracking: GA4, Meta Pixel + Conversions API, TikTok & Pinterest tags",
              "Without CAPI, iOS users vanish from ad attribution. Verify AddToCart/Checkout/Purchase events fire.", "human"),
            T(0, "measure", "UTM convention + per-channel short links",
              "Tool generates utm_source/medium/campaign per channel & creator so the dashboard can attribute sales.", "auto"),
            T(0, "foundation", "Google Merchant Center: free product listings + Shopping tab",
              "Free traffic from Google Shopping for gift searches. Sync from Shopify's Google & YouTube app.", "human"),
            T(0, "foundation", "Google Search Console + Bing Webmaster: verify, submit sitemap",
              "Also connects GSC to this tool for link + ranking tracking.", "human"),
            T(0, "foundation", "Pinterest business account + catalog sync (Rich Pins)",
              "Every product becomes a shoppable pin automatically; Pinterest is a top apparel discovery engine.", "human"),
            T(0, "foundation", "Auto-build brand voice profile from the site", "Tone, audience, do/don't words, signature jokes.", "auto",
              {"job": "build_brand_voice"}),
            # ---------- Day 1: recognizable ----------
            T(1, "social", "Finalize IG, TikTok, Facebook, Pinterest, YouTube profiles — identical name/logo/bio/link",
              f"Suggested bio: 'Life is full of crises. At least your outfit doesn't have to be. Funny graphic tees. "
              f"Free US shipping.' Same NAP everywhere = stronger brand entity for Google.", "approve"),
            T(1, "links", "Claim brand profiles on self-publish platforms (batch 1)",
              "Crunchbase, Trustpilot, Linktree, about.me, Gravatar, Behance, Tumblr, Medium, Quora, Reddit (founder). "
              "Each = a brand mention + link. Tool prepares copy per platform from brand voice.", "approve"),
            T(1, "store", "Homepage: 6–8 best designs above the fold, Best Sellers collection, seasonal gift collection",
              f"Lead with: {season}. Make free US shipping + free first exchange impossible to miss.", "human"),
            T(1, "store", "Reviews + email capture",
              "Install a reviews app (photo reviews, post-purchase request at day 7). Popup: 10% for email; welcome + abandoned-cart flows.", "human"),
            T(1, "social", "Produce 5 short videos + 3 lifestyle mockups of best designs",
              "Tool drafts hooks/scripts per design in brand voice: 'POV: your family at Thanksgiving…'.", "approve",
              {"generate": "video_scripts", "count": 5}),
            T(1, "creators", "Build creator shortlist (60 candidates → 30 to contact)",
              "US, 5K–50K followers, comedy/relatable, mom & family, holiday, casual fashion. Score by engagement rate, not followers.", "auto",
              {"strategy": "creators"}),
            # ---------- Day 2: in front of people ----------
            T(2, "creators", "Send 30 gifting DMs/emails (honest content, no positive-review requirement)",
              "Each creator gets a unique discount code + UTM link for attribution; ask for UGC reuse rights in the same message. "
              "Disclosure (#gifted/#ad) required by FTC.", "approve", {"limit_channel": "email"}),
            T(2, "social", "Publish: 3 IG Reels, 3 TikToks, 2 FB Reels, 5 Pins, 2 YouTube Shorts (repurposed)",
              "One video → five platforms. Tool schedules at best US times (ET evenings).", "approve"),
            T(2, "links", "Pinterest: pin every best seller + 2 gift-idea boards", "Pins link to product pages (traffic + discovery).", "approve"),
            T(2, "community", "Reddit/Quora: 5 genuinely helpful answers (gift ideas, funny shirt threads)",
              "Founder account, value first, link only when it truly answers the question. Respect each sub's rules.", "approve"),
            T(2, "pr", "Gift-guide PR sprint",
              f"Find '{season.split(',')[0]} funny shirt gift guide' articles from the last 12 months + authors; pitch samples. "
              "Editors finalize holiday guides early — this window closes fast.", "approve", {"strategy": "gift_guides"}),
            T(2, "links", "Run competitor backlink analysis (crazy-dog style competitors)",
              "Self-publish replication list + editorial link gap → queue.", "auto", {"job": "full_discovery"}),
            # ---------- Day 3: attention → sales ----------
            T(3, "store", "Launch campaign landing page: 'Your Wardrobe Is Having a Crisis. We've Got You.'", offer, "human"),
            T(3, "email", "Announce to subscribers + SMS (if any)", "Tool drafts subject lines A/B in brand voice.", "approve"),
            T(3, "ads", "Meta test: $20–30/day, US, 3–5 creatives, broad + retarget (site visitors, video viewers)",
              "Judge by add-to-cart, checkout, purchase, CAC — not likes. Kill losers after ~$15 spend each.", "human"),
            T(3, "ads", "Optional: Google Performance Max / Shopping $10–15/day for gift-intent searches", "", "human"),
            T(3, "links", "First self-published articles: Medium + Tumblr/Blogger gift guide featuring own designs",
              "Canonical to our blog where possible. Link to the seasonal collection.", "approve"),
            T(3, "measure", "72h review: which designs, creatives and channels drove ATC/sales?",
              "Dashboard snapshot; double down on top 2 designs and top channel next week.", "auto"),
        ]


@playbooks.register("launch_30d")
class Launch30d(Playbook):
    label = "First 30 days (after the sprint)"
    description = "Turn the launch into a steady engine: weekly links, content, creators, PR."
    stage = "launch"
    days = 30
    types = ("ecommerce",)

    def tasks(self, project, start):
        T = TaskSpec
        out = []
        for w in range(4):
            d = w * 7 + 4
            out += [
                T(d, "links", f"Week {w+1}: 3–5 self-publish links from the opportunity queue", "Highest-score platforms first.", "approve"),
                T(d, "social", f"Week {w+1}: 10 short videos + 15 pins", "Repurpose winners; test 2 new hooks.", "approve"),
                T(d + 1, "creators", f"Week {w+1}: follow up creators, contact 15 new", "One follow-up max. Track posts + code sales.", "approve"),
                T(d + 2, "community", f"Week {w+1}: 5 Reddit/Quora answers", "", "approve"),
                T(d + 3, "pr", f"Week {w+1}: 5 journalist-request answers + 5 gift-guide/roundup pitches", "", "approve"),
                T(d + 3, "measure", f"Week {w+1}: review dashboard, prune channels", "", "auto"),
            ]
        for m in upcoming(start, 45):
            push = max((m.date - timedelta(days=m.lead_days) - start).days, 0)
            out.append(T(push, "store", f"Prepare {m.name} ({m.date:%b %d}) collection + campaign", m.angle, "approve",
                         {"moment": m.key}))
        return out


@playbooks.register("growth_90d")
class Growth90d(Playbook):
    label = "Established brand: next level (90 days)"
    description = "For brands with traffic: link gap, digital PR, broken links, mentions, creators at scale."
    stage = "growth"
    days = 90

    def tasks(self, project, start):
        T = TaskSpec
        return [
            T(0, "links", "Full competitor link gap (2+ competitor overlap) + quality filter", "", "auto", {"job": "full_discovery"}),
            T(1, "links", "Unlinked brand mentions → link requests", "", "approve", {"strategy": "unlinked_mentions"}),
            T(3, "links", "Broken competitor pages with backlinks → offer our equivalent", "", "approve", {"strategy": "broken_links"}),
            T(5, "pr", "Data story: original survey or sales-data insight (e.g. 'most-gifted shirt slogans by state')",
              "Linkable asset for news sites; pitch to journalists covering trends/holidays.", "approve"),
            T(7, "pr", "Daily journalist-request monitoring (Qwoted, Featured, SourceBottle)", "", "auto", {"strategy": "pr_requests"}),
            T(10, "creators", "Creator affiliate program (UpPromote/GoAffPro) — recruit 50 micro-creators", "", "approve"),
            T(14, "links", "Podcast guesting: 10 pitches (founder story, POD business, humor brand)", "Show-notes links.", "approve"),
            T(21, "links", "Resource & gift-guide evergreen pages outreach", "", "approve"),
            T(30, "measure", "Month 1 review: RD growth, DR, rankings, revenue from referral", "", "auto"),
            T(60, "measure", "Month 2 review", "", "auto"),
            T(90, "measure", "Quarter review + next playbook", "", "auto"),
        ]


@playbooks.register("affiliate_launch")
class AffiliateLaunch(Playbook):
    label = "Affiliate / content site launch (14 days)"
    description = "Authority + first links for an affiliate or info site: profiles, resource pages, Q&A, expert quotes."
    stage = "launch"
    days = 14
    types = ("affiliate",)

    def tasks(self, project, start):
        T = TaskSpec
        return [
            T(0, "measure", "GA4 + Search Console + Bing Webmaster; submit sitemap", "Connect GSC for link/ranking tracking.", "human"),
            T(0, "foundation", "Build brand voice + author/expert bio (E-E-A-T)", "Real person, credentials, photo, About page.", "approve",
              {"job": "build_brand_voice"}),
            T(1, "links", "Claim brand profiles (batch 1): Crunchbase, LinkedIn page, Pinterest, Medium, Quora, Reddit (founder), Gravatar, about.me",
              "Same name/description everywhere. Profile kit on the Link publishing tab.", "approve"),
            T(1, "social", "Pinterest boards + first 30 pins from guides", "Handled by the Social engine (traffic-engine).", "approve"),
            T(2, "community", "Reddit/Quora: 5 helpful answers/day from the Social engine queue", "Value first; link ~1 in 2 with disclosure.", "approve"),
            T(3, "links", "Competitor link gap: resource pages + 'useful links' pages linking to competitors' guides", "", "auto",
              {"job": "full_discovery"}),
            T(4, "pr", "Expert-quote requests (Qwoted / Featured / SourceBottle): sign up, route emails to the reply inbox", "", "human"),
            T(5, "links", "Resource-page outreach: 10 personal pitches for your best guide", "", "approve"),
            T(7, "links", "Publish 2 hub articles on your blog + syndicate summaries (Medium import)", "", "approve"),
            T(10, "pr", "Answer 5 journalist requests with expert quotes", "", "approve"),
            T(14, "measure", "2-week review: links live, referring domains, impressions in GSC", "", "auto"),
        ]
