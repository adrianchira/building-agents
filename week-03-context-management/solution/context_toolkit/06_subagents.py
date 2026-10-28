"""
06_subagents.py - "Send an intern to the archive. They come back with one
page, not the whole archive."

A sub-agent gets a FRESH, EMPTY context, does the messy work there (reading
files, running queries, dead ends), and returns only a short, structured
result. The orchestrator's desk stays clean.

Also shown: running sub-agents in parallel and enforcing a return budget.

Run:  python 06_subagents.py
"""
import json
from concurrent.futures import ThreadPoolExecutor

from common import context_size, count_tokens

RETURN_BUDGET = 300  # tokens a sub-agent may hand back


def read_big_source(name: str) -> str:
    """Stand-in for an expensive tool: 30k tokens of raw data."""
    return "\n".join(f"{name} row {i}: amount={i * 7 % 1000} flag={'LATE' if i % 211 == 0 else 'ok'}"
                     for i in range(4_000))


def run_subagent(task: str, source: str) -> dict:
    """Everything inside this function lives in the sub-agent's own context."""
    sub_context = [{"role": "user", "content": task}]
    raw = read_big_source(source)
    sub_context.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": raw}]})

    # ... the sub-agent 'thinks' (here: plain Python instead of an LLM) ...
    late = [l for l in raw.splitlines() if "LATE" in l]
    result = {
        "source": source,
        "rows_scanned": len(raw.splitlines()),
        "late_rows": len(late),
        "examples": late[:3],
        "confidence": "high",
    }
    # Enforce the contract: short, structured, no raw dumps.
    text = json.dumps(result)
    assert count_tokens(text) <= RETURN_BUDGET, "sub-agent answer too long - summarise harder"
    result["_subagent_context_tokens"] = context_size(sub_context)
    return result


if __name__ == "__main__":
    sources = ["payments_2024", "payments_2025", "standing_orders", "direct_debits"]
    task = "Find late payments in {src}. Return JSON: rows_scanned, late_rows, 3 examples."

    # Option 1: do everything in the main agent -> all raw data lands on one desk.
    inline = [{"role": "user", "content": "Audit late payments across all sources."}]
    for s in sources:
        inline.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": s, "content": read_big_source(s)}]})
    print(f"Inline (one agent)       : orchestrator context ~{context_size(inline):,} tokens")

    # Option 2: fan out to sub-agents in parallel, keep only their summaries.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda s: run_subagent(task.format(src=s), s), sources))

    orchestrator = [{"role": "user", "content": "Audit late payments across all sources."}]
    for r in results:
        sub_tokens = r.pop("_subagent_context_tokens")
        print(f"  sub-agent {r['source']:<16}: used ~{sub_tokens:,} tokens in its OWN context, returned {count_tokens(json.dumps(r))}")
        orchestrator.append({"role": "user", "content": json.dumps(r)})
    print(f"With sub-agents          : orchestrator context ~{context_size(orchestrator):,} tokens")
    print("\nTrade-off: more total tokens spent (each sub-agent pays its own way),")
    print("but the main agent stays sharp, and the work runs in parallel.")
