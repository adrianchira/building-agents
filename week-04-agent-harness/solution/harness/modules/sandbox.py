"""Show a change before it happens. Mistakes stay contained."""

from contextlib import contextmanager
from dataclasses import dataclass

import lifedb
import life_tools
from agent_core import execute_tool
from providers import ToolResult


@dataclass
class Box:
    """What a sandbox hands back: a preview for the human, maybe the result already, and keep or not."""
    preview: str
    result: ToolResult | None = None
    keep: bool = False


def fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


@contextmanager
def no_sandbox(call, tools):
    """Nothing to dry-run: the human sees the call itself, and it runs only after a yes."""
    yield Box(preview=f"  {call.name}({fmt_args(call.input)})")


@contextmanager
def sqlite_sandbox(call, tools):
    """Run the call inside a transaction, show the diff, COMMIT on a yes, ROLLBACK otherwise."""
    with life_tools.LOCK:
        conn = life_tools.rw()
        before = lifedb.snapshot(conn)
        conn.execute("BEGIN")
        box = Box(preview="")
        try:
            box.result = execute_tool(call, tools)
            box.preview = lifedb.diff(before, lifedb.snapshot(conn))
            yield box
        finally:
            conn.execute("COMMIT" if box.keep else "ROLLBACK")
