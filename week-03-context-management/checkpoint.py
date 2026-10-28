"""Catch-up file: the same code as the notebook's code cells (setup + every technique).
If a section failed for you, run `from checkpoint import *` in the next section's checkpoint cell.
Generated from the notebook: do not edit by hand."""

import copy, hashlib, json, math, os, re, shutil, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import agent_core, lifedb, life_tools
from agent_core import WRITE, run_agent
from providers import load_api_key, open_conversation

PROVIDER, MODEL = "openai", "gpt-6-luna"
load_api_key(PROVIDER)
from openai import OpenAI
client = OpenAI()

DB = lifedb.create_db()          # Alex's week (dated to this week) + a year of history
WEEK = lifedb.week()
SYSTEM = (
    "You are a personal assistant for Alex, a 44-year-old software developer with a full-time job and two kids, "
    f"who is retraining to become an AI engineer. Today is {WEEK.today}. "
    "Use the tools to look at Alex's calendar, tasks and notes; never guess. Reply briefly."
)

print(f"Ready: {MODEL}, Alex's week {WEEK.label(0)} – {WEEK.label(6)}")


Message = dict
LLM = Callable[[str], str]  # prompt in -> text out


def count_tokens(obj) -> int:
    """Rough token estimate (~4 characters per token for English text).

    Good enough to drive thresholds. For exact numbers read `usage.input_tokens`
    from the last API response."""
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return max(1, len(text) // 4)


def context_size(messages: list[Message], system: str = "") -> int:
    return count_tokens(system) + sum(count_tokens(m) for m in messages)


KEY_PATTERNS = re.compile(r"(decid|agreed|must|never|always|deadline|budget|todo|open question|"
                          r"prefer|error|fixed|found|result|\d)", re.IGNORECASE)


def fake_llm(prompt: str) -> str:
    """Deterministic 'summarizer' so demos run without an API key: keeps sentences that look
    important (decisions, numbers, constraints) and drops chit-chat."""
    body = prompt.split("<transcript>")[-1].split("</transcript>")[0]
    sentences = re.split(r"(?<=[.!?])\s+|\n", body)
    keep = [s.strip() for s in sentences if s.strip() and KEY_PATTERNS.search(s)]
    seen, out = set(), []
    for s in keep:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return "\n".join(f"- {s[:160]}" for s in out[:15]) or "- (nothing important)"


def make_llm(real: bool = False, model: str | None = None) -> LLM:
    """real=False: the offline fake summariser. real=True: an OpenAI model via the Responses API."""
    if not real:
        return fake_llm
    model = model or os.getenv("OPENAI_SUMMARY_MODEL", "gpt-6-luna")

    def call(prompt: str) -> str:
        return client.responses.create(model=model, input=prompt, max_output_tokens=1500).output_text

    return call


def render(messages: list[Message], width: int = 90) -> str:
    """One line per message - handy for showing 'what is on the desk'."""
    lines = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            lines.append(f"[{m['role']}] {c[:width]}")
            continue
        for b in c:
            t = b.get("type")
            if t == "text":
                lines.append(f"[{m['role']}] {b['text'][:width]}")
            elif t == "tool_use":
                lines.append(f"[{m['role']} -> tool] {b['name']}({json.dumps(b['input'])[:60]})")
            elif t == "tool_result":
                body = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                lines.append(f"[tool_result] ({count_tokens(body)} tok) {body[:width - 20]}")
    return "\n".join(lines)


def to_transcript(messages: list[Message], max_tool_chars: int = 300) -> str:
    """Flatten messages to plain text for a summarizer prompt."""
    out = []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            out.append(f"{m['role'].upper()}: {c}")
            continue
        for b in c:
            t = b.get("type")
            if t == "text":
                out.append(f"{m['role'].upper()}: {b['text']}")
            elif t == "tool_use":
                out.append(f"TOOL CALL: {b['name']}({json.dumps(b['input'])})")
            elif t == "tool_result":
                body = b["content"] if isinstance(b["content"], str) else json.dumps(b["content"])
                out.append(f"TOOL RESULT: {body[:max_tool_chars]}")
    return "\n".join(out)


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


WINDOW, RESERVE = 6_000, 1_000

REVIEW = (f"Review my last 8 weeks, one week at a time (each Monday to Sunday, the first one starting "
          f"{WEEK.day(-56)}). For each week: hours spent in AI course sessions, number of networking chats, "
          "number of gym sessions. Look up exactly one week per tool call, and before the next lookup write "
          "that week's three numbers in one short line (your notes). "
          "Then tell me in two sentences which week was the least balanced.")


OPAQUE = ("encrypted_content", "id", "status")   # bookkeeping fields: not text the model reads


def desk_budget(conv) -> ContextBudget:
    """Alex's desk, zone by zone: what the model will read on its next call."""
    b = ContextBudget(window=WINDOW, reserve_output=RESERVE)
    b.add("system", conv.system)
    b.add("tools", conv.tools)
    for item in conv.input:
        kind = item.get("type")
        zone = ("tool_results" if kind == "function_call_output"
                else "tool_calls" if kind in ("function_call", "reasoning") else "history")
        b.add(zone, {k: v for k, v in item.items() if k not in OPAQUE})
    return b


def ground_truth(weeks=8):
    for k in range(weeks, 0, -1):
        start, end = WEEK.day(-7 * k), WEEK.day(-7 * k + 6)
        rows = life_tools.db_rows("SELECT title FROM events WHERE date BETWEEN ? AND ?", (start, end))
        course = 1.5 * sum(r["title"].startswith("AI course") for r in rows)
        chats = sum(r["title"] == "Networking chat" for r in rows)
        gym = sum(r["title"] == "Gym" for r in rows)
        print(f"week of {start}: course {course:4.1f} h · networking {chats} · gym {gym}")


def _starts_with_orphan_tool_result(msg) -> bool:
    c = msg["content"]
    return msg["role"] == "user" and isinstance(c, list) and any(b.get("type") == "tool_result" for b in c)


def _text(msg) -> str:
    c = msg["content"]
    return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c)


