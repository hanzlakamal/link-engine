"""CLI: python -m app.importer <project_domain> <csv_path> [competitor_domain]"""
import sys
from pathlib import Path

from sqlalchemy import select

from app import pipeline
from app.db import init_db, session_scope
from app.models import Project
from app.registry import load_plugins

if __name__ == "__main__":
    load_plugins()
    init_db()
    dom, path = sys.argv[1], Path(sys.argv[2])
    comp = sys.argv[3] if len(sys.argv) > 3 else None
    with session_scope() as s:
        p = s.scalar(select(Project).where(Project.domain == dom))
        if p is None:
            sys.exit(f"No project with domain {dom}")
        print(pipeline.import_backlinks_csv(s, p, path.read_text(encoding="utf-8"), comp, source=f"csv:{path.name}"))
        s.flush()
        print(pipeline.build_opportunities(s, p))
