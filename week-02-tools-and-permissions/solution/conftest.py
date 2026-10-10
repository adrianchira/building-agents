# Makes `import agent` work when running plain `pytest` from this folder.
# Tests pin Alex's week to Monday 2026-10-12, and every test gets its own fresh database.
import os
import tempfile

os.environ["LIFE_TODAY"] = "2026-10-12"
os.environ["AGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="life-week-")

import pytest  # noqa: E402

from agent import db  # noqa: E402  (must come after the environment is set)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    path = db.create(tmp_path / "life.db")
    yield path
    db.use(path)  # closes the shared write connection
