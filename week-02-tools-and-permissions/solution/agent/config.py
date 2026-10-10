"""Settings shared by every module. Change things here, not inside the loop."""

import os
from pathlib import Path

PROVIDER = "openai"   # "openai" | "anthropic" | "ollama"  (see providers.py)
MODEL = "gpt-6-luna"  # e.g. "claude-opus-5-5" with PROVIDER = "anthropic"
EFFORT = None         # None = provider default; or "low" | "medium" | "high"
MAX_TURNS = 12

_HERE = Path(__file__).resolve()
DATA_DIR = Path(os.environ.get("AGENT_DATA_DIR", _HERE.parents[2] / "data")).resolve()
DB_PATH = Path(os.environ.get("AGENT_DB", _HERE.parents[1] / "life.db")).resolve()

TODAY = "Monday 2026-10-12"  # the simulated "now" of the sample data

SYSTEM_PROMPT = (
    "You are a personal assistant for Alex, a 44-year-old software developer with a full-time "
    f"job and two kids, who is retraining to become an AI engineer. Today is {TODAY}. "
    "Use the tools to look at Alex's calendar, tasks and notes; never guess. "
    "Never do arithmetic in your head: use the calculator. Before changing anything, "
    "make sure you have the right event or task id. Reply briefly."
)

# ---------- tools: limits ----------
MAX_ROWS = 40          # tool outputs longer than this are cut, with a note on how to narrow down
TOOL_TIMEOUT_S = 10.0  # a tool that takes longer is abandoned and reported to the model
RETRY_ATTEMPTS = 3     # for transient failures (e.g. "database is locked"), handled by OUR code

# ---------- permissions ----------
# What happens for each kind of tool: allow | ask | deny
POLICY = {"read": "allow", "write": "ask", "destructive": "ask"}
# Per-tool exceptions, e.g. {"cancel_event": "deny"}
POLICY_OVERRIDES: dict[str, str] = {}

# ---------- model routing (week 1, Part 9) ----------

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

CLASSIFIER = ("openai", "gpt-6-luna")  # or ("anthropic", "claude-haiku-4-5"), ("ollama", OLLAMA_MODEL)

ROUTES = {
    "simple":   [("ollama", OLLAMA_MODEL), ("openai", "gpt-6-luna"), ("anthropic", "claude-haiku-4-5")],
    "moderate": [("openai", "gpt-6.1-sol"), ("anthropic", "claude-sonnet-5-5")],
    "hard":     [("openai", "gpt-6-astra"), ("anthropic", "claude-opus-5-5")],
}
DEFAULT_TIER = "hard"
