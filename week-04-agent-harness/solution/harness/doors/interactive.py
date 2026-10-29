"""Door 1: a person in a chat. The steering queue + priority gate let them talk while the agent works."""

import itertools
import queue
from dataclasses import dataclass, field

from ..observe import run

URGENT = ("stop", "cancel", "wait")


@dataclass(order=True)
class Message:
    priority: int                                 # 0 = urgent, 1 = normal: lower goes first
    n: int                                        # arrival order, among the same priority
    text: str = field(compare=False)

    @property
    def urgent(self) -> bool:
        return self.priority == 0

    @property
    def is_stop(self) -> bool:
        return self.urgent and self.text.strip().lower().rstrip("!. ") in ("stop", "cancel")


class SteeringQueue:
    """Safe to call put() from another thread (a chat UI); the harness calls let_in() between steps."""

    def __init__(self):
        self.q, self.count = queue.PriorityQueue(), itertools.count()

    def put(self, text: str) -> None:
        urgent = text.strip().lower().rstrip("!. ").split(" ")[0] in URGENT
        self.q.put(Message(0 if urgent else 1, next(self.count), text))

    def waiting(self) -> bool:
        return not self.q.empty()

    def let_in(self) -> list[Message]:
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out


def chat(make_harness) -> None:
    """A terminal chat: one harness for the session, one run per message. Type 'quit' to leave."""
    h = make_harness()
    while (text := input("\nYou: ").strip()).lower() not in ("quit", "exit", ""):
        run(h, text)
