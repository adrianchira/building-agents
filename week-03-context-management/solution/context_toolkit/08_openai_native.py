"""
08_openai_native.py - The same ideas on the OpenAI Responses API.

What OpenAI does for you, server-side:
  * COMPACTION       context_management=[{"type": "compaction", "compact_threshold": N}]
                     When the input crosses N tokens, the server summarises the
                     history into an opaque, encrypted "compaction" item.
  * STANDALONE       client.responses.compact(model=..., input=items)
    COMPACTION       You decide when; you get back the new, shorter window.
  * PROMPT CACHING   Automatic. Keep the stable prefix (instructions, tools)
                     identical and first; prompt_cache_key groups requests.

What you still do yourself (examples 04 and 05 plug in here):
  * clearing old tool results   -> clear_old_function_outputs() below
  * offloading big outputs      -> offload_if_large() from 04
  * memory                      -> FileMemory from 05, exposed as a function tool

Avoid truncation="auto" for real work: it silently drops the OLDEST items when
the window is full - exactly the "papers falling off the desk" problem.

Sources: developers.openai.com/api/docs/guides/compaction and
/guides/prompt-caching (checked October 2026). Model names change often;
override with OPENAI_MODEL.

Run:  pip install openai && OPENAI_API_KEY=... python 08_openai_native.py
"""
import importlib
import json
import os
import sys

offload_if_large = importlib.import_module("04_tool_results").offload_if_large
mem = importlib.import_module("05_memory")

MODEL = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
COMPACT_AT = 150_000        # tokens; server compacts above this
KEEP_TOOL_RESULTS = 4       # newest tool outputs that stay verbatim

INSTRUCTIONS = (            # stable -> cacheable. Never put timestamps here.
    "You are a migration analyst. ALWAYS call memory(view, /memories) first. "
    "Write decisions, progress and key numbers to /memories as you go: "
    "old tool outputs will be cleared and the history may be compacted."
)

TOOLS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a document by path. Large files return a preview "
                       "and a handle; use grep(handle, pattern) to look inside.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "memory",
        "description": mem.MEMORY_TOOL_SCHEMA["description"],
        "parameters": mem.MEMORY_TOOL_SCHEMA["input_schema"],
    },
]

CLEARED = "[output cleared to save context - call the tool again if needed]"


def clear_old_function_outputs(items, keep=KEEP_TOOL_RESULTS, exclude=("memory",)):
    """Example 04's clearing, for Responses API items.

    A tool call is a {"type": "function_call", "call_id", "name", ...} item;
    its result is a {"type": "function_call_output", "call_id", "output"} item.
    Keep the call record, blank all but the newest `keep` outputs.
    """
    names = {i["call_id"]: i["name"] for i in items if i.get("type") == "function_call"}
    outputs = [i for i in items
               if i.get("type") == "function_call_output" and names.get(i["call_id"]) not in exclude]
    for item in outputs[:-keep] if keep else outputs:
        item["output"] = CLEARED


def drop_before_last_compaction(items):
    """After a compaction item, earlier items are no longer needed (input-array chaining)."""
    idx = [n for n, i in enumerate(items) if i.get("type") == "compaction"]
    return items[idx[-1]:] if idx else items


def run_tool(name, args, memory):
    if name == "memory":
        return memory.handle(args)
    if name == "read_file":
        try:
            text = open(args["path"], encoding="utf-8").read()
        except OSError as e:
            return f"Error: {e}"
        return offload_if_large("read_file", text, max_tokens=2_000)
    return f"Error: unknown tool {name}"


def run_agent(client, task, max_turns=20):
    memory = mem.FileMemory("./memories_openai")
    items = [{"type": "message", "role": "user", "content": task}]

    for turn in range(1, max_turns + 1):
        clear_old_function_outputs(items)            # free, before every call
        items = drop_before_last_compaction(items)

        resp = client.responses.create(
            model=MODEL,
            instructions=INSTRUCTIONS,
            tools=TOOLS,
            input=items,
            store=False,                             # we own the history
            include=["reasoning.encrypted_content"], # pass reasoning back statelessly
            context_management=[{"type": "compaction", "compact_threshold": COMPACT_AT}],
            prompt_cache_key="context-talk-demo",
        )

        u = resp.usage
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        print(f"turn {turn:2d}  input {u.input_tokens:>8,} tok  (cached {cached:,})")

        new = [o.model_dump(exclude_none=True) for o in resp.output]
        if any(o.get("type") == "compaction" for o in new):
            print("          server compacted the history")
        items += new

        calls = [o for o in new if o.get("type") == "function_call"]
        if not calls:
            return resp.output_text
        for c in calls:
            out = run_tool(c["name"], json.loads(c["arguments"] or "{}"), memory)
            items.append({"type": "function_call_output", "call_id": c["call_id"], "output": out})
    return "(stopped: max turns reached)"


def compact_now(client, items):
    """Standalone compaction: you choose the moment (e.g. end of a work phase).

    The returned window is canonical: use it as-is, don't prune it.
    """
    compacted = client.responses.compact(model=MODEL, input=items)
    return [o.model_dump(exclude_none=True) for o in compacted.output]


if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY to run the agent. Request shape per turn:\n")
        print(json.dumps({
            "model": MODEL, "store": False,
            "context_management": [{"type": "compaction", "compact_threshold": COMPACT_AT}],
            "prompt_cache_key": "context-talk-demo",
            "tools": [t["name"] for t in TOOLS],
        }, indent=2))
        sys.exit(0)

    from openai import OpenAI
    print(run_agent(OpenAI(), "Read README.md and 03_compaction.py, then summarise "
                              "how compaction is implemented. Keep notes in memory."))
