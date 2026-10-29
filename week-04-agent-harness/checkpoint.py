"""Catch-up file: the same code as the notebook's concept cells (setup + every part of the harness).
If a section failed for you, run `from checkpoint import *` in the next section's checkpoint cell.
Generated from the notebook: do not edit by hand."""

import itertools, json, queue, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

from IPython.display import Markdown, display
from pydantic import Field

import lifedb, life_tools
from agent_core import DESTRUCTIVE, READ, WRITE, execute_tool, run_agent, tool, tool_schemas
from life_tools import Args
from providers import ToolCall, ToolResult, load_api_key, open_conversation

PROVIDER, MODEL = "openai", "gpt-6-luna"
load_api_key(PROVIDER)
from openai import OpenAI
client = OpenAI()


def fresh_week() -> None:
    """Alex's week, dated to this week, from scratch (undo everything the agents changed)."""
    lifedb.create_db()
    life_tools.reset()


fresh_week()
WEEK = lifedb.week()
ALL_TOOLS = {**life_tools.TOOLS, **life_tools.WRITE_TOOLS}          # read + write: calendar, tasks, email

SYSTEM = (
    "You are Alex's personal assistant. Alex is 44, a senior backend developer with a full-time job and two kids, "
    f"retraining as an AI engineer and job-hunting. Today is {WEEK.today}; this week runs to {WEEK.label(6)}. "
    "All times are Eastern. Use the tools to check facts; never guess. Keep the final answer short."
)
print("Today is", WEEK.today, "| tools:", ", ".join(ALL_TOOLS))


@dataclass
class Event:
    kind: str                       # start | model | think | action | approval | observation | steer | compact | limit | done
    data: dict = field(default_factory=dict)
    agent: str = "alex"             # which harness sent it: many can run at the same time
    t: float = field(default_factory=time.time)


@dataclass
class Limits:
    """So a confused model can't loop forever (slide 5): turns, money and time, and the length of one reply."""
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
    return (uncached * PRICE["input"] + step.cached_tokens * PRICE["cached"] + step.output_tokens * PRICE["output"]) / 1e6


def policy_by_effect(rules: dict | None = None, overrides: dict | None = None) -> Callable[[str, str], str]:
    """Week 2's allow / ask / deny: by the tool's effect, with per-tool overrides."""
    rules = rules or {READ: "allow", WRITE: "ask", DESTRUCTIVE: "ask"}
    overrides = overrides or {}
    return lambda name, effect: overrides.get(name, rules.get(effect, "ask"))     # unknown effect: be careful


def always(answer: str) -> Callable[[Event], str]:
    """An approver that always gives the same answer: 'yes', 'no', or 'hold' (decide later)."""
    return lambda event: answer


def ask_human(event: Event) -> str:
    print(f"\n🔐 {event.data['tool']} wants to make this change:\n{event.data['preview']}")
    return "yes" if input("Allow? [y/N] ").strip().lower() in ("y", "yes") else "no"


@dataclass
class Box:
    """What a sandbox hands back: a preview for the human, maybe the result already, and keep or not."""
    preview: str
    result: ToolResult | None = None
    keep: bool = False


def fmt_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


@contextmanager
def no_sandbox(call, tools):
    """Nothing to dry-run: the human sees the call itself, and it runs only after a yes."""
    yield Box(preview=f"  {call.name}({fmt_args(call.input)})")


@dataclass
class Held:
    """A change that waits for a human (the remote door: nobody is at the keyboard)."""
    agent: str
    tool: str
    args: dict
    preview: str


