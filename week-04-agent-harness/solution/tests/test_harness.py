"""The harness with a scripted fake model: no API key, no network."""

import json
import threading
from types import SimpleNamespace as NS
from urllib.request import Request, urlopen

import pytest

import lifedb
import life_tools
from harness import Harness, Limits
from harness.context import SummaryTail, as_text, step_starts
from harness.doors.interactive import SteeringQueue
from harness.doors.remote import approve, morning_triage
from harness.doors.webhook import make_server
from harness.modules.memory import memory_module
from harness.modules.permissions import always, policy_by_effect
from harness.modules.sandbox import sqlite_sandbox
from harness.modules.skills import skills_module
from harness import alex
from harness.observe import calls, final, record, replay, run, turn_table


# ---------------------------------------------------------------- a fake OpenAI Responses API

def call(tool_name, call_id="c1", **args):
    return NS(type="function_call", call_id=call_id, name=tool_name, arguments=json.dumps(args))


def say(text):
    return NS(type="message", content=[NS(type="output_text", text=text)])


def reply(*items):
    text = " ".join(c.text for i in items if i.type == "message" for c in i.content)
    return NS(output=list(items), status="completed", output_text=text,
              usage=NS(input_tokens=100, output_tokens=10, input_tokens_details=NS(cached_tokens=0)))


class FakeClient:
    """Plays a script of model replies; remembers what each request sent."""

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []
        self.responses = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append({**kw, "input": list(kw.get("input", []))})
        return self.replies.pop(0)


def harness(client, tools=None, **kw):
    return Harness(tools or alex.ALL_TOOLS, system="test", client=client, **kw)


def kinds(events):
    return [e.kind for e in events]


def event_ids():
    return [r["id"] for r in life_tools.db_rows("SELECT id FROM events ORDER BY id")]


MOVE = dict(event_id=7, date="2026-10-15", start="08:00", end="08:30")


# ---------------------------------------------------------------- the loop

def test_loop_acts_then_stops():
    h = harness(FakeClient(reply(call("list_tasks")), reply(say("9.25 h"))))
    events = run(h, "x", quiet=True)
    assert kinds(events) == ["start", "model", "action", "observation", "model", "done"]
    assert final(events) == "9.25 h"
    assert "TOTAL est_hours" in events[3].data["text"]


def test_max_turns_stops_the_run():
    h = harness(FakeClient(*[reply(call("list_tasks", f"c{i}")) for i in range(5)]), limits=Limits(max_turns=2))
    events = run(h, "x", quiet=True)
    assert kinds(events)[-2:] == ["limit", "done"]
    assert events[-1].data["turns"] == 2 and events[-1].data["stop"] == "limit"


def test_max_cost_stops_the_run():
    h = harness(FakeClient(*[reply(call("list_tasks", f"c{i}")) for i in range(5)]), limits=Limits(max_cost=0))
    events = run(h, "x", quiet=True)
    assert events[-1].data["turns"] == 1 and "cost" in events[-2].data["reason"]


# ---------------------------------------------------------------- permissions + sandbox

def test_deny_never_runs_the_tool():
    h = harness(FakeClient(reply(call("cancel_event", event_id=7)), reply(say("ok"))),
                policy=policy_by_effect(overrides={"cancel_event": "deny"}))
    events = run(h, "x", quiet=True)
    assert 7 in event_ids() and "turned off" in events[3].data["text"] and "approval" not in kinds(events)


def test_approved_change_is_committed_and_previewed():
    h = harness(FakeClient(reply(call("move_event", **MOVE)), reply(say("moved"))),
                approver=always("yes"), sandbox=sqlite_sandbox)
    events = run(h, "x", quiet=True)
    approval = next(e for e in events if e.kind == "approval")
    assert "- events: (7, '2026-10-13', '20:30'" in approval.data["preview"]
    assert "+ events: (7, '2026-10-15', '08:00'" in approval.data["preview"]
    assert life_tools.db_rows("SELECT date FROM events WHERE id = 7")[0]["date"] == "2026-10-15"


def test_declined_change_is_rolled_back():
    h = harness(FakeClient(reply(call("move_event", **MOVE)), reply(say("ok"))),
                approver=always("no"), sandbox=sqlite_sandbox)
    events = run(h, "x", quiet=True)
    assert life_tools.db_rows("SELECT date FROM events WHERE id = 7")[0]["date"] == "2026-10-13"
    assert calls(events) == [("move_event", MOVE, False)]


