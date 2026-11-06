"""Frequency control. Every rate-limited action goes through `allow()` + `record()`.

Limits come from project settings (config.DEFAULTS['limits']), so they're editable per
project and per channel. Email gets a warm-up ramp.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ActionLog


def daily_cap(cfg: dict, channel: str, account_age_days: int | None = None) -> int:
    lim = cfg["limits"]
    if channel == "email" and account_age_days is not None:
        r = lim["email_ramp"]
        weeks = max(r["weeks"], 1)
        step = (r["max"] - r["start"]) / weeks
        return int(min(r["max"], r["start"] + step * (account_age_days // 7)))
    return int(lim["per_channel_per_day"].get(channel, lim["default_per_day"]))


def used_today(s: Session, project_id: int, channel: str, account_id: int | None = None) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    q = select(func.count()).select_from(ActionLog).where(
        ActionLog.project_id == project_id, ActionLog.channel == channel, ActionLog.created_at >= since)
    if account_id is not None:
        q = q.where(ActionLog.account_id == account_id)
    return s.scalar(q) or 0


def in_business_hours(cfg: dict, now_local_hour: int) -> bool:
    start, end = cfg["limits"]["business_hours"]
    return start <= now_local_hour < end


def allow(s: Session, cfg: dict, project_id: int, channel: str, account_id: int | None = None,
          account_age_days: int | None = None) -> tuple[bool, str]:
    cap = daily_cap(cfg, channel, account_age_days)
    used = used_today(s, project_id, channel, account_id)
    if used >= cap:
        return False, f"{channel}: daily cap reached ({used}/{cap})"
    return True, f"{channel}: {used}/{cap} used"


def record(s: Session, project_id: int, channel: str, account_id: int | None = None) -> None:
    s.add(ActionLog(project_id=project_id, channel=channel, account_id=account_id))


def next_slot(cfg: dict, after: datetime) -> datetime:
    lo, hi = cfg["limits"]["jitter_minutes"]
    return after + timedelta(minutes=random.uniform(lo, hi))