class Harness:
    """The engine room: loop + context + modules. It has no screen of its own: `run()` yields Events,
    and whoever started it (a notebook, a CLI, a cron job, an eval) decides what to do with them."""

    def __init__(self, tools: dict, *, system: str, name: str = "alex", model: str = MODEL,
                 provider: str = PROVIDER, effort: str | None = "low", limits: Limits | None = None,
                 modules: list[dict] = (), policy=None, approver=None, sandbox=None,
                 compactor=None, steering=None, extra: dict | None = None, client=None):
        self.tools, self.system = dict(tools), system
        for m in modules:                                   # plug-in parts: more tools and/or instructions
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
        self.held: list[Held] = []                          # changes waiting for a human
        self.conv = None                                    # the desk of the last run, to look at afterwards

    def event(self, kind: str, **data) -> Event:
        return Event(kind, data, self.name)

    def run(self, task: str) -> Iterator[Event]:
        conv = self.conv = open_conversation(self.provider, self.model, task, tools=tool_schemas(self.tools),
                                             system=self.system, effort=self.effort, client=self.client,
                                             extra=self.extra)
        conv.max_tokens = self.limits.max_output_tokens
        cost, t0 = 0.0, time.time()
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

            step = conv.ask()                               # THINK: the model picks the next step
            cost += step_cost(step)
            yield self.event("model", turn=turn, input=step.input_tokens, cached=step.cached_tokens,
                             output=step.output_tokens, cost=cost)

            if step.stop != "tool_use":                     # the model says "done" (or can't go on)
                if self.steering and self.steering.waiting():
                    continue                                # the user typed while it answered: keep going
                yield self.event("done", answer=step.text, stop=step.stop, turns=turn, cost=cost,
                                 seconds=time.time() - t0)
                return
            if step.text:
                yield self.event("think", turn=turn, text=step.text)

            results = []
            for call in step.tool_calls:                    # ACT: the harness runs the tools, not the model
                yield self.event("action", turn=turn, tool=call.name, args=call.input)
                result = yield from self.act(call, turn)
                yield self.event("observation", turn=turn, tool=call.name, text=result.content,
                                 error=result.is_error)     # LOOK: the result goes back as an observation
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
        rule = self.policy(call.name, entry["effect"]) if entry else "allow"   # unknown tool: execute_tool explains
        if rule == "allow":
            return execute_tool(call, self.tools)
        if rule == "deny":
            return ToolResult(call.id, f"'{call.name}' is turned off for this assistant. "
                                       "Tell the user what you wanted to do, so they can do it themselves.", True)

        with self.sandbox(call, self.tools) as box:          # "ask": try it safely, show the change, wait
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


ICON = {"start": "▶", "think": "💭", "action": "🔧", "approval": "🔐", "observation": "👀", "steer": "📨",
        "compact": "🗜", "limit": "⛔", "done": "🏁"}
PRINT = threading.Lock()                         # several harnesses may print at once


def short(x: Any, n: int = 140) -> str:
    s = str(x).replace("\n", " | ")
    return s if len(s) <= n else s[:n] + "…"


def show(ev: Event, *, tag: bool = False) -> None:
    d, who = ev.data, f"[{ev.agent}] " if tag else ""
    line = {
        "start": lambda: f"task: {short(d['task'], 100)}",
        "model": lambda: f"turn {d['turn']} · desk {d['input']:,} tokens · total ${d['cost']:.4f}",
        "think": lambda: short(d["text"]),
        "action": lambda: f"{d['tool']}({short(fmt_args(d['args']), 110)})",
        "approval": lambda: f"paused: a human must approve {d['tool']}\n{d['preview']}",
        "observation": lambda: ("❌ " if d["error"] else "") + short(d["text"]),
        "steer": lambda: ("URGENT: " if d["urgent"] else "") + d["text"],
        "compact": lambda: f"desk {d['before']:,} → {d['after']:,} tokens ({d['summarised']} items summarised, "
                           f"{d['kept']} kept word for word)",
        "limit": lambda: f"limit reached: {d['reason']}",
        "done": lambda: f"{d['turns']} turns · ${d['cost']:.4f} · {d['seconds']:.0f} s · stop={d['stop']}\n"
                        f"   {d['answer']}",
    }[ev.kind]()
    indent = "" if ev.kind in ("start", "model", "done") else "   "
    with PRINT:
        print(f"{who}{indent}{ICON.get(ev.kind, '·')} {line}")


def run(harness: Harness, task: str, *, quiet: bool = False, tag: bool = False, on_event=None) -> list[Event]:
    events = []
    for ev in harness.run(task):
        events.append(ev)
        if not quiet:
            show(ev, tag=tag)
        if on_event:
            on_event(ev)
    return events


