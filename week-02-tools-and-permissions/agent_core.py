"""Last week's loop, packaged as a module (exactly what homework 8.1 asked for),
with three additions we study this week:

  * `tool()`        - one Pydantic model gives both the JSON schema AND the validation
  * `run_tools()`   - read-only tool calls run in parallel, writes run one at a time
  * FatalToolError  - a tool can stop the whole run when continuing makes no sense

Read it: `import inspect; print(inspect.getsource(agent_core.run_tools))`
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic
from pydantic import BaseModel, ValidationError

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000
EFFORT_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}  # Haiku 4.5 rejects effort / fallbacks

READ, WRITE, DESTRUCTIVE = "read", "write", "destructive"


class FatalToolError(Exception):
    """Raise from a tool when the run must stop (e.g. the database is gone)."""


# ---------------------------------------------------------------- tools

def tool(fn: Callable, *, description: str, input_model: type[BaseModel], effect: str = READ) -> dict:
    """Build a registry entry. The Pydantic model is the single source of truth:
    the model sees its JSON schema, and our code validates every call against it."""
    def run(**kwargs: Any) -> str:
        args = input_model.model_validate(kwargs)       # raises ValidationError on bad input
        return str(fn(**dict(args)))
    return {
        "fn": run,
        "effect": effect,
        "schema": {"name": fn.__name__, "description": description,
                   "input_schema": input_model.model_json_schema()},
    }


def tool_schemas(tools: dict) -> list[dict]:
    return [t["schema"] for t in tools.values()]


def _format_validation_error(exc: ValidationError) -> str:
    problems = [f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors()]
    return "Invalid arguments. " + "; ".join(problems)


def execute_tool(call: Any, tools: dict) -> dict:
    """One tool_use block -> one tool_result block. Errors go back to the model,
    except FatalToolError, which propagates and ends the run."""
    result = {"type": "tool_result", "tool_use_id": call.id}
    entry = tools.get(call.name)
    if entry is None:
        return {**result, "content": f"Unknown tool '{call.name}'. Available: {', '.join(tools)}",
                "is_error": True}
    try:
        return {**result, "content": entry["fn"](**call.input)}
    except FatalToolError:
        raise
    except ValidationError as exc:
        return {**result, "content": _format_validation_error(exc), "is_error": True}
    except Exception as exc:
        return {**result, "content": f"{type(exc).__name__}: {exc}", "is_error": True}


def run_tools(calls: list, tools: dict, *, parallel: bool = True) -> list[dict]:
    """Run all tool calls from one model reply. Results keep the order of the calls.

    Only an all-read batch runs in parallel: writes may depend on each other and
    approval prompts must not interleave on the user's screen."""
    all_reads = all(tools.get(c.name, {}).get("effect") == READ for c in calls)
    if parallel and all_reads and len(calls) > 1:
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda c: execute_tool(c, tools), calls))
    return [execute_tool(c, tools) for c in calls]


# ---------------------------------------------------------------- loop

@dataclass
class Result:
    answer: str
    stop: str
    turns: int
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[str] = field(default_factory=list)
    seconds: float = 0.0
    messages: list = field(default_factory=list, repr=False)


def _short(x: Any, n: int = 200) -> str:
    s = str(x).replace("\n", " | ")
    return s if len(s) <= n else s[:n] + "..."


def run_agent(task: str, tools: dict, *, system: str, model: str = MODEL, effort: str = "medium",
              max_turns: int = 10, parallel: bool = True, verbose: bool = True,
              client: Any = None) -> Result:
    client = client or anthropic.Anthropic()
    extra = ({"output_config": {"effort": effort}, "betas": ["server-side-fallback-2026-07-01"],
              "fallbacks": "default"} if model in EFFORT_MODELS else {})
    messages: list[dict] = [{"role": "user", "content": task}]
    res = Result("", "", 0, messages=messages)
    t0 = time.perf_counter()

    for turn in range(1, max_turns + 1):
        res.turns = turn
        r = client.beta.messages.create(model=model, max_tokens=MAX_TOKENS, system=system,
                                        tools=tool_schemas(tools), messages=messages, **extra)
        res.input_tokens += r.usage.input_tokens
        res.output_tokens += r.usage.output_tokens
        messages.append({"role": "assistant", "content": r.content})
        calls = [b for b in r.content if b.type == "tool_use"]
        if verbose:
            print(f"\n── turn {turn} · stop={r.stop_reason} · in={r.usage.input_tokens} out={r.usage.output_tokens}")
            for b in r.content:
                if b.type == "text" and b.text.strip():
                    print("  💬", _short(b.text, 300))
            for c in calls:
                print(f"  🔧 {c.name}({json.dumps(c.input, ensure_ascii=False)})")

        if r.stop_reason == "tool_use":
            res.tool_calls += [c.name for c in calls]
            try:
                results = run_tools(calls, tools, parallel=parallel)
            except FatalToolError as exc:
                res.answer, res.stop = f"[run stopped: {exc}]", "fatal"
                break
            if verbose:
                for x in results:
                    print("  ❌" if x.get("is_error") else "  ✅", _short(x["content"]))
            messages.append({"role": "user", "content": results})
            continue

        text = "\n".join(b.text for b in r.content if b.type == "text").strip()
        res.answer, res.stop = {
            "max_tokens": (text + "\n[cut off: max_tokens]", "max_tokens"),
            "refusal": ("[the model declined this request]", "refusal"),
        }.get(r.stop_reason, (text, str(r.stop_reason)))
        break
    else:
        res.answer, res.stop = f"[stopped after {max_turns} turns]", "max_turns"

    res.seconds = time.perf_counter() - t0
    return res


def first_tool(task: str, tools: dict, *, system: str, model: str = MODEL, client: Any = None) -> str:
    """Which tool does the model reach for FIRST? One call, nothing executed. For evals."""
    client = client or anthropic.Anthropic()
    extra = {"output_config": {"effort": "low"}} if model in EFFORT_MODELS else {}
    r = client.messages.create(model=model, max_tokens=4000, system=system, tools=tool_schemas(tools),
                               messages=[{"role": "user", "content": task}], **extra)
    return next((b.name for b in r.content if b.type == "tool_use"), "(no tool)")
