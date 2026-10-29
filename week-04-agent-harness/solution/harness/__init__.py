"""Alex's agent harness, packaged (week 4 homework, reference solution).

    events.py        Event, Limits, step_cost
    core.py          Harness (run + act), Held
    context.py       desk_tokens, step_starts, SummaryTail
    modules/         permissions, sandbox, skills, memory
    doors/           interactive (SteeringQueue, chat), remote (triage + CLI), webhook
    observe.py       show, turn_table, record, replay, calls
    alex.py          Alex's setup: tools, policy, system prompt, the benchmark

The harness uses the week's shared modules (providers.py, lifedb.py, life_tools.py, agent_core.py)
from the folder above `solution/`.
"""
import sys
from pathlib import Path

WEEK_DIR = Path(__file__).resolve().parents[2]          # week-04-agent-harness/
if str(WEEK_DIR) not in sys.path:
    sys.path.insert(0, str(WEEK_DIR))

from .core import Harness, Held  # noqa: E402
from .events import Event, Limits  # noqa: E402

__all__ = ["Harness", "Held", "Event", "Limits"]