def final(events: list[Event]) -> str:
    return next((e.data["answer"] for e in reversed(events) if e.kind == "done"), "")


def turn_table(events: list[Event]) -> None:
    """Slide 6: one row per action, what the model decided and what the tool reported back."""
    rows, paused = [], ""
    for e in events:
        d = e.data
        if e.kind == "action":
            rows.append([str(d["turn"]), f"`{d['tool']}`({short(fmt_args(d['args']), 70)})", ""])
            paused = ""
        elif e.kind == "approval":
            paused = "⏸ paused for a human → "
        elif e.kind == "observation" and rows:
            rows[-1][2] = paused + short(d["text"], 110).replace("|", "/")
        elif e.kind == "steer":
            rows.append([str(d["turn"]), "📨 *the user:* " + short(d["text"], 80), "let in between steps"])
        elif e.kind == "compact":
            rows.append([str(d["turn"]), "🗜 *the harness compacts*", f"{d['before']:,} → {d['after']:,} tokens"])
        elif e.kind == "done":
            rows.append([str(d["turns"]), "answer, then stop", short(d["answer"], 110).replace("|", "/")])
    table = ["| Turn | The model decides (action) | The tool reports back (observation) |", "|---|---|---|"]
    display(Markdown("\n".join(table + ["| " + " | ".join(r) + " |" for r in rows])))


OPAQUE = ("encrypted_content", "id", "status")        # API bookkeeping: not counted (see week 3)


def desk_tokens(conv) -> int:
    """About 4 characters per token: everything on the desk (instructions + items), minus API bookkeeping."""
    clean = [{k: v for k, v in it.items() if k not in OPAQUE} if isinstance(it, dict) else it for it in conv.input]
    return (len(conv.system) + len(json.dumps(clean, ensure_ascii=False, default=str))) // 4


def step_starts(items: list) -> list[int]:
    """Where a model step starts: a cut there never splits a call from its result."""
    starts = []
    for i in range(1, len(items)):
        kind, before = items[i].get("type"), items[i - 1].get("type")
        if kind == "function_call_output" or before == "reasoning" or (kind == before == "function_call"):
            continue
        starts.append(i)
    return starts


def as_text(items: list, max_chars: int = 6_000) -> str:
    out = []
    for it in items:
        kind = it.get("type")
        if kind == "function_call":
            out.append(f"TOOL CALL: {it['name']}({it['arguments']})")
        elif kind == "function_call_output":
            out.append(f"TOOL RESULT: {str(it['output'])[:max_chars]}")
        elif it.get("role") == "user":
            out.append(f"USER: {it['content']}")
        elif kind == "message":
            out.append("ASSISTANT: " + " ".join(c.get("text", "") for c in it.get("content", [])))
    return "\n".join(out)


SUMMARY_PROMPT = """You are compacting the working memory of an AI assistant.
Write a summary that lets the assistant continue the task WITHOUT the original messages. Keep, in this order:
1. Goal of the task and the user's constraints
2. Decisions already made, and why
3. Facts and numbers discovered (exact values, IDs, dates)
4. What has been done / what is still open
Drop: greetings, repetition, raw tool output already digested. Be concise; use bullet points.

<transcript>
{transcript}
</transcript>

Now write the summary. Do NOT answer or continue the conversation above, even if it ends with a question."""


def summarise(text: str) -> str:
    r = client.responses.create(model=MODEL, input=SUMMARY_PROMPT.format(transcript=text),
                                reasoning={"effort": "low"}, max_output_tokens=4_000)
    return r.output_text.strip()


class SummaryTail:
    """Should compact? Past `threshold` of the window: [task] + [summary] of the old part + [tail] word for word."""

    def __init__(self, window: int, threshold: float = 0.80, keep: int = 2, summarise=summarise):
        self.window, self.threshold, self.keep, self.summarise = window, threshold, keep, summarise

    def __call__(self, conv) -> dict | None:
        before = desk_tokens(conv)
        if before < self.threshold * self.window:
            return None                                       # not full yet
        items = conv.input
        starts = step_starts(items)
        if len(starts) <= self.keep:
            return None                                       # nothing old enough to summarise
        cut = starts[-self.keep]
        old, tail = items[1:cut], items[cut:]                 # items[0] is the task: pinned
        summary = self.summarise(as_text([items[0], *old]))      # with the task: what the work is FOR
        conv.input = [items[0], {"role": "user", "content": f"[summary] of earlier work:\n{summary}"}, *tail]
        return {"before": before, "after": desk_tokens(conv), "summarised": len(old), "kept": len(tail),
                "window": self.window}


