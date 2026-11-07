from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Project, Task


@dataclass
class TaskSpec:
    day: int
    module: str  # foundation | store | social | creators | links | pr | community | email | ads | measure
    title: str
    detail: str = ""
    owner: str = "approve"  # auto | approve | human
    data: dict = field(default_factory=dict)


class Playbook(ABC):
    name = "base"
    label = ""
    description = ""
    stage = "launch"
    days = 3
    types: tuple[str, ...] = ("ecommerce", "affiliate", "local", "saas")

    @abstractmethod
    def tasks(self, project: Project, start: date) -> list[TaskSpec]: ...

    def apply(self, s: Session, project: Project, start: date | None = None) -> int:
        from sqlalchemy import select

        start = start or date.today()
        have = set(s.scalars(select(Task.title).where(Task.project_id == project.id, Task.playbook == self.name)).all())
        n = 0
        for t in self.tasks(project, start):
            if t.title in have:  # re-applying never duplicates tasks or resets their status
                continue
            have.add(t.title)
            due = datetime.combine(start + timedelta(days=max(t.day, 0)), time(17, 0), tzinfo=timezone.utc)
            s.add(Task(project_id=project.id, playbook=self.name, module=t.module, day=t.day, title=t.title,
                       detail=t.detail, owner=t.owner, due_at=due, data=t.data))
            n += 1
        return n
