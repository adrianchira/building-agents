"""The loop with a scripted fake model."""

import time
from types import SimpleNamespace as NS

from agent import db, run_agent, run_tools
from agent.tools import READ, WRITE


def _resp(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks), usage=NS(input_tokens=10, output_tokens=5))


def _text(t):
    return NS(type="text", text=t)


def _tool(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_loop_runs_tools_then_stops():
    client = FakeClient(_resp("tool_use", _tool("a", "list_tasks", due_before="2026-10-16")),
                        _resp("end_turn", _text("13.75 h")))
    result = run_agent("x", client=client, verbose=False)
    assert (result.answer, result.stop, result.turns) == ("13.75 h", "end_turn", 2)
    sent = client.requests[1]["messages"][-1]["content"][0]
    assert sent["tool_use_id"] == "a" and "TOTAL est_hours: 13.75" in sent["content"]


def test_fatal_error_stops_the_run():
    db.path().unlink()
    client = FakeClient(_resp("tool_use", _tool("a", "list_tasks")), _resp("end_turn", _text("never")))
    result = run_agent("x", client=client, verbose=False)
    assert result.stop == "fatal" and "database not found" in result.answer
    assert len(client.requests) == 1


def _slow_tools(effect):
    def slow(**kw):
        time.sleep(0.3)
        return kw["n"]
    return {"slow": {"fn": slow, "effect": effect, "schema": {}}}


def test_parallel_reads_are_faster_and_keep_order():
    calls = [NS(id=str(i), name="slow", input={"n": str(i)}) for i in range(4)]
    t0 = time.perf_counter()
    results = run_tools(calls, _slow_tools(READ), parallel=True)
    assert time.perf_counter() - t0 < 0.8
    assert [r.content for r in results] == ["0", "1", "2", "3"]


def test_writes_run_sequentially():
    calls = [NS(id=str(i), name="slow", input={"n": str(i)}) for i in range(3)]
    t0 = time.perf_counter()
    run_tools(calls, _slow_tools(WRITE), parallel=True)
    assert time.perf_counter() - t0 >= 0.9
