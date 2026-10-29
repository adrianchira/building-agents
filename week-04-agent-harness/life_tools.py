"""Alex's tools, as a module: week 2's read and write tools, week 3's binder, and email.

    TOOLS          read tools (capped, compact outputs)
    WRITE_TOOLS    tools that change Alex's life: calendar, tasks, emails. Run them through a harness
                   with permissions: every one of them is marked WRITE or DESTRUCTIVE.
    BINDER_TOOLS   one tool that returns everything as JSON: big outputs that fill the desk
    inbox()        the emails that arrived overnight (the remote door's work queue)

Every write goes through ONE connection, `rw()`, so a harness can wrap a call in a transaction
(BEGIN ... ROLLBACK) and show the change before it happens: a sandbox.
"""

import json
import re
import sqlite3
import threading
from datetime import date as _date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

import lifedb
from agent_core import DESTRUCTIVE, WRITE, FatalToolError, tool

MAX_ROWS = 40
EVENT_COLS = ["id", "date", "start", "end", "title", "category", "location"]
TASK_COLS = ["id", "title", "course", "due", "est_hours", "priority", "status"]


def _check_date(v: str) -> str:
    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"'{v}' is not a date. Use YYYY-MM-DD (today is {lifedb.week().today})") from None
    return v


def _check_time(v: str) -> str:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
        raise ValueError(f"'{v}' is not a time. Use 24h HH:MM, e.g. '14:30'")
    return v


Date = Annotated[str, AfterValidator(_check_date), Field(description="YYYY-MM-DD")]
Time = Annotated[str, AfterValidator(_check_time), Field(description="HH:MM, 24-hour clock")]


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


