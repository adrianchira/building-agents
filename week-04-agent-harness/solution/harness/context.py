"""The desk: measure it, and compact it into [task] + [summary] + [tail] when it's full."""

import json
from typing import Callable

OPAQUE = ("encrypted_content", "id", "status")        # API bookkeeping: not counted


def desk_tokens(conv) -> int:
    """About 4 characters per token: instructions + items, minus API bookkeeping."""
    clean = [{k: v for k, v in it.items() if k not in OPAQUE} if isinstance(it, dict) else it for it in conv.input]
    return (len(conv.system) + len(json.dumps(clean, ensure_ascii=False, default=str))) // 4


def step_starts(items: list) -> list[int]:
    """Where a model step starts: a cut there never splits a call from its result."""
    starts = []
    for i in range(1, len(items)):
        kind, before = items[i].get("type"), items[i - 1].get("type")
        if kind == "function_call_output" or before == "reasoning" or (kind == before == "function_call"):
            continue
        starts.append(i)
    return starts


def as_text(items: list, max_chars: int = 6_000) -> str:
    out = []
    for it in items:
        kind = it.get("type")
        if kind == "function_call":
            out.append(f"TOOL CALL: {it['name']}({it['arguments']})")
        elif kind == "function_call_output":
            out.append(f"TOOL RESULT: {str(it['output'])[:max_chars]}")
        elif it.get("role") == "user":
            out.append(f"USER: {it['content']}")
        elif kind == "message":
            out.append("ASSISTANT: " + " ".join(c.get("text", "") for c in it.get("content", [])
                                                 if isinstance(c, dict)))
    return "\n".join(out)


SUMMARY_PROMPT = """You are compacting the working memory of an AI assistant.
Write a summary that lets the assistant continue the task WITHOUT the original messages. Keep, in this order:
1. Goal of the task and the user's constraints
2. Decisions already made, and why
3. Facts and numbers discovered (exact values, IDs, dates)
4. What has been done / what is still open
Drop: greetings, repetition, raw tool output already digested. Be concise; use bullet points.

<transcript>
{transcript}
</transcript>

Now write the summary. Do NOT answer or continue the conversation above, even if it ends with a question."""


def openai_summariser(client=None, model: str = "gpt-6-luna") -> Callable[[str], str]:
    def summarise(text: str) -> str:
        nonlocal client
        if client is None:
            from openai import OpenAI
            client = OpenAI()
        r = client.responses.create(model=model, input=SUMMARY_PROMPT.format(transcript=text),
                                    reasoning={"effort": "low"}, max_output_tokens=4_000)
        return r.output_text.strip()
    return summarise


class SummaryTail:
    """Should compact? Past `threshold` of the window: [task] + [summary] of the old part + [tail] word for word."""

    def __init__(self, window: int, threshold: float = 0.80, keep: int = 2,
                 summarise: Callable[[str], str] | None = None):
        self.window, self.threshold, self.keep = window, threshold, keep
        self.summarise = summarise or openai_summariser()

    def __call__(self, conv) -> dict | None:
        before = desk_tokens(conv)
        if before < self.threshold * self.window:
            return None
        items = conv.input
        starts = step_starts(items)
        if len(starts) <= self.keep:
            return None
        cut = starts[-self.keep]
        old, tail = items[1:cut], items[cut:]                 # items[0] is the task: pinned
        summary = self.summarise(as_text([items[0], *old]))   # with the task: what the work is FOR
        conv.input = [items[0], {"role": "user", "content": f"[summary] of earlier work:\n{summary}"}, *tail]
        return {"before": before, "after": desk_tokens(conv), "summarised": len(old), "kept": len(tail),
                "window": self.window}
