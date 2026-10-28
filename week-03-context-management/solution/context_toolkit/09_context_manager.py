"""
09_context_manager.py - Putting it together: a layered context manager for
an agent loop, plus a live demo that shows the desk filling up.

Layers, cheapest first (the "escalation ladder"):
  1. Offload huge tool outputs at the door          (04)  - free
  2. Clear old tool results past 50% of the window   (04)  - free, lossless if re-fetchable
  3. Compact older history past 75%                  (03)  - one LLM call, lossy
  4. Notes in memory survive all of the above        (05)

Run:  python 09_context_manager.py
"""
import copy
import os
import shutil

from common import context_size, make_llm, real_llm_enabled

import importlib
tool_results = importlib.import_module("04_tool_results")
compaction = importlib.import_module("03_compaction")
memory_mod = importlib.import_module("05_memory")


class ContextManager:
    def __init__(self, llm, window=40_000, clear_at=0.50, compact_at=0.75, keep_tools=3,
                 mem_dir="./memories_agent"):
        self.window, self.clear_at, self.keep_tools = window, clear_at, keep_tools
        self.compactor = compaction.Compactor(llm, window, trigger=compact_at, keep_last=4)
        self.memory = memory_mod.FileMemory(mem_dir)
        self.log = []

    def ingest_tool_output(self, name: str, output: str) -> str:
        return tool_results.offload_if_large(name, output, max_tokens=1_500)

    def before_model_call(self, messages):
        size = context_size(messages)
        if size > self.clear_at * self.window:
            freed = tool_results.clear_old_tool_results(messages, keep=self.keep_tools)
            if freed:
                self.log.append(f"clear  : freed ~{freed:,} tokens")
        if self.compactor.needs_compaction(messages):
            before = context_size(messages)
            messages = self.compactor.compact(messages)
            self.log.append(f"compact: {before:,} -> {context_size(messages):,} tokens")
        return messages


def simulate(strategy: str, steps=40, window=40_000):
    """A fake agent that reads one ~3k-token document per step and takes a note."""
    cm = ContextManager(make_llm(real=real_llm_enabled()), window=window,
                        mem_dir=f"./memories_agent/{strategy}")
    msgs = [{"role": "user", "content": "TASK: review 40 contracts, list any with a penalty clause above 10%."}]
    sizes, overflow_at = [], None
    for i in range(steps):
        doc = f"Contract {i}. Penalty clause {i % 17}%. " + ("Standard legal boilerplate. " * 420)
        msgs.append({"role": "assistant", "content": [
            {"type": "text", "text": f"Reading contract {i}."},
            {"type": "tool_use", "id": f"c{i}", "name": "read_contract", "input": {"id": i}}]})
        body = cm.ingest_tool_output("read_contract", doc) if strategy == "offload" else doc
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": body}]})
        if i % 17 > 10:  # the agent writes findings to memory, outside the window
            cm.memory.handle({"command": "append", "path": "/memories/findings.md",
                              "text": f"- contract {i}: penalty {i % 17}%"})
        if strategy in ("layered", "offload"):
            msgs = cm.before_model_call(msgs)
        size = context_size(msgs)
        sizes.append(size)
        if size > window and overflow_at is None:
            overflow_at = i
    return sizes, overflow_at, cm


def bar(v, window, width=46):
    n = min(width, int(width * v / window))
    return "#" * n + ("!" if v > window else "")


if __name__ == "__main__":
    for d in ("./memories_agent", "./.tool_outputs"):
        shutil.rmtree(d, ignore_errors=True)
    W = 40_000
    results = {s: simulate(s, window=W) for s in ("none", "layered", "offload")}

    print(f"Context size per step (window = {W:,} tokens; '!' = desk overflowed)\n")
    print(f"{'step':>4}  {'no management':<48}{'clear (+compact)':<48}offload at the door")
    for step in range(0, 40, 3):
        cells = [f"{bar(results[s][0][step], W):<48}" for s in ("none", "layered", "offload")]
        print(f"{step:>4}  " + "".join(cells))

    for s, (sizes, overflow, cm) in results.items():
        print(f"\n{s:<8} peak {max(sizes):>7,} tokens | overflow at step {overflow if overflow is not None else '-'}")
        n_clear = sum(l.startswith("clear") for l in cm.log)
        n_comp = sum(l.startswith("compact") for l in cm.log)
        if cm.log:
            print(f"          {n_clear} clearing events, {n_comp} compactions; e.g. {cm.log[0]}")
    print("\nMemory survived everything:")
    print(results["layered"][2].memory.handle({"command": "view", "path": "/memories/findings.md"}))
