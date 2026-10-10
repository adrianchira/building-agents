"""The life database: building it, connecting to it, and diffing it (for dry-runs)."""

import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import config
from .simweek import build_week

SCHEMA = """
CREATE TABLE events (
    id       INTEGER PRIMARY KEY,
    date     TEXT NOT NULL,          -- YYYY-MM-DD
    start    TEXT NOT NULL,          -- HH:MM (24h)
    end      TEXT NOT NULL,          -- HH:MM (24h)
    title    TEXT NOT NULL,
    category TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT ''
);
CREATE TABLE tasks (
    id        INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    course    TEXT NOT NULL DEFAULT '',
    due       TEXT NOT NULL,         -- YYYY-MM-DD
    est_hours REAL NOT NULL,
    priority  TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    status    TEXT NOT NULL CHECK (status IN ('todo', 'done'))
);
"""

_path: Path = config.DB_PATH
_rw: sqlite3.Connection | None = None


def _history(rng: random.Random, monday: date):
    """A year of plausible past events for Alex: work, gym, kids, the AI course
    (started 7 weeks ago), networking (last 4 months). Everything before `monday`."""
    first, last = monday - timedelta(days=406), monday - timedelta(days=1)
    course_start, networking_start = monday - timedelta(days=48), monday - timedelta(days=133)
    d = first
    while d <= last:
        wd = d.weekday()  # 0 = Monday
        vacation = (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day == 1) or (d.month == 7 and d.day <= 10)
        school = d.month not in (7, 8)
        if wd < 5 and not vacation:
            yield d, "09:00", "17:30", "Work", "work", "Office" if wd in (0, 2, 4) else "Home office"
        if wd in (0, 3) and rng.random() < 0.7:
            yield d, "06:30", "07:30", "Gym", "health", "Fitness center"
        if wd == 0 and school and not vacation:
            yield d, "17:45", "18:30", "Pick up kids from soccer practice", "family", "Riverside Park fields"
        if wd in (1, 3) and d >= course_start:
            yield d, "19:30", "21:00", "AI course: live session", "course", "Zoom"
        if wd < 5 and d >= networking_start and rng.random() < 0.08:
            yield d, "20:00", "20:45", "Networking chat", "networking", "Zoom"
        if wd == 5 and school and rng.random() < 0.8:
            yield d, "09:00", "11:00", "Kids' soccer game", "family", "Riverside Park fields"
        if wd == 6 and rng.random() < 0.9:
            yield d, "17:00", "17:30", "Call with parents", "family", "Phone"
        d += timedelta(days=1)


def create(path: Path | None = None, *, history: bool = True, seed: int = 7) -> Path:
    """(Re)build data/ for the current week, then the database, and make it the active one."""
    week = build_week(config.DATA_DIR, template_dir=config.LIFE_DIR, today=config.WEEK.monday)
    path = Path(path or config.DB_PATH)
    use(path)  # closes any open connection before we delete the file
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    with open(config.DATA_DIR / "calendar.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO events VALUES (:id, :date, :start, :end, :title, :category, :location)",
                         csv.DictReader(f))
    with open(config.DATA_DIR / "tasks.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO tasks VALUES (:id, :title, :course, :due, :est_hours, :priority, :status)",
                         csv.DictReader(f))
    if history:
        rows = _history(random.Random(seed), week.monday)
        conn.executemany("INSERT INTO events (date, start, end, title, category, location) VALUES (?, ?, ?, ?, ?, ?)",
                         ((d.isoformat(), *rest) for d, *rest in rows))
    conn.commit()
    conn.close()
    return path


def use(path: Path) -> None:
    global _path, _rw
    if _rw is not None:
        _rw.close()
    _path, _rw = Path(path), None


def is_current() -> bool:
    """Does the database hold this week's data? (The week moves with the calendar.)"""
    if not _path.exists():
        return False
    conn = sqlite3.connect(_path)
    try:
        row = conn.execute("SELECT date FROM events WHERE id = 1").fetchone()
    finally:
        conn.close()
    return row is not None and row[0] == config.WEEK.day(0)


def path() -> Path:
    return _path


def ro() -> sqlite3.Connection:
    """A fresh read-only connection: whatever SQL the model sends, nothing can change."""
    if not _path.exists():
        from .tools import FatalToolError
        raise FatalToolError(f"database not found at {_path}; run setup first")
    conn = sqlite3.connect(f"file:{_path}?mode=ro", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def rw() -> sqlite3.Connection:
    """The one shared write connection. Autocommit, unless a dry-run opens a transaction."""
    global _rw
    if not _path.exists():
        from .tools import FatalToolError
        raise FatalToolError(f"database not found at {_path}; run setup first")
    if _rw is None:
        _rw = sqlite3.connect(_path, isolation_level=None, check_same_thread=False)
        _rw.row_factory = sqlite3.Row
    return _rw


def snapshot(conn: sqlite3.Connection) -> dict[str, set[tuple]]:
    return {t: {tuple(r) for r in conn.execute(f"SELECT * FROM {t}")} for t in ("events", "tasks")}


def diff(before: dict[str, set[tuple]], after: dict[str, set[tuple]]) -> str:
    lines = []
    for table in before:
        lines += [f"  - {table}: {r}" for r in sorted(before[table] - after[table])]
        lines += [f"  + {table}: {r}" for r in sorted(after[table] - before[table])]
    return "\n".join(lines) or "  (no changes)"
