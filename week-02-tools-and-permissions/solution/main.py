"""Run the assistant from the command line. Writes ask for your approval first.

    python main.py "Move my dentist appointment to Thursday 16:30"
    python main.py --route "What do I have on Wednesday?"
    python main.py --reset ...      # rebuild life.db from data/*.csv first
"""

import sys

from agent import TOOLS, apply_policy, run_agent, run_routed
from agent import db

DEFAULT_TASK = "Find me a 2-hour slot before Thursday evening to revise for the ML midterm."


def main() -> None:
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    task = " ".join(a for a in args if not a.startswith("--")) or DEFAULT_TASK
    if "--reset" in flags or not db.path().exists():
        db.create()

    tools = apply_policy(TOOLS)  # interactive: writes show a diff and wait for y/N
    result = (run_routed(task, tools=tools)[1] if "--route" in flags
              else run_agent(task, tools=tools))
    print("\n" + "═" * 60)
    print(result.answer)
    print(f"\n[{result.stop} after {result.turns} turns · "
          f"{result.input_tokens} in / {result.output_tokens} out tokens]")


if __name__ == "__main__":
    main()
