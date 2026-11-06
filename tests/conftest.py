import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ADMIN_PASSWORD"] = "pw"
os.environ["SECRET_KEY"] = "test-secret"
for k in ("AHREFS_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "ANTHROPIC_API_KEY"):
    os.environ[k] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from app.db import Base, engine, init_db  # noqa: E402
from app.registry import load_plugins  # noqa: E402

load_plugins()


@pytest.fixture(autouse=True)
def fresh_db():
    init_db()
    yield
    Base.metadata.drop_all(engine)