def sliding_window(messages, budget_tokens: int, pin_first: int = 1):
    """Return pinned head + the newest messages that fit in budget_tokens."""
    pinned = messages[:pin_first]
    budget = budget_tokens - sum(count_tokens(m) for m in pinned)

    kept = []
    for msg in reversed(messages[pin_first:]):
        cost = count_tokens(msg)
        if cost > budget:
            break
        kept.insert(0, msg)
        budget -= cost

    # Pairing rule: drop leading tool_results whose tool_use fell off the desk.
    while kept and _starts_with_orphan_tool_result(kept[0]):
        kept.pop(0)
    # Roles must alternate: the first kept message after the pin should be an assistant turn.
    while kept and pinned and kept[0]["role"] == pinned[-1]["role"]:
        kept.pop(0)

    dropped = len(messages) - len(pinned) - len(kept)
    if dropped:
        # Tell the model something is missing - silent gaps cause confusion.
        note = {"role": "assistant", "content": f"[{dropped} earlier messages were removed to save space]"}
        if kept and kept[0]["role"] == "assistant":
            kept[0] = {"role": "assistant", "content": note["content"] + "\n" + _text(kept[0])}
        else:
            kept.insert(0, note)
    return pinned + kept


SUMMARY_PROMPT = """You are compacting the working memory of an AI assistant.
Write a summary that lets the assistant continue the task WITHOUT the original
messages. Keep, in this order:
1. Goal of the task and the user's constraints (budgets, dates, preferences)
2. Decisions already made, and why
3. Facts and numbers discovered (exact values, IDs, file names)
4. What has been done / what is still open (next steps, open questions)
Drop: greetings, repetition, raw tool output already digested.
Be concise; use bullet points.

<previous_summary>
{previous}
</previous_summary>

<transcript>
{transcript}
</transcript>

Now write the summary. Do NOT answer or continue the conversation above, even if it ends with a question."""
# ^ course fix: without that last line, a real model sometimes answered the transcript's last question
#   instead of summarising it, and every earlier fact was lost (see the discussion below).

