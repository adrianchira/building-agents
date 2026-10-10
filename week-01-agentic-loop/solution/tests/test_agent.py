"""Tests that run WITHOUT an API key: real tools, scripted fake model."""

from types import SimpleNamespace as NS

import pytest

from agent import run_agent
from agent.tools import calculator, execute_tool, list_dir, read_file


# ---------- tools ----------

def test_calculator_exact():
    assert calculator("120*19.99 + 45*49.5") == "4626.3"


@pytest.mark.parametrize("expr", ["__import__('os')", "open('x')", "a + 1"])
def test_calculator_rejects_code(expr):
    with pytest.raises(ValueError):
        calculator(expr)


def test_list_and_read():
    assert "calendar.csv" in list_dir(".")
    assert "notes/" in list_dir(".")
    assert read_file("calendar.csv").startswith("id,date,start,end")


def test_sandbox_blocks_escape():
    with pytest.raises(PermissionError):
        read_file("../solution/agent/config.py")


def test_execute_tool_turns_errors_into_results():
    block = NS(id="t1", name="read_file", input={"path": "missing.csv"})
    result = execute_tool(block)
    assert result.is_error is True
    assert result.tool_use_id == "t1"
    assert "FileNotFoundError" in result.content


def test_execute_tool_unknown_name():
    result = execute_tool(NS(id="t2", name="rm_rf", input={}))
    assert result.is_error is True


# ---------- loop (fake client) ----------

def _resp(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks),
              usage=NS(input_tokens=10, output_tokens=5))


def _text(t):
    return NS(type="text", text=t)


def _tool(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


class FakeClient:
    """Plays back scripted responses and records every request it got."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_loop_runs_tools_then_stops():
    client = FakeClient(
        _resp("tool_use", _text("Let me compute."), _tool("a", "calculator", expression="2+2")),
        _resp("end_turn", _text("It's 4.")),
    )
    result = run_agent("2+2?", client=client, verbose=False)

    assert (result.answer, result.stop, result.turns) == ("It's 4.", "end_turn", 2)
    # 2nd request carried: user task, assistant tool_use, user tool_result
    sent = client.requests[1]["messages"]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[2]["content"] == [{"type": "tool_result", "tool_use_id": "a", "content": "4"}]


def test_loop_parallel_tool_results_in_one_message():
    client = FakeClient(
        _resp("tool_use", _tool("a", "calculator", expression="1+1"),
              _tool("b", "calculator", expression="2+2")),
        _resp("end_turn", _text("done")),
    )
    run_agent("x", client=client, verbose=False)
    results = client.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_loop_respects_max_turns():
    looping = [_resp("tool_use", _tool(f"t{i}", "list_dir", path=".")) for i in range(5)]
    result = run_agent("x", client=FakeClient(*looping), max_turns=3, verbose=False)
    assert result.stop == "max_turns"
    assert result.turns == 3


def test_loop_does_not_run_tools_when_cut_off():
    client = FakeClient(_resp("max_tokens", _tool("a", "read_file", path="calendar.csv")))
    result = run_agent("x", client=client, verbose=False)
    assert result.stop == "max_tokens"
    assert len(client.requests) == 1