def db_rows(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    if not lifedb.DB_PATH.exists():
        raise FatalToolError(f"database not found at {lifedb.DB_PATH}")
    conn = lifedb.connect(lifedb.DB_PATH, readonly=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def table(rows, columns, limit=MAX_ROWS, hint=""):
    if not rows:
        return "(no rows)"
    lines = ["\t".join(columns)] + ["\t".join(str(r[c]) for c in columns) for r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"... showing {limit} of {len(rows)} rows. {hint}".rstrip())
    return "\n".join(lines)


def _minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _hhmm(mins: int) -> str:
    return f"{mins // 60:02d}:{mins % 60:02d}"


class ListEventsIn(Args):
    start_date: Date
    end_date: Date


def list_events(start_date: str, end_date: str) -> str:
    rows = db_rows("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start", (start_date, end_date))
    return table(rows, EVENT_COLS, hint="Narrow the date range, or use run_sql with COUNT/GROUP BY.")


def list_events_raw(start_date: str, end_date: str) -> str:
    rows = db_rows("SELECT * FROM events WHERE date BETWEEN ? AND ? ORDER BY date, start", (start_date, end_date))
    return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=1)      # everything: a binder


class ListTasksIn(Args):
    status: Literal["todo", "done", "all"] = "todo"
    due_before: Date | None = Field(None, description="Only tasks due strictly before this date")


def list_tasks(status: str = "todo", due_before: str | None = None) -> str:
    sql, params = "SELECT * FROM tasks WHERE 1=1", []
    if status != "all":
        sql, params = sql + " AND status = ?", params + [status]
    if due_before:
        sql, params = sql + " AND due < ?", params + [due_before]
    rows = db_rows(sql + " ORDER BY due", tuple(params))
    return table(rows, TASK_COLS) + f"\nTOTAL est_hours: {sum(r['est_hours'] for r in rows):g} ({len(rows)} tasks)"


class FreeSlotsIn(Args):
    date: Date
    day_start: Time = "06:00"
    day_end: Time = "22:30"
    min_minutes: int = Field(30, ge=5, le=600, description="Shortest slot worth reporting")


def free_slots(date: str, day_start: str = "06:00", day_end: str = "22:30", min_minutes: int = 30) -> str:
    lo, hi = _minutes(day_start), _minutes(day_end)
    busy = sorted((max(_minutes(r["start"]), lo), min(_minutes(r["end"]), hi))
                  for r in db_rows("SELECT start, end FROM events WHERE date = ?", (date,)))
    slots, cursor = [], lo
    for start, end in busy:
        if end <= start:
            continue
        if start - cursor >= min_minutes:
            slots.append((cursor, start))
        cursor = max(cursor, end)
    if hi - cursor >= min_minutes:
        slots.append((cursor, hi))
    if not slots:
        return f"No free slot of {min_minutes}+ min on {date} between {day_start} and {day_end}."
    return "\n".join(f"{_hhmm(s)}-{_hhmm(e)} ({(e - s) / 60:g} h)" for s, e in slots) + \
        f"\nTOTAL free: {sum(e - s for s, e in slots) / 60:g} h"


NOTES = sorted(p.name for p in (lifedb.HERE.parent / "life" / "notes").glob("*.txt"))


def _check_note(v: str) -> str:
    if v not in NOTES:
        raise ValueError(f"Unknown note '{v}'. Choose one of: {', '.join(NOTES)}")
    return v


class ReadNoteIn(Args):
    # an enum in the schema: the model sees exactly which notes exist; the validator enforces it
    name: Annotated[str, AfterValidator(_check_note), Field(json_schema_extra={"enum": [*NOTES]})]


def read_note(name: str) -> str:
    return (lifedb.DATA_DIR / "notes" / name).read_text(encoding="utf-8")


class RunSqlIn(Args):
    query: str = Field(description="One SQLite SELECT statement")


def run_sql(query: str) -> str:
    try:
        rows = db_rows(query)
    except sqlite3.Error as exc:
        raise ValueError(f"SQL error: {exc}. Tables: events({', '.join(EVENT_COLS)}); "
                         f"tasks({', '.join(TASK_COLS)})") from None
    return table(rows, list(rows[0].keys()) if rows else [], hint="Aggregate with COUNT / SUM / GROUP BY.")


TOOLS = {
    "list_events": tool(list_events, input_model=ListEventsIn, description=
        "List calendar events between two dates (inclusive), ordered by time. Shows each event's id."),
    "list_tasks": tool(list_tasks, input_model=ListTasksIn, description=
        "List tasks (default: open ones), optionally only those due before a date. Includes the total estimated hours."),
    "free_slots": tool(free_slots, input_model=FreeSlotsIn, description=
        "Free time on one day between day_start and day_end (default 06:00-22:30), overlapping events merged."),
    "read_note": tool(read_note, input_model=ReadNoteIn, description=
        "Read one of Alex's notes: AI course syllabus, personal preferences, job-search pipeline."),
    "run_sql": tool(run_sql, input_model=RunSqlIn, description=
        "Read-only SQL over Alex's calendar and tasks. Tables: events(id, date, start, end, title, category, "
        "location) with date YYYY-MM-DD and times HH:MM; tasks(id, title, course, due, est_hours, priority, status)."),
}

BINDER_TOOLS = {
    "list_events_raw": tool(list_events_raw, input_model=ListEventsIn, description=
        "List calendar events between two dates (inclusive), with all their details, as JSON."),
}


# ---------------------------------------------------------------- write tools (from week 2)

CATEGORIES = ["work", "course", "job_search", "networking", "family", "health", "personal", "social"]
LOCK = threading.RLock()        # one change at a time: several harnesses may run in parallel
_rw: sqlite3.Connection | None = None
_rw_path = None


def rw() -> sqlite3.Connection:
    """The one read-write connection. Autocommit, unless a sandbox opens a transaction (BEGIN)."""
    global _rw, _rw_path
    if _rw is None or _rw_path != lifedb.DB_PATH:      # reconnect if the database moved
        _rw, _rw_path = lifedb.connect(lifedb.DB_PATH), lifedb.DB_PATH
    return _rw


def reset() -> None:
    """Forget the connection, e.g. after lifedb.create_db() rebuilt the file."""
    global _rw
    if _rw is not None:
        _rw.close()
    _rw = None


def locked(fn):
    """Writes take the lock, so no write can land inside another harness's dry-run transaction."""
    def run(**kwargs):
        with LOCK:
            return fn(**kwargs)
    run.__name__, run.__doc__ = fn.__name__, fn.__doc__
    return run


def _describe(e) -> str:
    return f"#{e['id']} '{e['title']}' {e['date']} {e['start']}-{e['end']}"


def _conflicts(day: str, start: str, end: str, ignore_id: int | None = None) -> list:
    return [r for r in rw().execute("SELECT * FROM events WHERE date = ? AND start < ? AND end > ?",
                                    (day, end, start)) if r["id"] != ignore_id]


class _Slot(Args):
    date: Date
    start: Time
    end: Time

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be after start ({self.start})")
        return self


class CreateEventIn(_Slot):
    title: str = Field(min_length=1, max_length=80)
    category: Literal["work", "course", "job_search", "networking", "family", "health", "personal", "social"]
    location: str = ""


def create_event(date: str, start: str, end: str, title: str, category: str, location: str = "") -> str:
    if clash := _conflicts(date, start, end):
        raise ValueError("Conflicts with " + ", ".join(map(_describe, clash)) +
                         ". Pick another time (see free_slots) or ask Alex what to move.")
    cur = rw().execute("INSERT INTO events (date, start, end, title, category, location) VALUES (?, ?, ?, ?, ?, ?)",
                       (date, start, end, title, category, location))
    return f"Created #{cur.lastrowid} '{title}' {date} {start}-{end}"


def _event(event_id: int):
    row = rw().execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ValueError(f"No event with id {event_id}. Use list_events to find the right id.")
    return row


class MoveEventIn(_Slot):
    event_id: int


def move_event(event_id: int, date: str, start: str, end: str) -> str:
    old = _event(event_id)
    if clash := _conflicts(date, start, end, ignore_id=event_id):
        raise ValueError("Conflicts with " + ", ".join(map(_describe, clash)) + ". Pick another time.")
    rw().execute("UPDATE events SET date = ?, start = ?, end = ? WHERE id = ?", (date, start, end, event_id))
    return f"Moved {_describe(old)} -> {date} {start}-{end}"


class EventIdIn(Args):
    event_id: int


def cancel_event(event_id: int) -> str:
    old = _event(event_id)
    rw().execute("DELETE FROM events WHERE id = ?", (event_id,))
    return f"Cancelled {_describe(old)}"


class TaskIdIn(Args):
    task_id: int


def complete_task(task_id: int) -> str:
    row = rw().execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"No task with id {task_id}. Use list_tasks to find the right id.")
    if row["status"] == "done":
        return f"Task #{task_id} '{row['title']}' was already done."
    rw().execute("UPDATE tasks SET status = 'done' WHERE id = ?", (task_id,))
    return f"Marked #{task_id} '{row['title']}' as done"


