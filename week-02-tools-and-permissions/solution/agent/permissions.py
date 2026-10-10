"""allow / ask / deny, per kind of tool, with a dry-run preview before anything changes.

We don't touch the loop: we wrap each tool's function. The loop just sees tools that
sometimes fail with "the user declined" - information the model can act on.
"""

from typing import Any, Callable

from . import config, db

Approver = Callable[[str], bool]


def ask_human(preview: str) -> bool:
    return input(f"\n{preview}\nAllow? [y/N] ").strip().lower() in ("y", "yes")


def always(answer: bool) -> Approver:
    """For tests and demos: an approver that always says yes (or no)."""
    return lambda preview: answer


def decision_for(name: str, effect: str, policy: dict[str, str] | None = None,
                 overrides: dict[str, str] | None = None) -> str:
    policy = config.POLICY if policy is None else policy
    overrides = config.POLICY_OVERRIDES if overrides is None else overrides
    return overrides.get(name, policy.get(effect, "ask"))  # unknown effect: be careful


def _guard(name: str, fn: Callable[..., str], decision: str, approver: Approver) -> Callable[..., str]:
    if decision == "allow":
        return fn

    if decision == "deny":
        def denied(**kwargs: Any) -> str:
            raise PermissionError(f"'{name}' is turned off in the user's settings. "
                                  "Tell the user what you wanted to do so they can do it themselves.")
        return denied

    def ask(**kwargs: Any) -> str:
        # Dry-run: do the change inside a transaction, show the diff, then commit or roll back.
        conn = db.rw()
        before = db.snapshot(conn)
        conn.execute("BEGIN")
        committed = False
        try:
            output = fn(**kwargs)  # an invalid call raises here: the user is never bothered
            changes = db.diff(before, db.snapshot(conn))
            args = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
            if approver(f"🔐 {name}({args})\n{changes}"):
                conn.execute("COMMIT")
                committed = True
                return output
        finally:
            if not committed:  # declined, invalid, or the prompt itself failed (Ctrl+C, no stdin)
                conn.execute("ROLLBACK")
        raise PermissionError("The user declined this change. Ask them what they would prefer.")
    return ask


def apply_policy(tools: dict[str, dict[str, Any]], *, approver: Approver = ask_human,
                 policy: dict[str, str] | None = None,
                 overrides: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Return a new registry where every tool obeys the policy. The original is untouched."""
    return {name: {**entry, "fn": _guard(name, entry["fn"],
                                         decision_for(name, entry["effect"], policy, overrides), approver)}
            for name, entry in tools.items()}
