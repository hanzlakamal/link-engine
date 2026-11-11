"""Cross-project learning for the Launch Kit.

`learn(s)` rebuilds the LearnedSite table from every project's results (cheap DB scan, idempotent):
  - an opportunity marked done on a launch/niche/self-publish site          -> win
  - an earned link from that domain that is live (and dofollow / its score) -> proof
  - a rejected niche site                                                    -> reject
  - competitor self-publish platforms seen across projects                    -> demand signal
New projects are then seeded (app/launchkit.seed) with learned sites that proved themselves for the same
project type or a similar niche, ranked by `score`. Only domains and counts are shared between projects.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classify import domain_of, root_domain
from app.models import EarnedLink, LearnedSite, Opportunity, Project

LEARN_KINDS = ("launch_site", "niche_site", "self_publish")
STOP = {"and", "the", "for", "with", "shop", "store", "online", "brand", "company", "services", "service", "best"}


def niche_terms(project: Project) -> set[str]:
    words = f"{project.niche or ''} " + " ".join(((project.settings or {}).get("launch") or {}).get("keywords") or [])
    return {w for w in re.split(r"[^a-z0-9]+", words.lower()) if len(w) > 3 and w not in STOP}


def site_score(st: dict) -> float:
    """Proven > popular. Rejections and never-completed sites sink."""
    win_rate = st["wins"] / st["projects"] if st["projects"] else 0
    score = st["wins"] * 12 + st["live"] * 6 + st["dofollow"] * 8 + win_rate * 20 + st["projects"] * 1.5 - st["rejects"] * 10
    if st["link_scores"]:
        score += sum(st["link_scores"]) / len(st["link_scores"]) / 10
    return round(score, 1)


def learn(s: Session) -> int:
    stats: dict[str, dict] = defaultdict(lambda: {"projects": 0, "wins": 0, "rejects": 0, "live": 0, "dofollow": 0,
                                                 "link_scores": [], "types": set(), "terms": set(), "name": "", "url": "",
                                                 "tier": "", "kind": "", "pids": set()})
    projects = {p.id: p for p in s.scalars(select(Project)).all()}
    terms = {pid: niche_terms(p) for pid, p in projects.items()}
    for o in s.scalars(select(Opportunity).where(Opportunity.kind.in_(LEARN_KINDS))).all():
        dom = root_domain(o.domain or domain_of(o.url))
        if not dom or o.project_id not in projects:
            continue
        st = stats[dom]
        if o.project_id not in st["pids"]:
            st["pids"].add(o.project_id)
            st["projects"] += 1
        d = o.data or {}
        st["name"] = st["name"] or o.platform or o.title
        st["url"] = st["url"] or o.url
        st["tier"] = st["tier"] or d.get("tier") or d.get("category") or "niche"
        st["kind"] = st["kind"] or d.get("type") or d.get("category") or ""
        if o.status == "done":
            st["wins"] += 1
            st["types"].add(projects[o.project_id].type)
            st["terms"] |= terms[o.project_id]
        elif o.status == "rejected":
            st["rejects"] += 1
        elif o.kind == "niche_site":
            st["terms"] |= terms[o.project_id]  # found relevant for this niche, not yet proven
    for el in s.scalars(select(EarnedLink)).all():
        dom = root_domain(domain_of(el.source_url))
        if dom not in stats or el.status != "live":
            continue
        st = stats[dom]
        st["live"] += 1
        st["dofollow"] += bool(el.dofollow)
        if el.score is not None:
            st["link_scores"].append(el.score)
        if el.project_id in projects:
            st["types"].add(projects[el.project_id].type)
            st["terms"] |= terms.get(el.project_id, set())
    have = {ls.domain: ls for ls in s.scalars(select(LearnedSite)).all()}
    for dom, st in stats.items():
        ls = have.get(dom) or LearnedSite(domain=dom)
        ls.name, ls.url, ls.tier, ls.kind = st["name"][:200], st["url"], st["tier"][:30], st["kind"][:30]
        ls.types, ls.niche_terms = sorted(st["types"]), sorted(st["terms"])[:60]
        ls.projects, ls.wins, ls.rejects = st["projects"], st["wins"], st["rejects"]
        ls.live_links, ls.dofollow_links = st["live"], st["dofollow"]
        ls.avg_link_score = round(sum(st["link_scores"]) / len(st["link_scores"]), 1) if st["link_scores"] else None
        ls.score = site_score(st)
        if dom not in have:
            s.add(ls)
    return len(stats)


def suggestions(s: Session, project: Project, limit: int = 40) -> list[LearnedSite]:
    """Proven sites from OTHER projects that fit this one (same type, or overlapping niche words)."""
    mine = niche_terms(project)
    own = {root_domain(d) for d in s.scalars(select(Opportunity.domain).where(Opportunity.project_id == project.id)).all()}
    out = []
    for ls in s.scalars(select(LearnedSite).where(LearnedSite.score > 0, LearnedSite.wins + LearnedSite.live_links > 0)
                        .order_by(LearnedSite.score.desc()).limit(500)):
        if ls.domain in own or ls.domain == root_domain(project.domain):
            continue
        overlap = len(mine & set(ls.niche_terms or []))
        generic = ls.tier in ("profile", "citation", "content", "web2", "docs", "curation", "social")
        if (project.type in (ls.types or []) and (generic or overlap)) or overlap >= 2:
            out.append(ls)
        if len(out) >= limit:
            break
    return out