SUMMARY_TAG = "[CONVERSATION SUMMARY]"


def _is_summary(m) -> bool:
    return isinstance(m["content"], str) and m["content"].startswith(SUMMARY_TAG)


class Compactor:
    def __init__(self, llm, window: int, trigger: float = 0.70, keep_last: int = 6):
        self.llm, self.window, self.trigger, self.keep_last = llm, window, trigger, keep_last
        self.summary = ""
        self.compactions = 0

    def needs_compaction(self, messages) -> bool:
        return context_size(messages) > self.trigger * self.window

    def compact(self, messages):
        if not self.needs_compaction(messages) or len(messages) <= self.keep_last:
            return messages
        head, tail = messages[:-self.keep_last], messages[-self.keep_last:]
        # Do not split a tool_use / tool_result pair across the boundary.
        while tail and tail[0]["role"] == "user" and isinstance(tail[0]["content"], list):
            head.append(tail.pop(0))
        # Messages must alternate and start with the user: make the tail start with assistant.
        if tail and tail[0]["role"] == "user":
            head.append(tail.pop(0))

        head = [m for m in head if not _is_summary(m)]  # old summary is passed separately
        self.summary = self.llm(SUMMARY_PROMPT.format(
            previous=self.summary or "(none)", transcript=to_transcript(head)))
        self.compactions += 1
        summary_msg = {"role": "user", "content": f"{SUMMARY_TAG}\n{self.summary}"}
        return [summary_msg] + tail


CHAT_SYSTEM = (
    "You are Alex's personal assistant. Alex is a 44-year-old developer with a full-time job and two kids, "
    f"retraining as an AI engineer. This chat runs through the week that starts on {WEEK.today}; "
    "every message starts with its day and time. Keep answers short: at most 80 words."
)

ALEX_WEEK = [
    ("Mon 07:45", "Morning! Context for this week: my partner is travelling Wednesday and Thursday, so I'm on my own "
                  "with the kids. No calls between 18:00 and 20:00 on those days."),
    ("Mon 12:30", "Lunch break. In what order should I tackle my capstone tasks? The RAG pipeline scares me."),
    ("Mon 21:10", "Coffee chat with Priya went great. She'll refer me to Kestrel Labs if I send her my resume by Friday."),
    ("Tue 12:10", "Give me 3 good questions to ask the Northwind recruiter tonight."),
    ("Tue 21:15", "Recruiter screen done! Next step: a take-home assignment, due next Wednesday, about 5 hours of work."),
    ("Wed 07:10", "Dentist in an hour. Honestly, what should I prioritise today?"),
    ("Wed 22:00", "Mock interview feedback: my STAR stories are too long. I should aim for 2 minutes each."),
    ("Thu 06:40", "Skipping the gym this morning to work on the RAG pipeline. Bad idea?"),
    ("Thu 21:30", "The RAG pipeline works! Retrieval accuracy went from 62% to 81% after I added reranking."),
    ("Thu 22:15", "Draft 3 bullet points for tomorrow's demo intro, please."),
]

PROBES = [
    ("(Fri 08:00) Remind me: on which evenings was I unavailable for calls this week, and from when to when?",
     lambda a: "18" in a and "20" in a),
    ("(Fri 08:05) By when do I need to send my resume to Priya?", lambda a: "friday" in a or "today" in a),
    ("(Fri 08:10) When is the Northwind take-home due, and how long will it take?",
     lambda a: "wednesday" in a and ("5" in a or "five" in a)),
    ("(Fri 08:15) What was the feedback from my mock interview?", lambda a: "2 minutes" in a or "two minutes" in a),
    ("(Fri 08:20) What retrieval accuracy did my RAG pipeline reach?", lambda a: "81" in a),
]


