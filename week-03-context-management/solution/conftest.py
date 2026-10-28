# The toolkit's scripts import each other as `from common import ...`, so its folder goes on sys.path.
# Every test runs in its own temporary folder: .tool_outputs/ and memories/ never land in the repo.
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "context_toolkit"))


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REAL_LLM", raising=False)
