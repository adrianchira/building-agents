"""The agentic loop: call the model, run the tools it asks for, repeat until it stops.

The loop talks to a `Conversation` (see providers.py), so it works the same with
Claude, OpenAI or a local Ollama model.
"""

from dataclasses import dataclass
from typing import Any

from . import config
from .providers import AnthropicConversation, Conversation
from .tools import TOOLS, execute_tool, tool_schemas
from .tracing import trace_step, trace_tool_result


@dataclass
class AgentResult:
    answer: str
    stop: str  # why the loop ended: end_turn | max_turns | max_tokens | refusal | ...
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0


def run_agent(
    task: str,
    *,
    conversation: Conversation | None = None,
    client: Any = None,
    tools: dict[str, dict[str, Any]] = TOOLS,
    max_turns: int = config.MAX_TURNS,
    verbose: bool = True,
) -> AgentResult:
    conv = conversation or AnthropicConversation(task, tools=tool_schemas(tools), client=client)
    tokens_in = tokens_out = 0

    for turn in range(1, max_turns + 1):
        step = conv.ask()
        tokens_in += step.input_tokens
        tokens_out += step.output_tokens
        if verbose:
            trace_step(turn, step)

        def done(stop: str, answer: str) -> AgentResult:
            return AgentResult(answer, stop, turn, tokens_in, tokens_out)

        if step.stop == "tool_use":
            results = [execute_tool(call, tools) for call in step.tool_calls]
            if verbose:
                for r in results:
                    trace_tool_result(r)
            conv.add_tool_results(results)
            continue

        if step.stop == "end_turn":
            return done("end_turn", step.text)
        if step.stop == "max_tokens":
            # Any tool call in a cut-off reply may have truncated arguments: don't run it.
            return done("max_tokens", step.text + "\n[cut off: max_tokens]")
        if step.stop == "refusal":
            return done("refusal", "[the model declined this request]")
        return done(step.stop, step.text)

    return AgentResult(f"[stopped after {max_turns} turns without a final answer]",
                       "max_turns", max_turns, tokens_in, tokens_out)
