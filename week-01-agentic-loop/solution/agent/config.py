"""Settings shared by every module. Change things here, not inside the loop."""

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .simweek import Week, find_template_dir, sim_monday

load_dotenv(find_dotenv(usecwd=True))  # .env holds API keys, and may pin LIFE_TODAY

PROVIDER = "openai"   # "openai" | "anthropic" | "ollama"  (see providers.py)
MODEL = "gpt-6-luna"  # e.g. "claude-opus-5-5" with PROVIDER = "anthropic"
EFFORT = None         # None = provider default; or "low" | "medium" | "high"
MAX_TURNS = 10

# The agent may only touch files under this folder (see tools._safe_path).
DATA_DIR = Path(
    os.environ.get("AGENT_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
).resolve()

# Alex's week follows the real calendar: build_week() writes it into DATA_DIR (see simweek.py).
LIFE_DIR = find_template_dir(Path(__file__).resolve())
WEEK = Week(sim_monday())
TODAY = WEEK.today  # e.g. "Monday 2026-10-12": the simulated "now"

SYSTEM_PROMPT = (
    "You are a personal assistant for Alex, a 44-year-old software developer with a full-time "
    f"job and two kids, who is retraining to become an AI engineer. Today is {TODAY}. "
    "Alex's calendar, task list and notes are files in a sandboxed data folder. Never do "
    "arithmetic in your head: use the calculator. When you have the answer, reply briefly "
    "and show the key numbers you used."
)

# ---------- model routing (Part 9) ----------

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

# The cheap, fast model that reads the task and picks a tier. (provider, model)
CLASSIFIER = ("openai", "gpt-6-luna")  # or ("anthropic", "claude-haiku-4-5"), ("ollama", OLLAMA_MODEL)

# For each tier, candidates in order of preference; the router takes the first one available.
ROUTES = {
    "simple":   [("ollama", OLLAMA_MODEL), ("openai", "gpt-6-luna"), ("anthropic", "claude-haiku-4-5")],
    "moderate": [("openai", "gpt-6.1-sol"), ("anthropic", "claude-sonnet-5-5")],
    "hard":     [("openai", "gpt-6-astra"), ("anthropic", "claude-opus-5-5")],
}
# When the classifier fails or is unsure, err on the side of capability.
DEFAULT_TIER = "hard"