class ChatSession:
    """A chatbot: the desk is the list of messages. A strategy may tidy it before every call."""

    def __init__(self, strategy=None, extra=None, native=False):
        self.messages, self.strategy, self.extra, self.native, self.log = [], strategy, extra or {}, native, []

    def say(self, text: str) -> str:
        self.messages.append({"role": "user", "content": text})
        if self.strategy:
            self.messages = self.strategy(self.messages)
        r = client.responses.create(model=MODEL, instructions=CHAT_SYSTEM, input=self.messages,
                                    max_output_tokens=2000, reasoning={"effort": "low"}, **self.extra)
        cached = getattr(r.usage.input_tokens_details, "cached_tokens", 0) or 0
        self.log.append({"input": r.usage.input_tokens, "cached": cached})
        if self.native:     # keep the API's own items (needed for server-side compaction, section 8)
            self.messages += [o.model_dump(exclude_none=True, warnings=False) for o in r.output]
        else:
            self.messages.append({"role": "assistant", "content": r.output_text})
        return r.output_text


def play_and_probe(session, label):
    for when, text in ALEX_WEEK:
        session.say(f"({when}) {text}")
    score, answers = 0, []
    for question, check in PROBES:
        answer = session.say(question)
        ok = check(answer.lower())
        score += ok
        answers.append(f"  {'✅' if ok else '❌'} {question}\n     → {answer.strip()[:150]}")
    peak = max(x["input"] for x in session.log)
    total = sum(x["input"] for x in session.log)
    print(f"── {label}: probes {score}/5 · biggest desk {peak:,} tok · {total:,} input tokens in total")
    print("\n".join(answers))
    return {"label": label, "score": score, "peak": peak, "total": total}


STORE = Path("./.tool_outputs")
PLACEHOLDER = "[result cleared to save context - call the tool again if needed]"


def _stored(handle: str) -> Path:                     # course fix: a handle can't point outside STORE
    path = (STORE / handle).resolve()
    if not path.is_relative_to(STORE.resolve()):
        raise ValueError("handle escapes the tool output store")
    return path


# ---------- A. Offload large outputs at ingestion time ----------------------
def offload_if_large(tool_name: str, output: str, max_tokens: int = 500) -> str:
    """Return output unchanged if small; else save it and return a preview."""
    if count_tokens(output) <= max_tokens:
        return output
    STORE.mkdir(exist_ok=True)
    handle = f"{tool_name}-{hashlib.sha1(output.encode()).hexdigest()[:8]}.txt"
    (STORE / handle).write_text(output)
    lines = output.splitlines()
    head, tail = "\n".join(lines[:5]), "\n".join(lines[-3:])
    return (f"[Large output: {count_tokens(output):,} tokens, {len(lines):,} lines. "
            f"Saved as '{handle}'. Use read_slice(handle, start, end) or "
            f"grep(handle, pattern) to look inside.]\n"
            f"--- first lines ---\n{head}\n...\n--- last lines ---\n{tail}")


def grep(handle: str, pattern: str, limit: int = 20) -> str:
    """A tool the agent can call to search an offloaded output."""
    hits = [l for l in _stored(handle).read_text().splitlines() if pattern.lower() in l.lower()]
    return "\n".join(hits[:limit]) + (f"\n... {len(hits) - limit} more" if len(hits) > limit else "")


def read_slice(handle: str, start: int, end: int) -> str:       # course addition: the note promises it
    """A tool the agent can call to read lines start..end (1-based) of an offloaded output."""
    lines = _stored(handle).read_text().splitlines()
    return "\n".join(f"{i}: {l}" for i, l in enumerate(lines[start - 1:end], start))


# ---------- B. Clear old tool results ---------------------------------------
def clear_old_tool_results(messages, keep: int = 3, exclude_tools=("memory",)):
    """Replace all but the `keep` most recent tool results with a placeholder."""
    names = {}  # tool_use_id -> tool name
    for m in messages:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
    positions = [(mi, bi) for mi, m in enumerate(messages)
                 if m["role"] == "user" and isinstance(m["content"], list)
                 for bi, b in enumerate(m["content"])
                 if b.get("type") == "tool_result" and names.get(b["tool_use_id"]) not in exclude_tools]
    freed = 0
    for mi, bi in positions[:-keep] if keep else positions:
        block = messages[mi]["content"][bi]
        if block["content"] != PLACEHOLDER:
            freed += count_tokens(block["content"])
            block["content"] = PLACEHOLDER
    return freed


