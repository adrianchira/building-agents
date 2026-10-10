"""Print what happens on each turn so you can *read* the agent's behaviour."""

from typing import Any


def _short(text: Any, limit: int = 300) -> str:
    text = str(text).replace("\n", " | ")
    return text if len(text) <= limit else text[:limit] + "..."


def trace_step(turn: int, step: Any) -> None:
    print(f"\n── turn {turn} · stop={step.stop} · "
          f"in={step.input_tokens} out={step.output_tokens} tokens")
    if step.text:
        print(f"  💬 {_short(step.text)}")
    for call in step.tool_calls:
        print(f"  🔧 {call.name}({call.input})")


def trace_tool_result(result: Any) -> None:
    mark = "❌" if result.is_error else "✅"
    print(f"  {mark} {_short(result.content, 200)}")