@contextmanager
def sqlite_sandbox(call, tools):
    """Run the call inside a transaction, show the diff, COMMIT on a yes, ROLLBACK otherwise."""
    with life_tools.LOCK:                              # one change at a time, even with many harnesses
        conn = life_tools.rw()
        before = lifedb.snapshot(conn)
        conn.execute("BEGIN")
        box = Box(preview="")
        try:
            box.result = execute_tool(call, tools)
            box.preview = lifedb.diff(before, lifedb.snapshot(conn))
            yield box
        finally:
            conn.execute("COMMIT" if box.keep else "ROLLBACK")


ALEX_POLICY = policy_by_effect(overrides={"draft_email": "allow", "remember": "allow"})


def read_skill(path: Path) -> dict:
    """SKILL.md: a small header (name, description) between --- lines, then the instructions."""
    _, header, body = path.read_text(encoding="utf-8").split("---", 2)
    meta = dict(line.split(":", 1) for line in header.strip().splitlines())
    return {"name": meta["name"].strip(), "description": meta["description"].strip(), "body": body.strip()}


def skills_module(folder: str = "skills") -> dict:
    skills = {s["name"]: s for s in map(read_skill, sorted(Path(folder).glob("*/SKILL.md")))}

    class LoadSkillIn(Args):
        name: str = Field(json_schema_extra={"enum": list(skills)})

    def load_skill(name: str) -> str:
        if name not in skills:
            raise ValueError(f"No skill '{name}'. Skills: {', '.join(skills)}")
        return skills[name]["body"]

    menu = "\n".join(f"- {s['name']}: {s['description']}" for s in skills.values())
    return {
        "system": "Skills: step-by-step instructions for jobs Alex asks for often. When a task matches one, "
                  "call load_skill with its name FIRST, then follow it.\n" + menu,
        "tools": {"load_skill": tool(load_skill, input_model=LoadSkillIn, description=
                                     "Load the full instructions of one skill from the menu in your instructions.")},
        "skills": skills,
    }


SKILLS = skills_module()


def memory_module(path: str = "memories/alex.md") -> dict:
    file = Path(path)

    class RememberIn(Args):
        fact: str = Field(min_length=3, max_length=300, description="One short fact, in Alex's words")

    def remember(fact: str) -> str:
        file.parent.mkdir(parents=True, exist_ok=True)
        with file.open("a", encoding="utf-8") as f:
            f.write(f"- {fact}\n")
        return "Remembered."

    notes = file.read_text(encoding="utf-8") if file.exists() else "(nothing yet)"
    return {"system": f"What you remember about Alex from earlier sessions (his rules: follow them):\n{notes}\n"
                      "When Alex tells you something to keep for next time, call remember.",
            "tools": {"remember": tool(remember, input_model=RememberIn, effect=WRITE, description=
                                       "Save one fact about Alex for future sessions.")}}


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
    """The steering queue + the priority gate. Safe to call put() from another thread (a chat UI)."""

    def __init__(self):
        self.q, self.count = queue.PriorityQueue(), itertools.count()

    def put(self, text: str) -> None:
        urgent = text.strip().lower().rstrip("!. ").split(" ")[0] in URGENT
        self.q.put(Message(0 if urgent else 1, next(self.count), text))

    def waiting(self) -> bool:
        return not self.q.empty()

    def let_in(self) -> list[Message]:
        """Called by the harness between two steps: everything waiting, urgent first."""
        out = []
        while not self.q.empty():
            out.append(self.q.get_nowait())
        return out


def triage_task(email: dict) -> str:
    return (f"New email from {email['from']}, subject '{email['subject']}':\n\n{email['body']}\n\n"
            "Handle it for Alex: update the calendar if needed and draft a reply if one is needed. "
            "Alex reviews everything in the morning.")