CLEARED = "[output cleared to save context - call the tool again if needed]"


def clear_old_function_outputs(items, keep=4, exclude=("memory",)):
    """Example 04's clearing, for Responses API items.

    A tool call is a {"type": "function_call", "call_id", "name", ...} item;
    its result is a {"type": "function_call_output", "call_id", "output"} item.
    Keep the call record, blank all but the newest `keep` outputs."""
    names = {i["call_id"]: i["name"] for i in items if i.get("type") == "function_call"}
    outputs = [i for i in items
               if i.get("type") == "function_call_output" and names.get(i["call_id"]) not in exclude]
    for item in outputs[:-keep] if keep else outputs:
        item["output"] = CLEARED


def run_review(tools, manage=None, label="", max_turns=30):
    log = []
    def before_call(conv, turn):
        if manage:
            manage(conv.input)
        log.append(desk_budget(conv).used)
    r = run_agent(REVIEW, tools, system=SYSTEM, model=MODEL, max_turns=max_turns, verbose=False,
                  extra={"parallel_tool_calls": False}, before_call=before_call)
    return {"label": label, "log": log, "result": r}


def bars(run, scale=150):
    limit = WINDOW - RESERVE
    print(f"\n{run['label']}  (peak {max(run['log']):,} tokens, {run['result'].turns} steps)")
    for i, n in enumerate(run["log"], 1):
        print(f"  step {i:2} {n:6,} {'█' * (n // scale)}{'  ! over the desk' if n > limit else ''}")


STICKY_TOOLS = {
    "grep": {"fn": grep, "effect": agent_core.READ, "schema": {
        "name": "grep", "description": "Search a saved tool output (by its handle) for lines containing a text.",
        "input_schema": {"type": "object", "properties": {"handle": {"type": "string"}, "pattern": {"type": "string"}},
                         "required": ["handle", "pattern"]}}},
    "read_slice": {"fn": read_slice, "effect": agent_core.READ, "schema": {
        "name": "read_slice", "description": "Read lines start..end (1-based) of a saved tool output.",
        "input_schema": {"type": "object", "properties": {"handle": {"type": "string"}, "start": {"type": "integer"},
                                                          "end": {"type": "integer"}},
                         "required": ["handle", "start", "end"]}}},
}


def offloaded(tools: dict) -> dict:
    """Wrap every tool so big outputs are offloaded at the door, and add the sticky-note tools."""
    wrapped = {name: {**e, "fn": (lambda _fn=e["fn"], _name=name, **kw: offload_if_large(_name, _fn(**kw), max_tokens=150))}
               for name, e in tools.items()}
    return {**wrapped, **STICKY_TOOLS}


MEMORY_TOOL_SCHEMA = {
    "name": "memory",
    "description": (
        "Your persistent notes. ALWAYS view /memories at the start of a task. "
        "Write down decisions, progress and facts you will need later - your "
        "context may be reset at any moment. Keep files short and organised."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "enum": ["view", "write", "append", "search", "delete"]},  # course fix: type
            "path": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
        },
        "required": ["command"],
    },
}


