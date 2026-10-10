"""The simulated life as a SQLite database: events + tasks.

The current week (12-18 Oct 2026) comes from data/*.csv. A year of generated
history before it gives us a table big enough to flood a context window.
"""

import csv
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
DB_PATH = HERE / "life.db"

SCHEMA = """
CREATE TABLE events (
    id       INTEGER PRIMARY KEY,
    date     TEXT NOT NULL,          -- YYYY-MM-DD
    start    TEXT NOT NULL,          -- HH:MM (24h)
    end      TEXT NOT NULL,          -- HH:MM (24h)
    title    TEXT NOT NULL,
    category TEXT NOT NULL,          -- class | work | study | health | personal | social | exam
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


def _history(rng: random.Random, first: date, last: date):
    """Plausible past events: lectures, café shifts, gym, the odd social thing."""
    d = first
    while d <= last:
        wd = d.weekday()  # 0 = Monday
        term = not (d.month in (7, 8) or (d.month == 12 and d.day > 19) or (d.month == 1 and d.day < 7))
        if term and wd in (0, 2):
            yield d, "09:00", "10:30", "Lecture", "class", "Room B201"
        if term and wd in (1, 3):
            yield d, "10:00", "12:00", "Lab", "class", "Lab 3"
        if wd in (0, 2, 4) and rng.random() < 0.85:
            yield d, "13:00", "17:00", "Shift at café", "work", "Café Central"
        if wd in (0, 3) and rng.random() < 0.7:
            yield d, "18:30", "19:30", "Gym", "health", "Campus gym"
        if wd == 5 and rng.random() < 0.5:
            yield d, "20:00", "23:00", rng.choice(["Dinner with friends", "Cinema", "Party"]), "social", "Downtown"
        if wd == 6 and rng.random() < 0.9:
            yield d, "10:00", "11:00", "Call with parents", "personal", "Phone"
        d += timedelta(days=1)


def create_db(path: Path = DB_PATH, *, history: bool = True, seed: int = 7) -> Path:
    """(Re)build the database from the CSVs. Safe to call before every experiment."""
    path = Path(path)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    with open(DATA_DIR / "calendar.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO events VALUES (:id, :date, :start, :end, :title, :category, :location)",
                         csv.DictReader(f))
    with open(DATA_DIR / "tasks.csv", encoding="utf-8") as f:
        conn.executemany("INSERT INTO tasks VALUES (:id, :title, :course, :due, :est_hours, :priority, :status)",
                         csv.DictReader(f))
    if history:
        rows = _history(random.Random(seed), date(2025, 9, 1), date(2026, 10, 11))
        conn.executemany("INSERT INTO events (date, start, end, title, category, location) VALUES (?, ?, ?, ?, ?, ?)",
                         ((d.isoformat(), *rest) for d, *rest in rows))
    conn.commit()
    conn.close()
    return path


def connect(path: Path = DB_PATH, *, readonly: bool = False) -> sqlite3.Connection:
    """Read-only connections can't change anything, whatever SQL the model sends."""
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        # isolation_level=None: autocommit, unless WE open a transaction with BEGIN (dry-runs).
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def snapshot(conn: sqlite3.Connection) -> dict[str, set[tuple]]:
    return {t: {tuple(r) for r in conn.execute(f"SELECT * FROM {t}")} for t in ("events", "tasks")}


def diff(before: dict[str, set[tuple]], after: dict[str, set[tuple]]) -> str:
    """Human-readable change list: '- old row' / '+ new row'."""
    lines = []
    for table in before:
        for row in sorted(before[table] - after[table]):
            lines.append(f"  - {table}: {row}")
        for row in sorted(after[table] - before[table]):
            lines.append(f"  + {table}: {row}")
    return "\n".join(lines) or "  (no changes)"