def remote_harness(name: str, **overrides) -> Harness:
    settings = dict(system=SYSTEM, name=name, modules=[SKILLS], policy=ALEX_POLICY, approver=always("hold"),
                    sandbox=sqlite_sandbox)
    return Harness(ALL_TOOLS, **(settings | overrides))


def morning_triage(emails: list[dict], *, quiet: bool = False, **overrides) -> dict[str, tuple[Harness, list]]:
    """The cron job: one headless harness per email, in parallel."""
    harnesses = {e["id"]: remote_harness(e["id"], **overrides) for e in emails}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {e["id"]: pool.submit(run, harnesses[e["id"]], triage_task(e), quiet=quiet, tag=True)
                   for e in emails}
        return {k: (harnesses[k], f.result()) for k, f in futures.items()}


def approve(held: Held, tools: dict = ALL_TOOLS) -> str:
    """Alex said yes in the morning: do it for real now (it can still fail if the calendar changed)."""
    return execute_tool(ToolCall("approved", held.tool, held.args), tools).content


RUNS = Path("runs")


def record(events: Iterator[Event], path: Path) -> Iterator[Event]:
    """The flight recorder: pass every event through, and append it to a JSONL file on the way."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(asdict(ev), ensure_ascii=False, default=str) + "\n")
            f.flush()
            yield ev


def replay(path: Path) -> list[Event]:
    return [Event(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def recorded_run(harness: Harness, task: str, path: Path, **kw) -> list[Event]:
    events = []
    for ev in record(harness.run(task), path):
        events.append(ev)
        if not kw.get("quiet"):
            show(ev, tag=kw.get("tag", False))
    return events


def calls(events: list[Event]) -> list[tuple[str, dict, bool]]:
    """(tool, args, worked) for every action: each action is followed by its observation."""
    out, pending = [], []
    for e in events:
        if e.kind == "action":
            pending.append(e.data)
        elif e.kind == "observation" and pending:
            a = pending.pop(0)
            out.append((a["tool"], a["args"], not e.data["error"]))
    return out


def booked(events) -> list[dict]:
    """Calendar changes the agent made or put on hold (both count: Alex approves holds)."""
    return [a for t, a, ok in calls(events) if ok and t in ("create_event", "move_event")]


def wrote(events, tool_name: str) -> bool:
    return any(t == tool_name and ok for t, a, ok in calls(events))


CHECKS = {
    "northwind": lambda ev: (any(b["date"] in (WEEK.day(1), WEEK.day(3)) and "08:00" <= b["start"]
                                 and b["end"] <= "09:00" for b in booked(ev))
                             and wrote(ev, "draft_email") and not wrote(ev, "send_email")),
    "brightline": lambda ev: (any(b["date"] == WEEK.day(4) and b["start"] == "08:00" for b in booked(ev))
                              and wrote(ev, "draft_email") and not wrote(ev, "send_email")),
    "school": lambda ev: not booked(ev) and not wrote(ev, "draft_email") and not wrote(ev, "send_email"),
}


def benchmark(label: str, repeats: int = 3, **overrides) -> dict[str, list[bool]]:
    """Every email, `repeats` times, each through a fresh remote harness, all in parallel.
    Every run is recorded to runs/<label>-<email>-<n>.jsonl. Models vary: one run proves little."""
    jobs = [(e, n) for e in life_tools.inbox() for n in range(1, repeats + 1)]
    with ThreadPoolExecutor(max_workers=9) as pool:
        futures = [(e["id"], n, pool.submit(recorded_run, remote_harness(f"{e['id']}-{n}", **overrides),
                                            triage_task(e), RUNS / f"{label}-{e['id']}-{n}.jsonl", quiet=True))
                   for e, n in jobs]
        results: dict[str, list[bool]] = {}
        for case, n, f in futures:
            results.setdefault(case, []).append(CHECKS[case](f.result()))
    passed = sum(map(sum, results.values()))
    print(f"{label:<16} " + "  ".join(f"{k} {sum(v)}/{len(v)}" for k, v in results.items())
          + f"   total {passed}/{len(jobs)}")
    return results
