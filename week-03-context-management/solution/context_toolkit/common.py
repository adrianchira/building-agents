"""
common.py - shared building blocks for the context-management examples.

Everything here is pure standard-library Python, so every example runs offline.
Messages use a simple, provider-neutral chat shape (08 shows the OpenAI
Responses API item format, which maps one-to-one):

    {"role": "user" | "assistant", "content": str | list[block]}

where a block is {"type": "text"|"tool_use"|"tool_result", ...}.

To plug in a real model, set OPENAI_API_KEY and call `make_llm(real=True)`.
"""
from __future__ import annotations

import json
import os
import re
from typing import Callable

Message = dict
LLM = Callable[[str], str]  # prompt in -> text out


# --------------------------------------------------------------------------
# 0. Settings from a .env file (no python-dotenv needed)
# --------------------------------------------------------------------------
def load_env(start: str | None = None) -> str | None:
    """Read the nearest .env walking up from `start` (default: cwd).

    KEY=VALUE lines; '#' comments and blank lines ignored; values already set
    in the real environment win. Returns the path used, or None.
    """
    from pathlib import Path

    here = Path(start or os.getcwd()).resolve()
    for folder in [here, *here.parents]:
        f = folder / ".env"
        if f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v:
                    os.environ.setdefault(k.strip(), v)
            return str(f)
    return None


def real_llm_enabled() -> bool:
    """REAL_LLM=1 in the env, and a key to go with it."""
    want = os.getenv("REAL_LLM", "0").strip().lower() in ("1", "true", "yes")
    if want and not os.getenv("OPENAI_API_KEY"):
        print("REAL_LLM=1 but OPENAI_API_KEY is empty - using the offline summariser.")
        return False
    return want


load_env()                                   # cwd and its parents
if "__file__" in globals():                 # (not defined inside a notebook)
    load_env(os.path.dirname(os.path.abspath(__file__)))  # next to this file and above


# --------------------------------------------------------------------------
# 1. Measuring the desk: token counting
# --------------------------------------------------------------------------
def count_tokens(obj) -> int:
    """Rough token estimate (~4 characters per token for English text).

    Good enough to drive thresholds. For exact numbers use the model's
    tokenizer (e.g. `tiktoken` for OpenAI models), or read `usage.input_tokens`
    from the last API response.
    """
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return max(1, len(text) // 4)


def context_size(messages: list[Message], system: str = "") -> int:
    return count_tokens(system) + sum(count_tokens(m) for m in messages)


# --------------------------------------------------------------------------
# 2. A model to call. Offline by default, a real OpenAI model if you ask.
# --------------------------------------------------------------------------
KEY_PATTERNS = re.compile(
    r"(decid|agreed|must|never|always|deadline|budget|todo|open question|"
    r"prefer|error|fixed|found|result|\d)",
    re.IGNORECASE,
)


def fake_llm(prompt: str) -> str:
    """Deterministic 'summarizer' so demos run without an API key.

    It keeps sentences that look important (decisions, numbers, constraints)
    and drops chit-chat. A real LLM does this far better, but the mechanics
    of the surrounding code are identical.
    """
    body = prompt.split("<transcript>")[-1].split("</transcript>")[0]
    sentences = re.split(r"(?<=[.!?])\s+|\n", body)
    keep = [s.strip() for s in sentences if s.strip() and KEY_PATTERNS.search(s)]
    seen, out = set(), []
    for s in keep:  # de-duplicate while preserving order
        if s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(f"- {s[:160]}" for s in out[:15]) or "- (nothing important)"


def make_llm(real: bool = False, model: str | None = None) -> LLM:
    """Return a prompt -> text function.

    real=False: the offline fake summariser above.
    real=True : an OpenAI model via the Responses API. Needs OPENAI_API_KEY.
                Summarising is grunt work, so the default is the cheap model;
                override with OPENAI_SUMMARY_MODEL.
    """
    if not real:
        return fake_llm
    from openai import OpenAI  # pip install openai

    client = OpenAI()
    model = model or os.getenv("OPENAI_SUMMARY_MODEL", "gpt-6-luna")

    def call(prompt: str) -> str:
        resp = client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=1500,
        )
        return resp.output_text

    return call


# --------------------------------------------------------------------------
# 3. Helpers for printing
# --------------------------------------------------------------------------
def render(messages: list[Message], width: int = 90) -> str:
    """One line per message - handy for showing 'what is on the desk'."""
    lines = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            lines.append(f"[{m['role']}] {c[:width]}")
            continue
        for b in c:
            t = b.get("type")
            if t == "text":
                lines.append(f"[{m['role']}] {b['text'][:width]}")
            elif t == "tool_use":
                lines.append(f"[{m['role']} -> tool] {b['name']}({json.dumps(b['input'])[:60]})")
            elif t == "tool_result":
                body = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                lines.append(f"[tool_result] ({count_tokens(body)} tok) {body[:width - 20]}")
    return "\n".join(lines)


def to_transcript(messages: list[Message], max_tool_chars: int = 300) -> str:
    """Flatten messages to plain text for a summarizer prompt."""
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append(f"{m['role'].upper()}: {c}")
            continue
        for b in c:
            t = b.get("type")
            if t == "text":
                out.append(f"{m['role'].upper()}: {b['text']}")
            elif t == "tool_use":
                out.append(f"TOOL CALL: {b['name']}({json.dumps(b['input'])})")
            elif t == "tool_result":
                body = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                out.append(f"TOOL RESULT: {body[:max_tool_chars]}")
    return "\n".join(out)
