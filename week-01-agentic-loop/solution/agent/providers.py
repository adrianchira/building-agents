"""One loop, many providers.

Every provider speaks its own wire format for tools. The loop shouldn't care, so each
provider gets an *adapter* that keeps the conversation in its native format and talks
to the loop in three neutral types: ToolCall, ToolResult and Step.

                     | Anthropic Messages           | OpenAI Responses (OpenAI, Ollama)
  tool definition    | {name, description,          | {type: "function", name, description,
                     |  input_schema}               |  parameters}
  model asks         | content block "tool_use"     | output item "function_call"
                     |   id, name, input (dict)     |   call_id, name, arguments (JSON string!)
  we answer          | user msg, "tool_result"      | input item "function_call_output"
                     |   tool_use_id, is_error      |   call_id, output  (no error flag)
  "run my tools"     | stop_reason == "tool_use"    | any function_call in output
  cut off            | stop_reason == "max_tokens"  | status == "incomplete"
"""

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import config


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


class Conversation(Protocol):
    provider: str
    model: str

    def ask(self) -> Step: ...
    def add_tool_results(self, results: list[ToolResult]) -> None: ...
    def complete_json(self, schema: dict[str, Any]) -> dict[str, Any]: ...


# ---------------------------------------------------------------- Anthropic

# Models that accept output_config.effort and server-side fallbacks. Haiku 4.5 rejects both.
_CLAUDE_EFFORT_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}


class AnthropicConversation:
    provider = "anthropic"

    def __init__(self, task: str, *, model: str = config.MODEL, tools: list[dict] | None = None,
                 system: str = config.SYSTEM_PROMPT, client: Any = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client, self.model, self.system = client, model, system
        self.tools = tools or []
        self.messages: list[dict[str, Any]] = [{"role": "user", "content": task}]

    def _extra(self) -> dict[str, Any]:
        if self.model not in _CLAUDE_EFFORT_MODELS:
            return {}
        return {"output_config": {"effort": config.EFFORT},
                "betas": [config.FALLBACK_BETA], "fallbacks": "default"}

    def ask(self) -> Step:
        response = self.client.beta.messages.create(
            model=self.model, max_tokens=config.MAX_TOKENS, system=self.system,
            tools=self.tools, messages=self.messages, **self._extra(),
        )
        # Whole content, append-only (thinking blocks must come back unchanged).
        self.messages.append({"role": "assistant", "content": response.content})
        return Step(
            stop=str(response.stop_reason),
            text="\n".join(b.text for b in response.content if b.type == "text").strip(),
            tool_calls=[ToolCall(b.id, b.name, b.input)
                        for b in response.content if b.type == "tool_use"],
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        blocks = []
        for r in results:
            block = {"type": "tool_result", "tool_use_id": r.tool_use_id, "content": r.content}
            if r.is_error:
                block["is_error"] = True
            blocks.append(block)
        self.messages.append({"role": "user", "content": blocks})  # all results, one message

    def complete_json(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Single call (no tools) whose reply is forced to match `schema`."""
        response = self.client.messages.create(
            model=self.model, max_tokens=1024, system=self.system, messages=self.messages,
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        return json.loads(next(b.text for b in response.content if b.type == "text"))


# ---------------------------------------------------------------- OpenAI Responses API

class ResponsesConversation:
    """OpenAI's Responses API. Also used for Ollama, which serves the same API locally."""

    def __init__(self, task: str, *, model: str, provider: str = "openai",
                 tools: list[dict] | None = None, system: str = config.SYSTEM_PROMPT,
                 client: Any = None):
        if client is None:
            from openai import OpenAI
            client = (OpenAI(base_url=config.OLLAMA_BASE_URL, api_key="ollama")
                      if provider == "ollama" else OpenAI())
        self.client, self.model, self.provider, self.system = client, model, provider, system
        self.tools = [{"type": "function", "name": t["name"], "description": t["description"],
                       "parameters": t["input_schema"]} for t in (tools or [])]
        self.input: list[Any] = [{"role": "user", "content": task}]

    def ask(self) -> Step:
        response = self.client.responses.create(
            model=self.model, instructions=self.system, input=self.input,
            tools=self.tools, max_output_tokens=config.MAX_TOKENS,
        )
        self.input += response.output  # everything back, incl. reasoning items
        calls = [ToolCall(i.call_id, i.name, json.loads(i.arguments or "{}"))
                 for i in response.output if i.type == "function_call"]
        refused = any(c.type == "refusal" for i in response.output if i.type == "message"
                      for c in i.content)
        if response.status == "incomplete":
            stop = "max_tokens"
        elif refused:
            stop = "refusal"
        elif calls:
            stop = "tool_use"
        else:
            stop = "end_turn"
        usage = response.usage
        return Step(stop=stop, text=(response.output_text or "").strip(), tool_calls=calls,
                    input_tokens=getattr(usage, "input_tokens", 0) or 0,
                    output_tokens=getattr(usage, "output_tokens", 0) or 0)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            # No is_error field in this format: say it in the text instead.
            output = f"ERROR: {r.content}" if r.is_error else r.content
            self.input.append({"type": "function_call_output", "call_id": r.tool_use_id,
                               "output": output})

    def complete_json(self, schema: dict[str, Any]) -> dict[str, Any]:
        response = self.client.responses.create(
            model=self.model, instructions=self.system, input=self.input,
            max_output_tokens=1024,
            text={"format": {"type": "json_schema", "name": "result", "schema": schema,
                             "strict": True}},
        )
        return json.loads(response.output_text)


# ---------------------------------------------------------------- factory + availability

def open_conversation(provider: str, model: str, task: str, *, tools: list[dict] | None = None,
                      system: str = config.SYSTEM_PROMPT, client: Any = None) -> Conversation:
    if provider == "anthropic":
        return AnthropicConversation(task, model=model, tools=tools, system=system, client=client)
    if provider in ("openai", "ollama"):
        return ResponsesConversation(task, model=model, provider=provider, tools=tools,
                                     system=system, client=client)
    raise ValueError(f"Unknown provider '{provider}'")


def _ollama_models() -> set[str]:
    url = config.OLLAMA_BASE_URL.removesuffix("/v1").rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=0.5) as resp:
            return {m["name"] for m in json.load(resp).get("models", [])}
    except (OSError, ValueError):
        return set()


def is_available(provider: str, model: str) -> bool:
    """Cheap check so the router never picks a provider we can't reach."""
    if provider == "anthropic":
        return True  # the SDK also finds `ant auth login` profiles, not only the env var
    if provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    if provider == "ollama":
        return model in _ollama_models()
    return False
