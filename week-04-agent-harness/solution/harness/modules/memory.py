"""Notes that survive between sessions: read into the instructions at the start, added to with `remember`."""

from pathlib import Path

from pydantic import Field

from agent_core import WRITE, tool
from life_tools import Args


def memory_module(path: str | Path) -> dict:
    file = Path(path)

    class RememberIn(Args):
        fact: str = Field(min_length=3, max_length=300, description="One short fact, in Alex's words")

    def remember(fact: str) -> str:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as f:
            f.write(f"- {fact}\n")
        return "Remembered."

    notes = file.read_text(encoding="utf-8") if file.exists() else "(nothing yet)"
    return {"system": f"What you remember about Alex from earlier sessions (his rules: follow them):\n{notes}\n"
                      "When Alex tells you something to keep for next time, call remember.",
            "tools": {"remember": tool(remember, input_model=RememberIn, effect=WRITE, description=
                                       "Save one fact about Alex for future sessions.")}}
