"""Adapters and router, tested with fake SDK clients (no API keys, no network)."""

import json
from types import SimpleNamespace as NS

import pytest

from agent import config, run_agent
from agent.providers import ResponsesConversation, ToolResult
from agent.router import choose_model, classify, run_routed
from agent.tools import tool_schemas


# ---------- fake OpenAI Responses client ----------

def _call(call_id, name, **args):
    return NS(type="function_call", call_id=call_id, name=name, arguments=json.dumps(args))


def _msg(text):
    return NS(type="message", content=[NS(type="output_text", text=text)])


def _response(*items, status="completed", text=""):
    return NS(output=list(items), status=status, output_text=text,
              usage=NS(input_tokens=7, output_tokens=3))


class FakeOpenAI:
    def __init__(self, *responses):
        self.responses_ = list(responses)
        self.requests = []
        self.responses = NS(create=self._create)

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "input": list(kwargs["input"])})
        return self.responses_.pop(0)


def test_responses_adapter_translates_tools_and_results():
    fake = FakeOpenAI(
        _response(_call("c1", "calculator", expression="6*7")),
        _response(_msg("42"), text="42"),
    )
    conv = ResponsesConversation("6*7?", model="m", tools=tool_schemas(), client=fake)
    result = run_agent("6*7?", conversation=conv, verbose=False)

    assert (result.answer, result.stop, result.turns) == ("42", "end_turn", 2)
    first = fake.requests[0]
    assert first["tools"][0]["type"] == "function" and "parameters" in first["tools"][0]
    assert fake.requests[1]["input"][-1] == {
        "type": "function_call_output", "call_id": "c1", "output": "42"}


def test_responses_adapter_marks_errors_in_text():
    conv = ResponsesConversation("x", model="m", client=FakeOpenAI())
    conv.add_tool_results([ToolResult("c9", "FileNotFoundError: nope", is_error=True)])
    assert conv.input[-1]["output"].startswith("ERROR:")


def test_responses_incomplete_is_max_tokens_and_tools_not_run():
    fake = FakeOpenAI(_response(_call("c1", "read_file", path="calendar.csv"), status="incomplete"))
    conv = ResponsesConversation("x", model="m", client=fake)
    result = run_agent("x", conversation=conv, verbose=False)
    assert result.stop == "max_tokens" and len(fake.requests) == 1


# ---------- router ----------

@pytest.fixture(autouse=True)
def claude_classifier(monkeypatch):
    """These router tests script an Anthropic-shaped classifier."""
    monkeypatch.setattr(config, "CLASSIFIER", ("anthropic", "claude-haiku-4-5"))

class FakeClassifier:
    """Fake Anthropic client whose structured-output reply is `payload`."""

    def __init__(self, payload):
        def create(**kwargs):
            if isinstance(payload, Exception):
                raise payload
            return NS(content=[NS(type="text", text=payload)])
        self.messages = NS(create=create)


def test_classify_reads_structured_output():
    tier, reason = classify("x", client=FakeClassifier('{"tier": "simple", "reason": "one file"}'))
    assert (tier, reason) == ("simple", "one file")


@pytest.mark.parametrize("payload", ['{"tier": "trivial", "reason": ""}', "not json",
                                     RuntimeError("network down")])
def test_classify_falls_back_to_default(payload):
    tier, _ = classify("x", client=FakeClassifier(payload))
    assert tier == config.DEFAULT_TIER


def test_choose_model_takes_first_available_in_tier():
    assert choose_model("simple", lambda p, m: p != "ollama") == ("openai", "gpt-6-luna")


def test_choose_model_escalates_when_tier_unavailable():
    only_opus = lambda p, m: m == "claude-opus-5-5"
    assert choose_model("moderate", only_opus) == ("anthropic", "claude-opus-5-5")


def test_choose_model_downgrades_as_last_resort():
    only_haiku = lambda p, m: m == "claude-haiku-4-5"
    assert choose_model("hard", only_haiku) == ("anthropic", "claude-haiku-4-5")


def test_run_routed_end_to_end(monkeypatch):
    monkeypatch.setattr("agent.router.is_available", lambda p, m: p == "openai")
    openai_fake = FakeOpenAI(_response(_msg("hi"), text="hi"))
    routing, result = run_routed(
        "list files",
        clients={"anthropic": FakeClassifier('{"tier": "simple", "reason": "trivial"}'),
                 "openai": openai_fake},
        verbose=False,
    )
    assert (routing.tier, routing.provider, routing.model) == ("simple", "openai", "gpt-6-luna")
    assert result.answer == "hi"


def test_default_provider_is_openai_with_non_strict_tools():
    fake = FakeOpenAI(_response(_call("c1", "calculator", expression="1+1")), _response(_msg("2"), text="2"))
    result = run_agent("1+1?", client=fake, verbose=False)   # no provider given: config.PROVIDER
    assert result.answer == "2"
    first = fake.requests[0]
    assert first["model"] == config.MODEL and first["instructions"] == config.SYSTEM_PROMPT
    assert all(t["strict"] is False for t in first["tools"])
