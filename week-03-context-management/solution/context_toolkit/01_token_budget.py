"""
01_token_budget.py - "How big is the desk, and what is already on it?"

Before managing context you need to MEASURE it. This example splits the
context window into zones (system prompt, tools, memory, history, headroom
for the answer) and shows which zone is eating the desk.

Run:  python 01_token_budget.py
"""
from dataclasses import dataclass, field

from common import count_tokens


@dataclass
class ContextBudget:
    window: int = 200_000          # model's context window (the desk size)
    reserve_output: int = 8_000    # always leave room for the answer
    zones: dict = field(default_factory=dict)

    def add(self, zone: str, content) -> None:
        self.zones[zone] = self.zones.get(zone, 0) + count_tokens(content)

    @property
    def used(self) -> int:
        return sum(self.zones.values())

    @property
    def free(self) -> int:
        return self.window - self.reserve_output - self.used

    def pressure(self) -> float:
        """0.0 = empty desk, 1.0 = desk full (excluding answer reserve)."""
        return self.used / (self.window - self.reserve_output)

    def action(self) -> str:
        p = self.pressure()
        if p < 0.50:
            return "OK - nothing to do"
        if p < 0.70:
            return "CLEAR - drop old tool results (cheap, no LLM call)"
        if p < 0.85:
            return "COMPACT - summarise older history"
        return "RESET - write notes to memory, start a fresh context"

    def report(self) -> str:
        rows = [f"{'zone':<14}{'tokens':>10}{'share':>8}"]
        for z, t in sorted(self.zones.items(), key=lambda kv: -kv[1]):
            rows.append(f"{z:<14}{t:>10,}{t / max(self.used, 1):>8.0%}")
        rows.append(f"{'USED':<14}{self.used:>10,}")
        rows.append(f"{'FREE':<14}{self.free:>10,}   (after {self.reserve_output:,} reserved for output)")
        rows.append(f"pressure = {self.pressure():.0%}  ->  {self.action()}")
        return "\n".join(rows)


if __name__ == "__main__":
    b = ContextBudget(window=200_000)
    b.add("system", "You are a helpful banking assistant. " * 60)
    b.add("tools", [{"name": f"tool_{i}", "description": "x" * 800} for i in range(25)])
    b.add("memory", "Customer prefers Romanian. Risk profile: moderate. " * 20)
    b.add("history", "user: ... assistant: ... " * 4_000)
    b.add("tool_results", "{'rows': [...]} " * 30_000)   # one big SQL dump
    print(b.report())
    print("\nLesson: the tool results, not the chat, are usually what fills the desk.")
