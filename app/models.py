"""Data model.

Design notes (for upgrades):
- Everything hangs off Project -> multi-client / multi-brand isolation.
- Opportunity is deliberately generic: `kind` covers links (self_publish, link_gap,
  broken, mention, resource), PR (pr_request, gift_guide) and marketing (creator,
  community, directory, marketplace). New kinds need no schema change; extra fields go
  in `data` (JSON).
- `data`/`settings` JSON columns are the escape hatch for new features before they
  deserve real columns.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    client: Mapped[str] = mapped_column(String(200), default="")
    name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    # launch = new site (self-publish + creators + launch playbook first)
    # growth = established (link gap, PR, broken links, scale)
    stage: Mapped[str] = mapped_column(String(20), default="launch")
    niche: Mapped[str] = mapped_column(String(200), default="")
    shop_platform: Mapped[str] = mapped_column(String(50), default="")  # shopify, woocommerce, ...
    brand_voice: Mapped[dict] = mapped_column(JSON, default=dict)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # overrides on top of config.DEFAULTS
    # Set when discovery needs a human (e.g. new site with no competitor data).
    needs_input: Mapped[str] = mapped_column(Text, default="")

    competitors: Mapped[list[Competitor]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Competitor(TimestampMixin, Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("project_id", "domain"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    domain: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(30), default="manual")  # manual | ahrefs | dataforseo | serp
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    domain_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    refdomains: Mapped[int | None] = mapped_column(Integer, nullable=True)
    traffic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backlinks_pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped[Project] = relationship(back_populates="competitors")


class Backlink(TimestampMixin, Base):
    """A raw link pointing at a competitor (or at us), as reported by a provider."""

    __tablename__ = "backlinks"
    __table_args__ = (UniqueConstraint("competitor_id", "source_url", "target_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    competitor_id: Mapped[int | None] = mapped_column(ForeignKey("competitors.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str] = mapped_column(String(255), index=True)
    target_url: Mapped[str] = mapped_column(Text, default="")
    anchor: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    dofollow: Mapped[bool] = mapped_column(Boolean, default=True)
    domain_rating: Mapped[float] = mapped_column(Float, default=0)
    traffic: Mapped[int] = mapped_column(Integer, default=0)
    page_type: Mapped[str] = mapped_column(String(255), default="")
    is_spam: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[str] = mapped_column(String(40), default="")
    # classification (app/classify.py)
    platform: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(40), default="")  # blog_platform, qa, social, ...
    subtype: Mapped[str] = mapped_column(String(40), default="")  # gift_guide, review_giveaway, charity, ...
    acquisition: Mapped[str] = mapped_column(String(30), default="")  # self_publish | outreach | pr | skip
    provider: Mapped[str] = mapped_column(String(30), default="")


class Opportunity(TimestampMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (UniqueConstraint("project_id", "kind", "key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(255))  # dedupe key, e.g. platform name or domain
    title: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(80), default="")
    score: Mapped[float] = mapped_column(Float, default=0, index=True)
    competitors_count: Mapped[int] = mapped_column(Integer, default=0)
    # new -> approved -> in_progress -> done | rejected | snoozed
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    reason: Mapped[str] = mapped_column(Text, default="")  # why it scored / why rejected
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ContentItem(TimestampMixin, Base):
    """Anything we publish or send: article, answer, pin, social post, pitch email."""

    __tablename__ = "content_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    channel: Mapped[str] = mapped_column(String(50), index=True)
    content_type: Mapped[str] = mapped_column(String(40), default="post")
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    target_url: Mapped[str] = mapped_column(Text, default="")  # page on our site we link to
    # draft -> pending_approval -> approved -> scheduled -> published | rejected | failed
    status: Mapped[str] = mapped_column(String(20), default="pending_approval", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_url: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class PlatformAccount(TimestampMixin, Base):
    __tablename__ = "platform_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(50))
    persona: Mapped[str] = mapped_column(String(30), default="brand")  # brand | founder
    handle: Mapped[str] = mapped_column(String(200), default="")
    secret: Mapped[str] = mapped_column(Text, default="")  # encrypted JSON (tokens / passwords)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Task(TimestampMixin, Base):
    """A playbook step. owner: auto (tool does it), approve (tool drafts, human OKs), human."""

    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    playbook: Mapped[str] = mapped_column(String(60), index=True)
    module: Mapped[str] = mapped_column(String(40), default="")  # links, social, creators, pr, store, ads, email
    day: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(20), default="approve")
    status: Mapped[str] = mapped_column(String(20), default="todo", index=True)  # todo | doing | done | skipped
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class EarnedLink(TimestampMixin, Base):
    __tablename__ = "earned_links"
    __table_args__ = (UniqueConstraint("project_id", "source_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    target_url: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(40), default="")  # mirrors Opportunity.kind
    dofollow: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="live")  # live | lost | pending
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id", ondelete="SET NULL"))


class Job(TimestampMixin, Base):
    """DB-backed job queue. TODO(upgrade): swap for Redis/arq if volume demands it."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSON, default=dict)


class Event(Base):
    """Activity feed + alerts for the dashboard and digests."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    level: Mapped[str] = mapped_column(String(10), default="info")  # info | win | warn | action
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ApiUsage(Base):
    __tablename__ = "api_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(30), index=True)
    endpoint: Mapped[str] = mapped_column(String(120), default="")
    units: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AppSetting(Base):
    """Global settings edited in the UI. Secrets are encrypted (app/security.py)."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ActionLog(Base):
    """One row per rate-limited action (post, email, comment) -> app/limits.py counts these."""

    __tablename__ = "action_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(50), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
