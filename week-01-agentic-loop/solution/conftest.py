# Makes `import agent` work when running plain `pytest` from this folder.
# Tests pin Alex's week to Monday 2026-10-12 and write it into a temporary folder.
import os
import tempfile

os.environ["LIFE_TODAY"] = "2026-10-12"
os.environ["AGENT_DATA_DIR"] = tempfile.mkdtemp(prefix="life-week-")

from agent import config  # noqa: E402  (must come after the environment is set)
from agent.simweek import build_week  # noqa: E402

build_week(config.DATA_DIR, template_dir=config.LIFE_DIR)