# ---------------------------------------------------------------- email (new in week 4)

class EmailIn(Args):
    to: str = Field(description="Recipient's email address")
    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=3000)


def draft_email(to: str, subject: str, body: str) -> str:
    cur = rw().execute("INSERT INTO outbox (to_addr, subject, body, status) VALUES (?, ?, ?, 'draft')",
                       (to, subject, body))
    return f"Saved draft #{cur.lastrowid} to {to}: '{subject}'. Alex can review it and send it."


def send_email(to: str, subject: str, body: str) -> str:
    cur = rw().execute("INSERT INTO outbox (to_addr, subject, body, status) VALUES (?, ?, ?, 'sent')",
                       (to, subject, body))
    return f"Sent email #{cur.lastrowid} to {to}: '{subject}'"


def outbox() -> list[dict]:
    return [dict(r) for r in rw().execute("SELECT * FROM outbox ORDER BY id")]


WRITE_TOOLS = {
    "create_event": tool(locked(create_event), input_model=CreateEventIn, effect=WRITE, description=
        "Add an event to the calendar. Fails if it overlaps an existing event."),
    "move_event": tool(locked(move_event), input_model=MoveEventIn, effect=WRITE, description=
        "Move an existing event (by id) to a new date and time. Fails on overlap."),
    "complete_task": tool(locked(complete_task), input_model=TaskIdIn, effect=WRITE, description=
        "Mark a task (by id) as done."),
    "cancel_event": tool(locked(cancel_event), input_model=EventIdIn, effect=DESTRUCTIVE, description=
        "Delete an event (by id) from the calendar. Cannot be undone."),
    "draft_email": tool(locked(draft_email), input_model=EmailIn, effect=WRITE, description=
        "Save an email as a draft in Alex's outbox. Nothing is sent: Alex reviews drafts and sends them himself."),
    "send_email": tool(locked(send_email), input_model=EmailIn, effect=DESTRUCTIVE, description=
        "Send an email on Alex's behalf, right now. It can't be unsent."),
}


# ---------------------------------------------------------------- the inbox (the remote door's work)

def inbox() -> list[dict]:
    """Emails that arrived overnight, dated to the simulated week (they arrive Monday night)."""
    w = lifedb.week()
    return [
        {"id": "northwind", "from": "dana.reyes@northwind.ai", "subject": "Moving our screen?", "body":
            f"Hi Alex, I just noticed our recruiter screen on {w.label(1)} at 20:30 overlaps your evening class. "
            f"Happy to move it! I'm free {w.label(1, True)} to {w.label(3, True)}, any time between 08:00 and "
            "18:00 Eastern. It's a 30-minute call. Just send me a time that works. Best, Dana"},
        {"id": "brightline", "from": "talent@brightlinehealth.com", "subject": "Technical interview", "body":
            "Hello Alex, thanks for applying to the AI Engineer role. We'd like to invite you to a 45-minute "
            f"technical interview (video). Could you do one of these: {w.label(2)} 12:00, {w.label(3)} 18:00, or "
            f"{w.label(4)} 08:00? Please reply with your choice. Kind regards, Brightline Talent Team"},
        {"id": "school", "from": "office@lincoln-elementary.org", "subject": "Reminder: field-trip forms", "body":
            f"Dear parents, a reminder that signed field-trip forms are due {w.label(2)}. "
            "No reply needed. Thank you! Lincoln Elementary Office"},
    ]