def test_hold_changes_nothing_and_can_be_approved_later():
    h = harness(FakeClient(reply(call("move_event", **MOVE)), reply(say("waiting for Alex"))),
                approver=always("hold"), sandbox=sqlite_sandbox)
    run(h, "x", quiet=True)
    assert life_tools.db_rows("SELECT date FROM events WHERE id = 7")[0]["date"] == "2026-10-13"
    assert [x.tool for x in h.held] == ["move_event"] and "+ events" in h.held[0].preview
    assert approve(h.held[0], alex.ALL_TOOLS).startswith("Moved #7")
    assert life_tools.db_rows("SELECT date FROM events WHERE id = 7")[0]["date"] == "2026-10-15"


def test_invalid_change_never_asks_the_human():
    asked = []
    h = harness(FakeClient(reply(call("move_event", event_id=999, date="2026-10-15", start="08:00", end="08:30")),
                           reply(say("ok"))), approver=lambda ev: asked.append(ev) or "yes", sandbox=sqlite_sandbox)
    events = run(h, "x", quiet=True)
    assert not asked and "No event with id 999" in events[3].data["text"]


def test_allowed_write_runs_without_approval():
    h = harness(FakeClient(reply(call("draft_email", to="a@b.c", subject="Hi", body="Hello")), reply(say("ok"))),
                policy=alex.ALEX_POLICY, approver=lambda ev: pytest.fail("should not ask"))
    run(h, "x", quiet=True)
    assert [m["status"] for m in life_tools.outbox()] == ["draft"]


# ---------------------------------------------------------------- steering

def test_steering_message_goes_in_between_steps():
    steer = SteeringQueue()
    client = FakeClient(reply(call("list_tasks")), reply(say("done")))
    h = harness(client, steering=steer)
    events = run(h, "x", quiet=True, on_event=lambda ev: ev.kind == "action" and steer.put("use Thursday"))
    assert "steer" in kinds(events)
    assert client.requests[1]["input"][-1] == {"role": "user", "content": "use Thursday"}


def test_stop_goes_first_and_ends_the_run():
    steer = SteeringQueue()
    client = FakeClient(reply(call("list_tasks")), reply(say("never")))
    h = harness(client, steering=steer)

    def type_two(ev):
        if ev.kind == "action":
            steer.put("also next week")
            steer.put("stop")
    events = run(h, "x", quiet=True, on_event=type_two)
    assert events[-2].kind == "steer" and events[-2].data["text"] == "stop"
    assert events[-1].data["stop"] == "user" and len(client.requests) == 1


def test_message_typed_during_the_answer_keeps_the_run_going():
    steer = SteeringQueue()
    client = FakeClient(reply(say("first answer")), reply(say("second answer")))
    h = harness(client, steering=steer)
    events = run(h, "x", quiet=True, on_event=lambda ev: ev.kind == "model" and ev.data["turn"] == 1
                 and steer.put("and Friday?"))
    assert final(events) == "second answer"


# ---------------------------------------------------------------- the desk

def test_step_starts_never_split_a_call_from_its_result():
    items = [{"role": "user", "content": "task"},
             {"type": "reasoning"}, {"type": "function_call"}, {"type": "function_call"},
             {"type": "function_call_output"}, {"type": "function_call_output"},
             {"type": "reasoning"}, {"type": "function_call"}, {"type": "function_call_output"},
             {"type": "message"}]
    assert step_starts(items) == [1, 6, 9]


def test_summary_tail_keeps_task_and_tail_and_gives_the_task_to_the_summariser():
    seen = []
    big = "x" * 4000
    items = [{"role": "user", "content": "count the gym sessions"}]
    for i in range(4):
        items += [{"type": "reasoning", "id": f"r{i}"},
                  {"type": "function_call", "name": "list_events_raw", "arguments": "{}", "call_id": f"c{i}"},
                  {"type": "function_call_output", "call_id": f"c{i}", "output": big}]
    conv = NS(system="s", input=items)
    info = SummaryTail(window=4000, keep=2, summarise=lambda t: seen.append(t) or "weeks 1-2: 2, 1")(conv)
    assert info and info["after"] < info["before"]
    assert conv.input[0]["content"] == "count the gym sessions"
    assert conv.input[1]["content"].startswith("[summary]") and conv.input[2]["type"] == "reasoning"
    assert len(conv.input) == 2 + 6 and "USER: count the gym sessions" in seen[0]


