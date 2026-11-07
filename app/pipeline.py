"""Discovery pipeline: competitors -> backlinks -> classification -> opportunities.

Each step is idempotent and runs as a worker job (see app/worker.py), so it can be
re-run safely, scheduled, or triggered from the UI.
"""
from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import providers as prov
import csv
import io

from app.catalog import lookup
from app.classify import classify, domain_of, root_domain
from app.config import merged_settings
from app.models import ApiUsage, Backlink, Competitor, Event, Project, utcnow
from app.registry import strategies


def _usage_cb(s: Session, project_id: int | None):
    def cb(provider: str, endpoint: str, units: float):
        s.add(ApiUsage(project_id=project_id, provider=provider, endpoint=endpoint, units=units))
    return cb


def over_budget(s: Session, project: Project, cfg: dict) -> tuple[bool, float]:
    budget = cfg["discovery"].get("monthly_unit_budget") or 0
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = s.scalar(select(func.coalesce(func.sum(ApiUsage.units), 0)).where(
        ApiUsage.project_id == project.id, ApiUsage.provider == "ahrefs", ApiUsage.created_at >= month_start)) or 0
    return (budget > 0 and used >= budget), float(used)


def _provider(s: Session, project: Project, cfg: dict):
    p = prov.pick(cfg["discovery"]["providers"], usage_cb=_usage_cb(s, project.id))
    if p is None:
        project.needs_input = "No backlink data provider configured. Add AHREFS_API_KEY or DATAFORSEO_LOGIN/PASSWORD."
        s.add(Event(project_id=project.id, level="action", message=project.needs_input))
    return p


def event(s: Session, project_id: int | None, message: str, level: str = "info", **data) -> None:
    s.add(Event(project_id=project_id, level=level, message=message, data=data))


def is_platform_not_competitor(domain: str, cfg: dict) -> bool:
    """Marketplaces/social/news show up as organic competitors but are channels, not rivals."""
    if domain in set(cfg["discovery"].get("never_competitors", [])):
        return True
    return lookup(domain, cfg.get("catalog_extra")) is not None


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
    skipped = []
    for c in found:
        if is_platform_not_competitor(c.domain, cfg):
            skipped.append(c.domain)  # Amazon, Etsy, Pinterest... are channels, not competitors
            continue
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
    d = cfg["discovery"]
    targets: list[tuple[int | None, str]] = [(None, project.domain)] if d["pull_own_backlinks"] else []
    fresh_cutoff = utcnow() - timedelta(days=d["refresh_days"])
    for c in project.competitors:
        if not c.confirmed or (competitor_id is not None and c.id != competitor_id):
            continue
        pulled = c.backlinks_pulled_at
        if pulled is not None and pulled.tzinfo is None:
            pulled = pulled.replace(tzinfo=timezone.utc)
        if competitor_id is None and pulled and pulled > fresh_cutoff:
            continue  # pulled recently; explicit single-competitor pulls bypass this
        targets.append((c.id, c.domain))
    over, used = over_budget(s, project, cfg)
    if over:
        msg = f"Monthly API budget reached ({used:.0f}/{d['monthly_unit_budget']} units). Raise it in Settings to continue."
        event(s, project.id, msg, "action")
        return {"status": "budget", "used": used}

    total = 0
    for comp_id, dom in targets:
        try:
            links = p.backlinks(dom, d["backlinks_per_competitor"], d["min_link_dr"], d["include_traffic"])
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
                platform=c.platform, category=c.category, subtype=c.subtype, acquisition=c.acquisition, provider=p.name,
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
        b.platform, b.category, b.subtype, b.acquisition = c.platform, c.category, c.subtype, c.acquisition
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


def import_backlinks_csv(s: Session, project: Project, text: str, competitor_domain: str | None,
                         source: str = "csv") -> dict:
    """Import an Ahrefs / DataForSEO / generic CSV export.

    Recognised columns (any subset): url_from | Referring page URL | source_url, domain_rating_source | DR |
    Domain rating, traffic_domain | Domain traffic, is_dofollow | Nofollow, anchor, title, is_spam.
    competitor_domain=None imports links pointing at OUR site.
    """
    cfg = merged_settings(project.settings)
    comp_id = None
    if competitor_domain:
        d = domain_of(competitor_domain)
        comp = s.scalar(select(Competitor).where(Competitor.project_id == project.id, Competitor.domain == d))
        if comp is None:
            comp = Competitor(project_id=project.id, domain=d, source=source, confirmed=True)
            s.add(comp)
            s.flush()
        comp_id = comp.id
        comp.backlinks_pulled_at = utcnow()

    def col(row, *names, default=""):
        low = {(k or "").strip().lower(): v for k, v in row.items()}
        for n in names:
            v = low.get(n.lower())
            if v not in (None, ""):
                return v
        return default

    def truthy(v):
        return str(v).strip().lower() in ("1", "true", "yes", "dofollow")

    seen = {b.source_url for b in s.scalars(select(Backlink).where(
        Backlink.project_id == project.id,
        Backlink.competitor_id.is_(None) if comp_id is None else Backlink.competitor_id == comp_id))}
    n = 0
    for row in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        url = col(row, "url_from", "Referring page URL", "source_url", "url")
        if not url or url in seen:
            continue
        seen.add(url)
        nofollow = col(row, "Nofollow", default=None)
        dofollow = truthy(col(row, "is_dofollow", "dofollow", default="1")) if nofollow is None else not truthy(nofollow)
        dr = float(col(row, "domain_rating_source", "DR", "Domain rating", default="0") or 0)
        traffic = int(float(col(row, "traffic_domain", "Domain traffic", default="0") or 0))
        title = col(row, "title", "Referring page title")
        spam = truthy(col(row, "is_spam", default="0"))
        c = classify(url, title, "", spam, cfg["quality"], cfg.get("catalog_extra"))
        s.add(Backlink(project_id=project.id, competitor_id=comp_id, source_url=url,
                       source_domain=root_domain(domain_of(url)), anchor=col(row, "anchor", "Anchor"), title=title,
                       dofollow=dofollow, domain_rating=dr, traffic=traffic, is_spam=spam, platform=c.platform,
                       category=c.category, subtype=c.subtype, acquisition=c.acquisition, provider=source))
        n += 1
    event(s, project.id, f"Imported {n} backlinks for {competitor_domain or project.domain} from {source}.")
    return {"imported": n}


def disavow_file(s: Session, project: Project) -> str:
    """Google disavow file for spam links pointing at OUR domain. Upload only if they ever cause a problem."""
    doms = sorted({b.source_domain for b in s.scalars(select(Backlink).where(
        Backlink.project_id == project.id, Backlink.competitor_id.is_(None), Backlink.is_spam.is_(True)))})
    head = (f"# Disavow file for {project.domain} generated by Link Engine on {utcnow():%Y-%m-%d}\n"
            "# Google ignores most spam automatically; upload only after a manual action or clear ranking hit.\n")
    return head + "\n".join(f"domain:{d}" for d in doms) + ("\n" if doms else "")
