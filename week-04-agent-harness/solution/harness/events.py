"""What the headless engine sends out: events. And the brakes: limits."""

import time
from dataclasses import dataclass, field

KINDS = ("start", "model", "think", "action", "approval", "observation", "steer", "compact", "limit", "done")


@dataclass
class Event:
    kind: str                       # one of KINDS
    data: dict = field(default_factory=dict)
    agent: str = "alex"             # which harness sent it: many can run at the same time
    t: float = field(default_factory=time.time)


@dataclass
class Limits:
    """So a confused model can't loop forever: turns, money and time, and the length of one reply."""
    max_turns: int = 12
    max_cost: float = 0.05          # dollars
    max_seconds: float = 240
    max_output_tokens: int = 4_000  # per model call: a runaway reply is cut off instead of running for minutes

    def broken(self, turn: int, cost: float, seconds: float) -> str | None:
        if turn >= self.max_turns:
            return f"{self.max_turns} turns"
        if cost > self.max_cost:
            return f"cost ${cost:.4f} > ${self.max_cost}"
        if seconds > self.max_seconds:
            return f"{seconds:.0f} s > {self.max_seconds} s"
        return None


PRICE = {"input": 0.10, "cached": 0.01, "output": 0.50}      # gpt-6-luna, $ per 1M tokens


def step_cost(step) -> float:
    uncached = step.input_tokens - step.cached_tokens
    return (uncached * PRICE["input"] + step.cached_tokens * PRICE["cached"]
            + step.output_tokens * PRICE["output"]) / 1e6
