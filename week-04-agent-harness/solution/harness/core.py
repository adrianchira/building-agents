"""The engine room: loop + context + modules, with no screen of its own."""

import time
from dataclasses import dataclass
from typing import Any, Iterator

from agent_core import execute_tool, tool_schemas
from providers import ToolResult, open_conversation

from .events import Event, Limits, step_cost
from .modules.permissions import ask_human, policy_by_effect
from .modules.sandbox import no_sandbox

PROVIDER, MODEL = "openai", "gpt-6-luna"


@dataclass
class Held:
    """A change that waits for a human (the remote door: nobody is at the keyboard)."""
    agent: str
    tool: str
    args: dict
    preview: str


class Harness:
    """`run()` yields Events; whoever started it (a chat, a CLI, a cron job, an eval) decides what to do with them.

    modules            more tools and/or instructions ({"tools": {...}, "system": "..."})
    policy             (tool name, effect) -> "allow" | "ask" | "deny"
    approver           approval Event -> "yes" | "no" | "hold"
    sandbox            context manager (call, tools) -> Box: shows a change before it happens
    compactor          callable(conv) -> info dict when it compacted the desk, else None
    steering           a SteeringQueue: the user's messages, let in between steps
    """

    def __init__(self, tools: dict, *, system: str, name: str = "alex", model: str = MODEL,
                 provider: str = PROVIDER, effort: str | None = "low", limits: Limits | None = None,
                 modules: list[dict] | tuple = (), policy=None, approver=None, sandbox=None,
                 compactor=None, steering=None, extra: dict | None = None, client: Any = None):
        self.tools, self.system = dict(tools), system
        for m in modules:
            self.tools |= m.get("tools", {})
            if m.get("system"):
                self.system += "\n\n" + m["system"]
        self.name, self.model, self.provider, self.effort = name, model, provider, effort
        self.limits = limits or Limits()
        self.policy = policy or policy_by_effect()
        self.approver = approver or ask_human
        self.sandbox = sandbox or no_sandbox
        self.compactor, self.steering = compactor, steering
        self.extra, self.client = extra, client
        self.held: list[Held] = []
        self.conv = None

    def event(self, kind: str, **data) -> Event:
        return Event(kind, data, self.name)

    def run(self, task: str) -> Iterator[Event]:
        conv = self.conv = open_conversation(self.provider, self.model, task, tools=tool_schemas(self.tools),
                                             system=self.system, effort=self.effort, client=self.client,
                                             extra=self.extra)
        conv.max_tokens = self.limits.max_output_tokens
        cost, t0, turn = 0.0, time.time(), 0
        yield self.event("start", task=task, model=self.model, tools=list(self.tools))

        for turn in range(1, self.limits.max_turns + 1):
            if self.steering:                               # the safe moment: between two steps
                for msg in self.steering.let_in():
                    yield self.event("steer", turn=turn, text=msg.text, urgent=msg.urgent)
                    if msg.is_stop:
                        yield self.event("done", answer="[stopped by the user]", stop="user", turns=turn - 1,
                                         cost=cost, seconds=time.time() - t0)
                        return
                    conv.add_user_message(msg.text)
            if self.compactor and (info := self.compactor(conv)):
                yield self.event("compact", turn=turn, **info)

            step = conv.ask()
            cost += step_cost(step)
            yield self.event("model", turn=turn, input=step.input_tokens, cached=step.cached_tokens,
                             output=step.output_tokens, cost=cost)

            if step.stop != "tool_use":
                if self.steering and self.steering.waiting():
                    continue                                # the user typed while it answered: keep going
                yield self.event("done", answer=step.text, stop=step.stop, turns=turn, cost=cost,
                                 seconds=time.time() - t0)
                return
            if step.text:
                yield self.event("think", turn=turn, text=step.text)

            results = []
            for call in step.tool_calls:
                yield self.event("action", turn=turn, tool=call.name, args=call.input)
                result = yield from self.act(call, turn)
                yield self.event("observation", turn=turn, tool=call.name, text=result.content,
                                 error=result.is_error)
                results.append(result)
            conv.add_tool_results(results)

            if reason := self.limits.broken(turn, cost, time.time() - t0):
                break
        else:
            reason = f"{self.limits.max_turns} turns"
        yield self.event("limit", turn=turn, reason=reason)
        yield self.event("done", answer=f"[stopped: {reason}]", stop="limit", turns=turn, cost=cost,
                         seconds=time.time() - t0)

    def act(self, call, turn: int):
        """One tool call, through the permission rules. Yields an 'approval' event when a human must decide."""
        entry = self.tools.get(call.name)
        rule = self.policy(call.name, entry["effect"]) if entry else "allow"
        if rule == "allow":
            return execute_tool(call, self.tools)
        if rule == "deny":
            return ToolResult(call.id, f"'{call.name}' is turned off for this assistant. "
                                       "Tell the user what you wanted to do, so they can do it themselves.", True)

        with self.sandbox(call, self.tools) as box:
            if box.result is not None and box.result.is_error:
                return box.result                           # an invalid call never bothers the human
            ask = self.event("approval", turn=turn, tool=call.name, args=call.input, preview=box.preview)
            yield ask
            answer = self.approver(ask)
            box.keep = answer == "yes"
        if answer == "yes":
            return box.result or execute_tool(call, self.tools)
        if answer == "hold":
            self.held.append(Held(self.name, call.name, call.input, box.preview))
            return ToolResult(call.id, "Held for approval: Alex reviews held changes in the morning. Treat it as "
                                       "pending, don't retry it, and say in your answer what is waiting for him.")
        return ToolResult(call.id, "The user declined this change. Ask them what they would prefer.", True)
