"""
04_tool_results.py - "Don't pile whole binders on the desk. Leave a sticky
note saying where the binder is."

For AGENTS, tool output (file reads, SQL results, web pages, logs) is usually
80-95% of the context. Two cheap, no-LLM techniques:

  A. OFFLOAD AT THE DOOR - when a tool returns something huge, save it to
     disk and give the model a short preview + a handle it can query later.
  B. CLEAR OLD RESULTS - after the agent has used a result, replace the body
     with a placeholder. The tool_use record stays, so the model knows the
     call happened and can re-run it if needed.

Run:  python 04_tool_results.py
"""
import hashlib
import json
from pathlib import Path

from common import context_size, count_tokens, render

STORE = Path("./.tool_outputs")
PLACEHOLDER = "[result cleared to save context - call the tool again if needed]"


# ---------- A. Offload large outputs at ingestion time ----------------------
def offload_if_large(tool_name: str, output: str, max_tokens: int = 500) -> str:
    """Return output unchanged if small; else save it and return a preview."""
    if count_tokens(output) <= max_tokens:
        return output
    STORE.mkdir(exist_ok=True)
    handle = f"{tool_name}-{hashlib.sha1(output.encode()).hexdigest()[:8]}.txt"
    (STORE / handle).write_text(output)
    lines = output.splitlines()
    head, tail = "\n".join(lines[:5]), "\n".join(lines[-3:])
    return (f"[Large output: {count_tokens(output):,} tokens, {len(lines):,} lines. "
            f"Saved as '{handle}'. Use read_slice(handle, start, end) or "
            f"grep(handle, pattern) to look inside.]\n"
            f"--- first lines ---\n{head}\n...\n--- last lines ---\n{tail}")


def _stored(handle: str) -> Path:
    """course fix: grep/read_slice are tools the MODEL calls - a handle must not point outside STORE
    (without this, grep("../.env", "KEY") reads your API key)."""
    path = (STORE / handle).resolve()
    if not path.is_relative_to(STORE.resolve()):
        raise ValueError("handle escapes the tool output store")
    return path


def grep(handle: str, pattern: str, limit: int = 20) -> str:
    """A tool the agent can call to search an offloaded output."""
    hits = [l for l in _stored(handle).read_text().splitlines() if pattern.lower() in l.lower()]
    return "\n".join(hits[:limit]) + (f"\n... {len(hits) - limit} more" if len(hits) > limit else "")


def read_slice(handle: str, start: int, end: int) -> str:
    """course fix: the offload note promises read_slice, so the agent needs it.
    Lines start..end (1-based) of an offloaded output."""
    lines = _stored(handle).read_text().splitlines()
    return "\n".join(f"{i}: {l}" for i, l in enumerate(lines[start - 1:end], start))


# ---------- B. Clear old tool results ---------------------------------------
def clear_old_tool_results(messages, keep: int = 3, exclude_tools=("memory",)):
    """Replace all but the `keep` most recent tool results with a placeholder."""
    names = {}  # tool_use_id -> tool name
    for m in messages:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]

    positions = [
        (mi, bi)
        for mi, m in enumerate(messages)
        if m["role"] == "user" and isinstance(m["content"], list)
        for bi, b in enumerate(m["content"])
        if b.get("type") == "tool_result" and names.get(b["tool_use_id"]) not in exclude_tools
    ]
    freed = 0
    for mi, bi in positions[:-keep] if keep else positions:
        block = messages[mi]["content"][bi]
        if block["content"] != PLACEHOLDER:
            freed += count_tokens(block["content"])
            block["content"] = PLACEHOLDER
    return freed


# ---------- demo -------------------------------------------------------------
def fake_sql(table: str) -> str:
    rows = [json.dumps({"id": i, "table": table, "balance": i * 13.37, "status": "OK" if i % 97 else "MISMATCH"})
            for i in range(2_000)]
    return "\n".join(rows)


if __name__ == "__main__":
    msgs = [{"role": "user", "content": "Reconcile the 5 account tables and report mismatches."}]
    for i, table in enumerate(["current", "savings", "loans", "cards", "deposits"]):
        raw = fake_sql(table)
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"t{i}", "name": "run_sql", "input": {"table": table}}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": raw}]})

    print(f"Raw agent context          : ~{context_size(msgs):>8,} tokens")

    # B. clearing on the raw history
    import copy
    cleared = copy.deepcopy(msgs)
    freed = clear_old_tool_results(cleared, keep=1)
    print(f"After clearing (keep=1)    : ~{context_size(cleared):>8,} tokens  (freed {freed:,})")

    # A. offloading at the door
    offloaded = copy.deepcopy(msgs)
    for m in offloaded:
        if isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_result":
                    b["content"] = offload_if_large("run_sql", b["content"])
    print(f"With offload at ingestion  : ~{context_size(offloaded):>8,} tokens\n")

    print(render(offloaded[:3], width=110))
    handle = next(p.name for p in STORE.iterdir() if "run_sql" in p.name)
    print(f"\nAgent follows up with grep('{handle}', 'MISMATCH'):")
    print(grep(handle, "MISMATCH", limit=3))
