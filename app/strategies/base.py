from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Opportunity, Project


class Strategy(ABC):
    name: str = "base"
    label: str = ""
    description: str = ""
    stages: tuple[str, ...] = ("launch", "growth")  # which project stages it runs for by default
    ready: bool = True  # False = planned; shows in UI as "coming soon"

    @abstractmethod
    def run(self, s: Session, project: Project, cfg: dict) -> int:
        """Create/update Opportunity rows. Return number touched."""

    @staticmethod
    def upsert(s: Session, project_id: int, kind: str, key: str, **fields) -> Opportunity:
        opp = s.scalar(select(Opportunity).where(
            Opportunity.project_id == project_id, Opportunity.kind == kind, Opportunity.key == key))
        if opp is None:
            opp = Opportunity(project_id=project_id, kind=kind, key=key)
            s.add(opp)
        for k, v in fields.items():
            # never clobber a human decision
            if k == "status" and opp.status not in ("new", None):
                continue
            setattr(opp, k, v)
        return opp