def test_summary_tail_does_nothing_below_the_threshold():
    conv = NS(system="s", input=[{"role": "user", "content": "short"}])
    assert SummaryTail(window=4000, summarise=lambda t: pytest.fail("no")) (conv) is None


def test_as_text_reads_every_kind_of_item():
    text = as_text([{"role": "user", "content": "hi"}, {"type": "function_call", "name": "f", "arguments": "{}"},
                    {"type": "function_call_output", "output": "42"},
                    {"type": "message", "content": [{"type": "output_text", "text": "done"}]}])
    assert text.splitlines() == ["USER: hi", "TOOL CALL: f({})", "TOOL RESULT: 42", "ASSISTANT: done"]


# ---------------------------------------------------------------- modules

def test_skills_menu_in_system_page_on_demand():
    skills = skills_module(alex.SKILLS_DIR)
    assert "- reply-to-recruiter:" in skills["system"] and "Best, Alex" not in skills["system"]
    h = harness(FakeClient(reply(call("load_skill", name="reply-to-recruiter")), reply(say("ok"))), modules=[skills])
    events = run(h, "x", quiet=True)
    assert "Best, Alex" in events[3].data["text"] and "Skills:" in h.system


def test_memory_survives_into_the_next_session(tmp_path):
    path = tmp_path / "alex.md"
    first = harness(FakeClient(reply(call("remember", fact="Thursday is capstone day")), reply(say("ok"))),
                    modules=[memory_module(path)], policy=alex.ALEX_POLICY)
    run(first, "remember", quiet=True)
    assert "Thursday is capstone day" in harness(FakeClient(), modules=[memory_module(path)]).system


# ---------------------------------------------------------------- doors 2 and 3

def test_remote_triage_runs_in_parallel_and_holds_changes():
    script = {"northwind": [reply(call("move_event", **MOVE)), reply(say("held"))],
              "school": [reply(say("nothing to do"))]}

    def make(name):
        return harness(FakeClient(*script[name]), name=name, approver=always("hold"), sandbox=sqlite_sandbox)
    emails = [e for e in life_tools.inbox() if e["id"] in script]
    out = morning_triage(emails, make, quiet=True)
    assert [x.tool for x in out["northwind"][0].held] == ["move_event"] and not out["school"][0].held
    assert life_tools.db_rows("SELECT date FROM events WHERE id = 7")[0]["date"] == "2026-10-13"


def test_webhook_door():
    server = make_server(lambda name: harness(FakeClient(reply(say("nothing to do"))), name=name))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/email"
        body = json.dumps(life_tools.inbox()[2]).encode()
        out = json.loads(urlopen(Request(url, data=body, headers={"Content-Type": "application/json"})).read())
        assert out == {"answer": "nothing to do", "held": []}
    finally:
        server.shutdown()


def test_record_then_replay_gives_the_same_events(tmp_path):
    h = harness(FakeClient(reply(call("list_tasks")), reply(say("done"))))
    events = list(record(h.run("x"), tmp_path / "run.jsonl"))
    again = replay(tmp_path / "run.jsonl")
    assert [(e.kind, e.data) for e in again] == [(e.kind, json.loads(json.dumps(e.data, default=str)))
                                                  for e in events]
    assert "| 1 | `list_tasks`()" in turn_table(again)


def test_benchmark_checks():
    w = lifedb.week()
    rules = alex.checks()

    def ev(*steps):
        h = harness(FakeClient(*steps, reply(say("ok"))), approver=always("hold"), sandbox=sqlite_sandbox,
                    policy=alex.ALEX_POLICY)
        return run(h, "x", quiet=True)
    good = ev(reply(call("move_event", event_id=7, date=w.day(3), start="08:00", end="08:30")),
              reply(call("draft_email", "c2", to="dana@n.ai", subject="Re", body="Thursday 8:00. Best, Alex")))
    evening = ev(reply(call("move_event", event_id=7, date=w.day(3), start="17:30", end="18:00")),
                 reply(call("draft_email", "c2", to="dana@n.ai", subject="Re", body="17:30")))
    assert rules["northwind"](good) and not rules["northwind"](evening)
    assert rules["school"](ev()) and not rules["school"](good)


def test_each_model_call_is_capped():
    client = FakeClient(reply(say("hi")))
    run(harness(client, limits=Limits(max_output_tokens=123)), "x", quiet=True)
    assert client.requests[0]["max_output_tokens"] == 123
