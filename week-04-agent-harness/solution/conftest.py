# Makes `import harness` work when running plain `pytest` from this folder.
# Tests pin Alex's week to Monday 2026-10-12, and every test gets its own database file.
import os

os.environ["LIFE_TODAY"] = "2026-10-12"

import pytest  # noqa: E402

import harness  # noqa: E402,F401  (puts the week's folder on sys.path)
import lifedb  # noqa: E402
import life_tools  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(lifedb, "DB_PATH", tmp_path / "life.db")
    lifedb.create_db(lifedb.DB_PATH)
    life_tools.reset()
    yield
    life_tools.reset()
