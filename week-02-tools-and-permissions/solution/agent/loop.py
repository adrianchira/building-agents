"""The agentic loop: call the model, run the tools it asks for, repeat until it stops.

New in week 2: read-only batches run in parallel, and a FatalToolError ends the run.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from . import config
from .providers import AnthropicConversation, Conversation, ToolResult
from .tools import READ, TOOLS, FatalToolError, execute_tool, tool_schemas
from .tracing import trace_step, trace_tool_result


@dataclass
class AgentResult:
    answer: str
    stop: str  # end_turn | max_turns | max_tokens | refusal | fatal | ...
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0


def run_tools(calls: list, tools: dict[str, dict[str, Any]], *, parallel: bool = True) -> list[ToolResult]:
    """Results keep the order of the calls. Only all-read batches run concurrently:
    writes may depend on each other, and approval prompts must not interleave."""
    all_reads = all(tools.get(c.name, {}).get("effect") == READ for c in calls)
    if parallel and all_reads and len(calls) > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda c: execute_tool(c, tools), calls))
    return [execute_tool(c, tools) for c in calls]


def run_agent(
    task: str,
    *,
    conversation: Conversation | None = None,
    client: Any = None,
    tools: dict[str, dict[str, Any]] = TOOLS,
    max_turns: int = config.MAX_TURNS,
    parallel: bool = True,
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
            try:
                results = run_tools(step.tool_calls, tools, parallel=parallel)
            except FatalToolError as exc:
                return done("fatal", f"[run stopped: {exc}]")
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
