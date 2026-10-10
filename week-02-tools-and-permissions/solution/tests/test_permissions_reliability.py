import time
from types import SimpleNamespace as NS

import pytest

from agent import db
from agent.permissions import always, apply_policy
from agent.reliability import TransientError, with_retries, with_timeout
from agent.tools import TOOLS, execute_tool

MOVE = dict(event_id=8, date="2026-10-16", start="08:00", end="08:45")


def dentist():
    return tuple(db.rw().execute("SELECT date, start FROM events WHERE id = 8").fetchone())


def run(tools, name, **args):
    return execute_tool(NS(id="t", name=name, input=args), tools)


# ---------- permissions ----------

def test_reads_are_allowed_without_asking():
    asked = []
    tools = apply_policy(TOOLS, approver=lambda p: asked.append(p) or False)
    assert not run(tools, "list_tasks").is_error and asked == []


def test_approved_write_is_committed_and_preview_shows_diff():
    previews = []
    tools = apply_policy(TOOLS, approver=lambda p: previews.append(p) or True)
    assert not run(tools, "move_event", **MOVE).is_error
    assert dentist() == ("2026-10-16", "08:00")
    assert "- events: (8, '2026-10-14', '08:00'" in previews[0]
    assert "+ events: (8, '2026-10-16', '08:00'" in previews[0]


def test_declined_write_is_rolled_back():
    r = run(apply_policy(TOOLS, approver=always(False)), "move_event", **MOVE)
    assert r.is_error and "declined" in r.content
    assert dentist() == ("2026-10-14", "08:00")


def test_invalid_write_never_bothers_the_user():
    asked = []
    tools = apply_policy(TOOLS, approver=lambda p: asked.append(p) or True)
    r = run(tools, "move_event", **{**MOVE, "start": "19:30", "end": "20:00", "date": "2026-10-13"})
    assert r.is_error and "Conflicts" in r.content and asked == []


def test_deny_override():
    tools = apply_policy(TOOLS, approver=always(True), overrides={"cancel_event": "deny"})
    r = run(tools, "cancel_event", event_id=18)
    assert r.is_error and "turned off" in r.content
    assert db.rw().execute("SELECT 1 FROM events WHERE id = 18").fetchone()


# ---------- reliability ----------

def test_retries_hide_transient_failures():
    attempts = []
    def flaky(**kw):
        attempts.append(1)
        if len(attempts) < 3:
            raise TransientError("database is locked")
        return "ok"
    assert with_retries(flaky, attempts=3, base_delay=0)() == "ok" and len(attempts) == 3


def test_retries_give_up_with_actionable_message():
    def down(**kw):
        raise TransientError("database is locked")
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        with_retries(down, attempts=2, base_delay=0)()


def test_other_errors_are_not_retried():
    attempts = []
    def bad(**kw):
        attempts.append(1)
        raise ValueError("bad input")
    with pytest.raises(ValueError):
        with_retries(bad, attempts=3, base_delay=0)()
    assert len(attempts) == 1


def test_timeout():
    slow = with_timeout(lambda **kw: time.sleep(1) or "late", seconds=0.1)
    with pytest.raises(TimeoutError, match="timed out after 0.1s"):
        slow()


def test_crashing_approver_leaves_no_open_transaction():
    def broken(preview):
        raise KeyboardInterrupt  # user hits Ctrl+C at the prompt
    with pytest.raises(KeyboardInterrupt):
        apply_policy(TOOLS, approver=broken)["move_event"]["fn"](**MOVE)
    assert not db.rw().in_transaction
    assert dentist() == ("2026-10-14", "08:00")
