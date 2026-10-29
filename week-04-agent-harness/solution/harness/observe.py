"""Door 3's tools, and the screen the engine doesn't have: show, turn_table, record, replay, calls."""

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .events import Event
from .modules.sandbox import fmt_args

ICON = {"start": "▶", "think": "💭", "action": "🔧", "approval": "🔐", "observation": "👀", "steer": "📨",
        "compact": "🗜", "limit": "⛔", "done": "🏁"}
PRINT = threading.Lock()


def short(x: Any, n: int = 140) -> str:
    s = str(x).replace("\n", " | ")
    return s if len(s) <= n else s[:n] + "…"


def describe(ev: Event) -> str:
    d = ev.data
    return {
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


def show(ev: Event, *, tag: bool = False) -> None:
    who = f"[{ev.agent}] " if tag else ""
    indent = "" if ev.kind in ("start", "model", "done") else "   "
    with PRINT:
        print(f"{who}{indent}{ICON.get(ev.kind, '·')} {describe(ev)}")


def run(harness, task: str, *, quiet: bool = False, tag: bool = False, on_event=None) -> list[Event]:
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


def turn_table(events: list[Event]) -> str:
    """Slide 6, as Markdown: one row per action, what the model decided and what the tool reported back."""
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
    head = ["| Turn | The model decides (action) | The tool reports back (observation) |", "|---|---|---|"]
    return "\n".join(head + ["| " + " | ".join(r) + " |" for r in rows])


def record(events: Iterator[Event], path: Path) -> Iterator[Event]:
    """The flight recorder: pass every event through, and append it to a JSONL file on the way."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(asdict(ev), ensure_ascii=False, default=str) + "\n")
            f.flush()
            yield ev


def replay(path: Path) -> list[Event]:
    return [Event(**json.loads(line)) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def recorded_run(harness, task: str, path: Path, *, quiet: bool = False, tag: bool = False) -> list[Event]:
    events = []
    for ev in record(harness.run(task), path):
        events.append(ev)
        if not quiet:
            show(ev, tag=tag)
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
