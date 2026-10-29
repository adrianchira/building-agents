"""Alex's harness: his tools, policy, instructions and modules, plus the benchmark (door 3)."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import lifedb
import life_tools

from . import WEEK_DIR
from .core import Harness
from .events import Limits
from .modules.memory import memory_module
from .modules.permissions import always, policy_by_effect
from .modules.sandbox import sqlite_sandbox
from .modules.skills import skills_module
from .observe import calls, recorded_run
from .doors.remote import triage_task

ALL_TOOLS = {**life_tools.TOOLS, **life_tools.WRITE_TOOLS}
ALEX_POLICY = policy_by_effect(overrides={"draft_email": "allow", "remember": "allow"})
SKILLS_DIR = WEEK_DIR / "skills"
MEMORY_FILE = WEEK_DIR / "memories" / "alex.md"
RUNS = WEEK_DIR / "runs"


def system_prompt() -> str:
    week = lifedb.week()
    return ("You are Alex's personal assistant. Alex is 44, a senior backend developer with a full-time job and "
            f"two kids, retraining as an AI engineer and job-hunting. Today is {week.today}; this week runs to "
            f"{week.label(6)}. All times are Eastern. Use the tools to check facts; never guess. "
            "Keep the final answer short.")


def fresh_week() -> None:
    lifedb.create_db()
    life_tools.reset()


def alex_harness(name: str = "alex", **overrides) -> Harness:
    """Interactive defaults: skills + memory, approvals asked, changes dry-run in the sandbox."""
    settings = dict(system=system_prompt(), name=name, modules=[skills_module(SKILLS_DIR), memory_module(MEMORY_FILE)],
                    policy=ALEX_POLICY, sandbox=sqlite_sandbox, limits=Limits())
    return Harness(ALL_TOOLS, **(settings | overrides))


def remote_harness(name: str, **overrides) -> Harness:
    """Nobody at the keyboard: every change is held for Alex."""
    return alex_harness(name, **({"modules": [skills_module(SKILLS_DIR)], "approver": always("hold")} | overrides))


# ---------------------------------------------------------------- door 3: the benchmark

def booked(events) -> list[dict]:
    return [a for t, a, ok in calls(events) if ok and t in ("create_event", "move_event")]


def wrote(events, tool_name: str) -> bool:
    return any(t == tool_name and ok for t, a, ok in calls(events))


def checks() -> dict:
    w = lifedb.week()
    return {
        "northwind": lambda ev: (any(b["date"] in (w.day(1), w.day(3)) and "08:00" <= b["start"]
                                     and b["end"] <= "09:00" for b in booked(ev))
                                 and wrote(ev, "draft_email") and not wrote(ev, "send_email")),
        "brightline": lambda ev: (any(b["date"] == w.day(4) and b["start"] == "08:00" for b in booked(ev))
                                  and wrote(ev, "draft_email") and not wrote(ev, "send_email")),
        "school": lambda ev: not booked(ev) and not wrote(ev, "draft_email") and not wrote(ev, "send_email"),
    }


def benchmark(label: str, repeats: int = 3, runs_dir: Path = RUNS, **overrides) -> dict[str, list[bool]]:
    """Every email, `repeats` times, each through a fresh remote harness, in parallel, recorded to JSONL."""
    rules = checks()
    jobs = [(e, n) for e in life_tools.inbox() for n in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [(e["id"], pool.submit(recorded_run, remote_harness(f"{e['id']}-{n}", **overrides),
                                         triage_task(e), Path(runs_dir) / f"{label}-{e['id']}-{n}.jsonl",
                                         quiet=True)) for e, n in jobs]
        results: dict[str, list[bool]] = {}
        for case, f in futures:
            results.setdefault(case, []).append(rules[case](f.result()))
    return results
