# Makes `import agent` work when running plain `pytest` from this folder,
# and gives every test its own fresh copy of the life database.
import pytest

from agent import db


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    path = db.create(tmp_path / "life.db")
    yield path
    db.use(path)  # closes the shared write connection
