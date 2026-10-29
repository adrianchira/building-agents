"""Door 2: nobody at the keyboard. Changes are held for Alex; many harnesses run in parallel.

    python -m harness.doors.remote "What's on Thursday?"
    python -m harness.doors.remote --triage

Cron, every weekday at 7:00 (from the solution/ folder):
    0 7 * * 1-5  cd /path/to/week-04-agent-harness/solution && ../../.venv/bin/python -m harness.doors.remote --triage
"""

import sys
from concurrent.futures import ThreadPoolExecutor

from agent_core import execute_tool
from providers import ToolCall

from ..core import Harness, Held
from ..observe import run


def triage_task(email: dict) -> str:
    return (f"New email from {email['from']}, subject '{email['subject']}':\n\n{email['body']}\n\n"
            "Handle it for Alex: update the calendar if needed and draft a reply if one is needed. "
            "Alex reviews everything in the morning.")


def morning_triage(emails: list[dict], make_harness, *, quiet: bool = False) -> dict[str, tuple[Harness, list]]:
    """One headless harness per email, in parallel. `make_harness(name)` builds each one."""
    harnesses = {e["id"]: make_harness(e["id"]) for e in emails}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {e["id"]: pool.submit(run, harnesses[e["id"]], triage_task(e), quiet=quiet, tag=True)
                   for e in emails}
        return {k: (harnesses[k], f.result()) for k, f in futures.items()}


def approve(held: Held, tools: dict) -> str:
    """Alex said yes in the morning: do it for real now (it can still fail if the calendar changed)."""
    return execute_tool(ToolCall("approved", held.tool, held.args), tools).content


def main(argv: list[str]) -> None:
    import life_tools
    from providers import load_api_key
    from .. import alex
    from ..observe import final

    load_api_key("openai")          # from the course's .env
    alex.fresh_week()
    if argv == ["--triage"]:
        for name, (h, events) in morning_triage(life_tools.inbox(), alex.remote_harness, quiet=True).items():
            print(f"[{name}] {final(events)}  ({len(h.held)} change(s) held)")
    elif argv:
        run(alex.remote_harness("cli"), " ".join(argv))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
