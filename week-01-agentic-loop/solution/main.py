"""Run the agent from the command line.

    python main.py "What do I have on Wednesday?"
    python main.py --route "List the files"        # classify first, then pick a model
"""

import sys

from agent import run_agent, run_routed

DEFAULT_TASK = (
    "Which open tasks are due before my ML midterm on Friday, how many hours of work "
    "are they in total, and how much free time do I have between 09:00 and 18:00 from "
    "Monday to Thursday? Is it enough?"
)


def main() -> None:
    args = sys.argv[1:]
    routed = "--route" in args
    task = " ".join(a for a in args if a != "--route") or DEFAULT_TASK

    result = run_routed(task)[1] if routed else run_agent(task)
    print("\n" + "═" * 60)
    print(result.answer)
    print(f"\n[{result.stop} after {result.turns} turns · "
          f"{result.input_tokens} in / {result.output_tokens} out tokens]")


if __name__ == "__main__":
    main()
