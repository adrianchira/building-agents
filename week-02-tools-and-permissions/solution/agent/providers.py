"""One interface, several model providers.

Every provider speaks its own wire format for tools. The loop shouldn't care, so each
provider gets an *adapter* that keeps the conversation in its native format and talks
to the loop in three neutral types: ToolCall, ToolResult and Step.

                     | OpenAI Responses API (OpenAI, Ollama) | Anthropic Messages API (Claude)
  tool definition    | {type: "function", name, description, | {name, description, input_schema}
                     |  parameters}                          |
  model asks         | output item "function_call":          | content block "tool_use":
                     |   call_id, name, arguments (JSON str) |   id, name, input (dict)
  we answer          | input item "function_call_output":    | user message, "tool_result" blocks:
                     |   call_id, output (no error flag)     |   tool_use_id, content, is_error
  "run my tools"     | any function_call in the output       | stop_reason == "tool_use"
  cut off            | status == "incomplete"                | stop_reason == "max_tokens"
  history            | append response.output                | append response.content

Tools are written once, in a neutral shape: {"name", "description", "input_schema"}.
"""

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
MAX_TOKENS = 16000


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class Step:
    """One model call, translated into the loop's language."""
    stop: str  # tool_use | end_turn | max_tokens | refusal | <other>
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# ---------------------------------------------------------------- OpenAI Responses API

class ResponsesConversation:
    """OpenAI's Responses API. Ollama (>= 0.13.3) serves the same API locally."""

    def __init__(self, task: str, *, model: str, provider: str = "openai", tools: list[dict] | None = None,
                 system: str = "", effort: str | None = None, client: Any = None):
        if client is None:
            from openai import OpenAI
            client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama") if provider == "ollama" else OpenAI()
        self.client, self.model, self.provider, self.system, self.effort = client, model, provider, system, effort
        # strict=False: otherwise the API may silently make every field required (our defaults would break).
        self.tools = [{"type": "function", "name": t["name"], "description": t["description"],
                       "parameters": t["input_schema"], "strict": False} for t in (tools or [])]
        self.input: list[Any] = [{"role": "user", "content": task}]

    def _extra(self) -> dict:
        return {"reasoning": {"effort": self.effort}} if self.effort else {}

    def ask(self) -> Step:
        r = self.client.responses.create(model=self.model, instructions=self.system, input=self.input,
                                         tools=self.tools, max_output_tokens=MAX_TOKENS, **self._extra())
        self.input += r.output                     # everything back, including reasoning items
        calls = [ToolCall(i.call_id, i.name, json.loads(i.arguments or "{}"))
                 for i in r.output if i.type == "function_call"]
        refused = any(c.type == "refusal" for i in r.output if i.type == "message" for c in i.content)
        stop = ("max_tokens" if r.status == "incomplete" else "refusal" if refused
                else "tool_use" if calls else "end_turn")
        usage = r.usage
        return Step(stop, (r.output_text or "").strip(), calls,
                    getattr(usage, "input_tokens", 0) or 0, getattr(usage, "output_tokens", 0) or 0)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for x in results:   # no is_error field in this format: say it in the text
            self.input.append({"type": "function_call_output", "call_id": x.tool_use_id,
                               "output": f"ERROR: {x.content}" if x.is_error else x.content})

    def complete_json(self, schema: dict) -> dict:
        """One call, no tools, reply forced to match `schema` (structured outputs)."""
        r = self.client.responses.create(
            model=self.model, instructions=self.system, input=self.input, max_output_tokens=2000,
            text={"format": {"type": "json_schema", "name": "result", "schema": schema, "strict": True}},
            **self._extra())
        return json.loads(r.output_text)


# ---------------------------------------------------------------- Anthropic Messages API

CLAUDE_EFFORT_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}   # Haiku 4.5 rejects effort / fallbacks


class AnthropicConversation:
    provider = "anthropic"

    def __init__(self, task: str, *, model: str, tools: list[dict] | None = None, system: str = "",
                 effort: str | None = None, client: Any = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.system, self.effort = client, model, system, effort
        self.tools = list(tools or [])
        self.messages: list[dict] = [{"role": "user", "content": task}]

    def _extra(self) -> dict:
        if self.model not in CLAUDE_EFFORT_MODELS:
            return {}
        # fallbacks: if a safety classifier declines, the API retries on a fallback model.
        return {"output_config": {"effort": self.effort or "medium"},
                "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

    def ask(self) -> Step:
        r = self.client.beta.messages.create(model=self.model, max_tokens=MAX_TOKENS, system=self.system,
                                             tools=self.tools, messages=self.messages, **self._extra())
        self.messages.append({"role": "assistant", "content": r.content})   # whole content, append-only
        return Step(str(r.stop_reason),
                    "\n".join(b.text for b in r.content if b.type == "text").strip(),
                    [ToolCall(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"],
                    r.usage.input_tokens, r.usage.output_tokens)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.messages.append({"role": "user", "content": [   # all results in ONE message
            {"type": "tool_result", "tool_use_id": x.tool_use_id, "content": x.content,
             **({"is_error": True} if x.is_error else {})} for x in results]})

    def complete_json(self, schema: dict) -> dict:
        r = self.client.messages.create(model=self.model, max_tokens=2000, system=self.system,
                                        messages=self.messages,
                                        output_config={"format": {"type": "json_schema", "schema": schema}})
        return json.loads(next(b.text for b in r.content if b.type == "text"))


# ---------------------------------------------------------------- factory + availability

def open_conversation(provider: str, model: str, task: str, *, tools: list[dict] | None = None,
                      system: str = "", effort: str | None = None, client: Any = None):
    if provider == "anthropic":
        return AnthropicConversation(task, model=model, tools=tools, system=system, effort=effort, client=client)
    if provider in ("openai", "ollama"):
        return ResponsesConversation(task, model=model, provider=provider, tools=tools, system=system,
                                     effort=effort, client=client)
    raise ValueError(f"Unknown provider '{provider}' (use 'openai', 'anthropic' or 'ollama')")


def ollama_models() -> set[str]:
    try:
        with urllib.request.urlopen(OLLAMA_BASE_URL.removesuffix("/v1") + "/api/tags", timeout=0.5) as resp:
            return {m["name"] for m in json.load(resp).get("models", [])}
    except (OSError, ValueError):
        return set()


def is_available(provider: str, model: str) -> bool:
    """Cheap check so a router never picks a provider we can't reach."""
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                    or (Path.home() / ".config" / "anthropic").exists())   # `ant auth login` profile
    if provider == "ollama":
        return model in ollama_models()
    return False
