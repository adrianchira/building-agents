"""Settings shared by every module. Change things here, not inside the loop."""

import os
from pathlib import Path

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT = "medium"  # low | medium | high | xhigh | max  -- trades thoroughness for tokens
MAX_TURNS = 10

# On a safety refusal, the API re-runs the request on a fallback model it picks.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# The agent may only touch files under this folder (see tools._safe_path).
DATA_DIR = Path(
    os.environ.get("AGENT_DATA_DIR", Path(__file__).resolve().parents[2] / "data")
).resolve()

TODAY = "Monday 2026-10-12"  # the simulated "now" of the sample data

SYSTEM_PROMPT = (
    f"You are a personal assistant for a busy university student. Today is {TODAY}. "
    "Their calendar, task list and notes are files in a sandboxed data folder. Never do "
    "arithmetic in your head: use the calculator. When you have the answer, reply briefly "
    "and show the key numbers you used."
)

# ---------- model routing (Part 9) ----------

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

# The cheap, fast model that reads the task and picks a tier. (provider, model)
CLASSIFIER = ("anthropic", "claude-haiku-4-5")

# For each tier, candidates in order of preference; the router takes the first one available.
ROUTES = {
    "simple":   [("ollama", OLLAMA_MODEL), ("openai", "gpt-6-luna"), ("anthropic", "claude-haiku-4-5")],
    "moderate": [("openai", "gpt-6.1-sol"), ("anthropic", "claude-sonnet-5-5")],
    "hard":     [("anthropic", "claude-opus-5-5"), ("openai", "gpt-6-astra")],
}
# When the classifier fails or is unsure, err on the side of capability.
DEFAULT_TIER = "hard"
