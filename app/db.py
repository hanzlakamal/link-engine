"""Database engine/session. One engine per process, one session per unit of work.

Unlike the legacy app (one shared sqlite connection across threads), every request
and every worker job gets its own session from a pooled engine.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import base_settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


engine = _make_engine(base_settings().database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Create tables. TODO(upgrade): switch to Alembic migrations once the schema settles."""
    from sqlalchemy import inspect, text

    from app import models  # noqa: F401  (registers tables)

    Base.metadata.create_all(engine)
    # Forward-only mini-migration: add new columns to existing tables (names come from our models only).
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                ctype = col.type.compile(dialect=engine.dialect)
                default = ""
                arg = getattr(col.default, "arg", None)
                if isinstance(arg, bool):
                    default = f" DEFAULT {'TRUE' if arg else 'FALSE'}" if engine.dialect.name == "postgresql" else f" DEFAULT {int(arg)}"
                elif isinstance(arg, (int, float)):
                    default = f" DEFAULT {arg}"
                elif isinstance(arg, str):
                    default = " DEFAULT '" + arg.replace("'", "''") + "'"
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ctype}{default}"))


@contextmanager
def session_scope():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db():
    """FastAPI dependency."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
