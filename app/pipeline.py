"""Discovery pipeline: competitors -> backlinks -> classification -> opportunities.

Each step is idempotent and runs as a worker job (see app/worker.py), so it can be
re-run safely, scheduled, or triggered from the UI.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import providers as prov
from app.classify import classify, domain_of
from app.config import merged_settings
from app.models import ApiUsage, Backlink, Competitor, Event, Project, utcnow
from app.registry import strategies


def _usage_cb(s: Session, project_id: int | None):
    def cb(provider: str, endpoint: str, units: float):
        s.add(ApiUsage(project_id=project_id, provider=provider, endpoint=endpoint, units=units))
    return cb


def _provider(s: Session, project: Project, cfg: dict):
    p = prov.pick(cfg["discovery"]["providers"], usage_cb=_usage_cb(s, project.id))
    if p is None:
        project.needs_input = "No backlink data provider configured. Add AHREFS_API_KEY or DATAFORSEO_LOGIN/PASSWORD."
        s.add(Event(project_id=project.id, level="action", message=project.needs_input))
    return p


def event(s: Session, project_id: int | None, message: str, level: str = "info", **data) -> None:
    s.add(Event(project_id=project_id, level=level, message=message, data=data))


def discover_competitors(s: Session, project: Project) -> dict:
    """Auto-discover competitors. If none have enough data (new sites), ask the user for one."""
    cfg = merged_settings(project.settings)
    p = _provider(s, project, cfg)
    if p is None:
        return {"status": "needs_input"}
    d = cfg["discovery"]
    found = []
    try:
        found = p.competitors(project.domain, cfg["market"]["country"], d["max_competitors"])
    except prov.ProviderError as e:
        event(s, project.id, f"Competitor discovery failed: {e}", "warn")

    existing = {c.domain for c in project.competitors}
    for c in found:
        if c.domain not in existing and c.domain != project.domain:
            s.add(Competitor(project_id=project.id, domain=c.domain, source=p.name,
                             domain_rating=c.domain_rating, traffic=c.traffic,
                             data={"common_keywords": c.common_keywords}))
            existing.add(c.domain)
    s.flush()
    s.refresh(project)

    # Is there at least one competitor (manual or found) with enough link data?
    rich = []
    for comp in project.competitors:
        if comp.refdomains is None:
            try:
                m = p.metrics(comp.domain, cfg["market"]["country"])
                comp.refdomains, comp.domain_rating = m.refdomains, m.domain_rating or comp.domain_rating
                comp.traffic = m.traffic or comp.traffic
            except prov.ProviderError as e:
                event(s, project.id, f"Metrics failed for {comp.domain}: {e}", "warn")
                continue
        if (comp.refdomains or 0) >= d["min_competitor_refdomains"]:
            rich.append(comp)
            if comp.source == "manual":
                comp.confirmed = True

    if not rich:
        project.needs_input = (
            f"Couldn't find a competitor with at least {d['min_competitor_refdomains']} referring domains for "
            f"{project.domain} (common for new sites). Add at least one established competitor to continue."
        )
        event(s, project.id, project.needs_input, "action")
        return {"status": "needs_input", "found": len(found)}

    project.needs_input = ""
    event(s, project.id, f"Competitors ready: {len(rich)} with enough data ({len(found)} auto-discovered).", "info")
    return {"status": "ok", "found": len(found), "rich": [c.domain for c in rich]}


def pull_backlinks(s: Session, project: Project, competitor_id: int | None = None) -> dict:
    """Pull backlinks for confirmed competitors (and for our own domain, to compute the gap)."""
    cfg = merged_settings(project.settings)
    p = _provider(s, project, cfg)
    if p is None:
        return {"status": "needs_input"}
    targets: list[tuple[int | None, str]] = [(None, project.domain)]
    for c in project.competitors:
        if c.confirmed and (competitor_id is None or c.id == competitor_id):
            targets.append((c.id, c.domain))

    total = 0
    for comp_id, dom in targets:
        try:
            links = p.backlinks(dom, cfg["discovery"]["backlinks_per_competitor"])
        except prov.ProviderError as e:
            event(s, project.id, f"Backlink pull failed for {dom}: {e}", "warn")
            continue
        seen = {(b.source_url, b.target_url) for b in s.scalars(select(Backlink).where(
            Backlink.project_id == project.id,
            Backlink.competitor_id.is_(None) if comp_id is None else Backlink.competitor_id == comp_id))}
        for rb in links:
            if (rb.source_url, rb.target_url) in seen:
                continue
            c = classify(rb.source_url, rb.title, rb.page_type, rb.is_spam, cfg["quality"], cfg.get("catalog_extra"))
            s.add(Backlink(
                project_id=project.id, competitor_id=comp_id, source_url=rb.source_url,
                source_domain=rb.source_domain or domain_of(rb.source_url), target_url=rb.target_url,
                anchor=rb.anchor, title=rb.title, dofollow=rb.dofollow, domain_rating=rb.domain_rating,
                traffic=rb.traffic, page_type=rb.page_type, is_spam=rb.is_spam, first_seen=rb.first_seen,
                platform=c.platform, category=c.category, acquisition=c.acquisition, provider=p.name,
            ))
            total += 1
        if comp_id:
            comp = s.get(Competitor, comp_id)
            comp.backlinks_pulled_at = utcnow()
    event(s, project.id, f"Pulled {total} new backlinks from {len(targets)} domains via {p.name}.")
    return {"status": "ok", "new_backlinks": total}


def reclassify(s: Session, project: Project) -> int:
    """Re-run classification after catalog/quality settings change (no API cost)."""
    cfg = merged_settings(project.settings)
    n = 0
    for b in s.scalars(select(Backlink).where(Backlink.project_id == project.id)):
        c = classify(b.source_url, b.title, b.page_type, b.is_spam, cfg["quality"], cfg.get("catalog_extra"))
        b.platform, b.category, b.acquisition = c.platform, c.category, c.acquisition
        n += 1
    return n


def build_opportunities(s: Session, project: Project) -> dict:
    cfg = merged_settings(project.settings)
    enabled = cfg.get("strategies")  # explicit list overrides stage defaults
    out = {}
    for name, cls in strategies.items():
        strat = cls()
        if not strat.ready:
            continue
        if enabled is not None and name not in enabled:
            continue
        if enabled is None and project.stage not in strat.stages:
            continue
        out[name] = strat.run(s, project, cfg)
    event(s, project.id, "Opportunities refreshed: " + ", ".join(f"{k}={v}" for k, v in out.items()), "win")
    return out
