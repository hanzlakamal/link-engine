"""Built-in strategies."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog import lookup
from app.classify import relevance, score
from app.models import Backlink, Competitor, Project
from app.registry import strategies
from app.strategies.base import Strategy


def _competitor_count(s: Session, project_id: int) -> int:
    return s.scalar(select(func.count()).select_from(Competitor).where(
        Competitor.project_id == project_id, Competitor.confirmed.is_(True))) or 0


@strategies.register("self_publish")
class SelfPublish(Strategy):
    label = "Self-publish replication"
    description = "Platforms where competitors got links we can create ourselves (posts, answers, profiles, listings)."

    def run(self, s, project, cfg):
        q = cfg["quality"]
        total = _competitor_count(s, project.id)
        rows = s.scalars(select(Backlink).where(
            Backlink.project_id == project.id, Backlink.acquisition == "self_publish")).all()
        groups: dict[str, list[Backlink]] = defaultdict(list)
        ours: set[str] = set()
        for b in rows:
            key = b.platform or b.source_domain
            if b.competitor_id is None:
                ours.add(key)  # we already have a presence there
            else:
                groups[key].append(b)
        n = 0
        for platform, links in groups.items():
            comps = {b.competitor_id for b in links}
            best = max(links, key=lambda b: (b.domain_rating, b.traffic))
            rel = max(relevance(f"{b.source_url} {b.title} {b.anchor}", q["relevance_terms"]) for b in links)
            dofollow_share = sum(b.dofollow for b in links) / len(links)
            hit = lookup(best.source_domain)
            plat = hit[1] if hit else None
            sc = score(dr=best.domain_rating, traffic=best.traffic, competitors_count=len(comps),
                       total_competitors=total, rel=max(rel, 0.5), dofollow_share=dofollow_share, weights=q["weights"])
            self.upsert(
                s, project.id, "self_publish", platform.lower(),
                title=f"{platform}: competitors have {len(links)} link(s) here",
                platform=platform, domain=best.source_domain, url=best.source_url, score=sc,
                competitors_count=len(comps),
                reason=(plat.notes if plat else best.category) or "",
                data={
                    "we_have_presence": platform in ours,
                    "category": best.category,
                    "posting": plat.posting if plat else "manual",
                    "link": plat.link if plat else ("dofollow" if dofollow_share > 0.5 else "nofollow"),
                    "content_types": list(plat.content_types) if plat else [],
                    "examples": [b.source_url for b in sorted(links, key=lambda b: -b.domain_rating)[:5]],
                    "anchors": list({b.anchor for b in links if b.anchor})[:10],
                },
            )
            n += 1
        return n


@strategies.register("link_gap")
class LinkGap(Strategy):
    label = "Link gap (editorial)"
    description = "Editorial sites linking to competitors but not to us. Outreach targets: gift guides, roundups, niche blogs."

    def run(self, s, project, cfg):
        q = cfg["quality"]
        total = _competitor_count(s, project.id)
        # launch-stage sites: even single-competitor links are worth a look
        min_overlap = cfg.get("link_gap", {}).get("min_overlap", 1 if project.stage == "launch" else 2)
        ours = set(s.scalars(select(Backlink.source_domain).where(
            Backlink.project_id == project.id, Backlink.competitor_id.is_(None))).all())
        rows = s.scalars(select(Backlink).where(
            Backlink.project_id == project.id, Backlink.acquisition == "outreach")).all()
        groups: dict[str, list[Backlink]] = defaultdict(list)
        for b in rows:
            if b.competitor_id is not None and b.source_domain not in ours:
                groups[b.source_domain].append(b)
        n = 0
        for dom, links in groups.items():
            comps = {b.competitor_id for b in links}
            best = max(links, key=lambda b: (b.domain_rating, b.traffic))
            if len(comps) < min_overlap or best.domain_rating < q["min_dr"] or best.traffic < q["min_traffic"]:
                continue
            rel = max(relevance(f"{b.source_url} {b.title} {b.anchor}", q["relevance_terms"]) for b in links)
            sc = score(dr=best.domain_rating, traffic=best.traffic, competitors_count=len(comps),
                       total_competitors=total, rel=rel, dofollow_share=sum(b.dofollow for b in links) / len(links),
                       weights=q["weights"])
            kind = "gift_guide" if any("gift" in (b.source_url + b.title).lower() for b in links) else "link_gap"
            self.upsert(
                s, project.id, kind, dom,
                title=best.title or dom, domain=dom, url=best.source_url, score=sc, competitors_count=len(comps),
                reason=f"links to {len(comps)}/{total} competitors",
                data={"examples": [b.source_url for b in links[:5]], "dr": best.domain_rating, "traffic": best.traffic},
            )
            n += 1
        return n


class _Planned(Strategy):
    ready = False

    def run(self, s, project, cfg):
        return 0


# Registered now so the UI/roadmap shows them; implementations land in v2/v3.
@strategies.register("pr_requests")
class PRRequests(_Planned):
    label = "Journalist requests (digital PR)"
    description = "Monitor Qwoted / Featured / SourceBottle / #journorequest; draft expert answers for approval."


@strategies.register("unlinked_mentions")
class UnlinkedMentions(_Planned):
    label = "Unlinked brand mentions"
    description = "Pages mentioning the brand or founder without a link; ask for the link."
    stages = ("growth",)


@strategies.register("broken_links")
class BrokenLinks(_Planned):
    label = "Broken competitor pages"
    description = "Dead competitor URLs that still have backlinks; offer our equivalent page."
    stages = ("growth",)


@strategies.register("creators")
class Creators(_Planned):
    label = "Creator / influencer seeding"
    description = "Find 5K-50K US creators in humor, family, holiday and fashion niches; gift shirts; track posts, codes and links."


@strategies.register("gift_guides")
class GiftGuides(_Planned):
    label = "Seasonal gift-guide placements"
    description = "Find this season's gift guides + their authors (SERP: 'funny shirt gifts 2026') and pitch with samples."


@strategies.register("ai_recommend")
class AIRecommend(_Planned):
    label = "AI-recommended link types"
    description = "Claude reviews competitor link profile + brand and proposes extra tactics specific to the niche."