class FileMemory:
    """Client-side backend. The model calls it through the tool above."""

    def __init__(self, root="./memories", max_file_tokens=2_000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_tokens = max_file_tokens

    def _path(self, p: str) -> Path:
        rel = p.removeprefix("/memories").lstrip("/") or "."
        full = (self.root / rel).resolve()
        if not full.is_relative_to(self.root):      # course fix: block ../../etc/passwd AND ../memories_evil
            raise ValueError("path escapes memory directory")
        return full

    def handle(self, cmd: dict) -> str:
        try:
            c = cmd["command"]
            if c == "view":
                p = self._path(cmd.get("path", "/memories"))
                if p.is_dir():   # course fix: show each note's content, not just its name (the model
                                 # often stopped at the list of names and never opened the note)
                    notes = [f"## {x.name}\n{x.read_text()}" for x in sorted(p.iterdir()) if x.is_file()]
                    return "\n\n".join(notes) or "(empty - nothing remembered yet)"
                return p.read_text()
            if c in ("write", "append"):
                p = self._path(cmd["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                new = (p.read_text() + "\n" if c == "append" and p.exists() else "") + cmd["text"]
                if count_tokens(new) > self.max_file_tokens:
                    return "Error: file too long - summarise it before writing more."
                p.write_text(new)
                return f"Saved {cmd['path']} ({count_tokens(new)} tokens)"
            if c == "search":
                q = cmd["query"].lower()
                hits = [f"{f.name}: {line.strip()}" for f in self.root.rglob("*.md")
                        for line in f.read_text().splitlines() if q in line.lower()]
                return "\n".join(hits[:20]) or "no matches"
            if c == "delete":
                self._path(cmd["path"]).unlink()
                return f"Deleted {cmd['path']}"
            return (f"Error: unknown command {c}. Commands: view (a folder, or a file to read it), "   # course fix:
                    "write, append, search, delete.")                                                   # say what to do
        except Exception as e:  # errors go back to the model, not up the stack
            return f"Error: {e}"


def load_relevant_memories(memory: FileMemory, user_message: str, budget_tokens=400) -> str:
    """For chatbots: inject only memories that match the new message."""
    words = {w.strip(".,?!").lower() for w in user_message.split() if len(w) > 3}
    scored = []
    for f in memory.root.rglob("*.md"):
        for line in f.read_text().splitlines():
            score = sum(w in line.lower() for w in words)
            if score:
                scored.append((score, line.strip()))
    out, used = [], 0
    for _, line in sorted(scored, reverse=True):
        if used + count_tokens(line) > budget_tokens:
            break
        out.append(line)
        used += count_tokens(line)
    return "\n".join(out)


MEMORY = FileMemory("./memories")
MEMORY_TOOL = {"memory": {"fn": lambda **cmd: MEMORY.handle(cmd), "effect": WRITE, "schema": MEMORY_TOOL_SCHEMA}}
QUESTION = "Northwind asked for a quick call on Thursday from 7:45 to 8:15, before work. Can I say yes?"


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
    late = [l for l in raw.splitlines() if "LATE" in l]     # the sub-agent 'thinks' (here: plain Python)
    result = {"source": source, "rows_scanned": len(raw.splitlines()), "late_rows": len(late),
              "examples": late[:3], "confidence": "high"}
    assert count_tokens(json.dumps(result)) <= RETURN_BUDGET, "sub-agent answer too long - summarise harder"
    result["_subagent_context_tokens"] = context_size(sub_context)
    return result


WEEK_PAGE = {
    "type": "object",
    "properties": {"course_hours": {"type": "number"}, "networking_chats": {"type": "integer"},
                   "gym_sessions": {"type": "integer"}, "note": {"type": "string"}},
    "required": ["course_hours", "networking_chats", "gym_sessions", "note"],
    "additionalProperties": False,
}


def alex_intern(k: int) -> dict:
    start, end = WEEK.day(-7 * k), WEEK.day(-7 * k + 6)
    binder = life_tools.list_events_raw(start, end)                                # the messy work
    intern = open_conversation(PROVIDER, MODEL, f"Events of the week {start} to {end}:\n{binder}", effort="low",
                               system="Count: hours of 'AI course' sessions (1.5 h each), number of 'Networking chat' "
                                      "events, number of 'Gym' events. note: one short sentence about the week.")
    page = {"week": start, **intern.complete_json(WEEK_PAGE)}
    assert count_tokens(json.dumps(page)) <= RETURN_BUDGET, "the contract: one small page"
    return page


DOCS = {
    "gdpr_art17.md": "Right to erasure. The data subject has the right to obtain erasure of personal data without undue delay.",
    "gdpr_art33.md": "Breach notification. The controller notifies the supervisory authority within 72 hours of becoming aware of a personal data breach.",
    "gdpr_art35.md": "A data protection impact assessment (DPIA) is required where processing is likely to result in a high risk.",
    "aiact_art50.md": "Transparency: providers ensure people are informed that they are interacting with an AI system.",
    "migration_runbook.md": "Cut-over weekend: freeze legacy writes Friday 18:00, reconcile balances, go/no-go Sunday 12:00.",
    "hr_policy.md": "Employees accrue 21 days of annual leave. Meal vouchers are granted per worked day.",
} | {f"filler_{i}.md": "Unrelated corporate text about office plants and parking. " * 30 for i in range(40)}


def tokenize(t: str):
    return re.findall(r"[a-z0-9]+", t.lower())


class BM25:
    def __init__(self, docs: dict, k1=1.5, b=0.75):
        self.names = list(docs)
        self.toks = [tokenize(docs[n]) for n in self.names]
        self.avg = sum(map(len, self.toks)) / len(self.toks)
        df = Counter(w for d in self.toks for w in set(d))
        n = len(self.toks)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, k=3):
        q = tokenize(query)
        scores = []
        for name, d in zip(self.names, self.toks):
            tf = Counter(d)
            s = sum(self.idf.get(w, 0) * tf[w] * (self.k1 + 1) /
                    (tf[w] + self.k1 * (1 - self.b + self.b * len(d) / self.avg)) for w in q)
            scores.append((s, name))
        return [n for s, n in sorted(scores, reverse=True)[:k] if s > 0]


def drop_before_last_compaction(items):
    """After a compaction item, earlier items are no longer needed (input-array chaining)."""
    idx = [n for n, i in enumerate(items) if i.get("type") == "compaction"]
    return items[idx[-1]:] if idx else items


def compact_now(client, items, model=MODEL):
    """Standalone compaction: you choose the moment (e.g. end of a work phase).
    The returned window is canonical: use it as-is, don't prune it."""
    compacted = client.responses.compact(model=model, input=items)
    return [o.model_dump(exclude_none=True, warnings=False) for o in compacted.output]


PRICE = {"input": 0.10, "cached": 0.01, "output": 0.50}      # gpt-6-luna, $ per 1M tokens


def cost(r) -> float:
    uncached = r.input_tokens - r.cached_tokens
    return (uncached * PRICE["input"] + r.cached_tokens * PRICE["cached"] + r.output_tokens * PRICE["output"]) / 1e6


def stamp(conv, turn):
    conv.system = f"Current time: {time.time():.3f}\n" + SYSTEM     # changes every call: breaks the cache


class ContextManager:
    def __init__(self, llm, window=40_000, clear_at=0.50, compact_at=0.75, keep_tools=3, mem_dir="./memories_agent"):
        self.window, self.clear_at, self.keep_tools = window, clear_at, keep_tools
        self.compactor = Compactor(llm, window, trigger=compact_at, keep_last=4)
        self.memory = FileMemory(mem_dir)
        self.log = []

    def ingest_tool_output(self, name: str, output: str) -> str:
        return offload_if_large(name, output, max_tokens=1_500)

    def before_model_call(self, messages):
        size = context_size(messages)
        if size > self.clear_at * self.window:
            freed = clear_old_tool_results(messages, keep=self.keep_tools)
            if freed:
                self.log.append(f"clear  : freed ~{freed:,} tokens")
        if self.compactor.needs_compaction(messages):
            before = context_size(messages)
            messages = self.compactor.compact(messages)
            self.log.append(f"compact: {before:,} -> {context_size(messages):,} tokens")
        return messages


def simulate(strategy: str, steps=40, window=40_000):
    """A fake agent that reads one ~3k-token document per step and takes a note."""
    cm = ContextManager(make_llm(real=False), window=window, mem_dir=f"./memories_agent/{strategy}")
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
