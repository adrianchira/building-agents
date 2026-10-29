"""May this run? (policy) and what does the human say? (approver)."""

from typing import Callable

from agent_core import DESTRUCTIVE, READ, WRITE


def policy_by_effect(rules: dict | None = None, overrides: dict | None = None) -> Callable[[str, str], str]:
    """allow / ask / deny by the tool's effect, with per-tool overrides. Unknown effect: ask."""
    rules = rules or {READ: "allow", WRITE: "ask", DESTRUCTIVE: "ask"}
    overrides = overrides or {}
    return lambda name, effect: overrides.get(name, rules.get(effect, "ask"))


def always(answer: str):
    """An approver that always gives the same answer: 'yes', 'no', or 'hold' (decide later)."""
    return lambda event: answer


def ask_human(event) -> str:
    print(f"\n🔐 {event.data['tool']} wants to make this change:\n{event.data['preview']}")
    return "yes" if input("Allow? [y/N] ").strip().lower() in ("y", "yes") else "no"
