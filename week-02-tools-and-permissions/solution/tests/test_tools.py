"""Tools against a real (temporary) SQLite database. No API key needed."""

from types import SimpleNamespace as NS

from agent import db
from agent.tools import TOOLS, execute_tool


def call(tool_name, **args):
    return execute_tool(NS(id="t", name=tool_name, input=args))


# ---------- read tools ----------

def test_list_events_shows_ids_and_overlap():
    out = call("list_events", start_date="2026-10-13", end_date="2026-10-13").content
    assert "AI course: live session" in out and "Recruiter screen: Northwind AI" in out
    assert out.splitlines()[0].startswith("id\tdate")


def test_list_tasks_returns_total():
    out = call("list_tasks", due_before="2026-10-16").content
    assert "TOTAL est_hours: 9.25 (6 tasks)" in out


def test_free_slots_merges_overlapping_events():
    out = call("free_slots", date="2026-10-13").content  # course 19:30-21:00 overlaps recruiter 20:30-21:00
    assert out.splitlines()[:3] == ["06:00-09:00 (3 h)", "17:30-19:30 (2 h)", "21:00-22:30 (1.5 h)"]
    assert "TOTAL free: 6.5 h" in out


def test_long_output_is_capped_with_a_hint():
    out = call("list_events", start_date="2025-09-01", end_date="2026-10-18").content
    assert "showing 40 of" in out and "run_sql" in out


def test_run_sql_is_read_only():
    r = call("run_sql", query="DELETE FROM events")
    assert r.is_error
    assert len(db.rw().execute("SELECT * FROM events").fetchall()) > 19


def test_run_sql_error_includes_schema():
    r = call("run_sql", query="SELECT starts FROM events")
    assert r.is_error and "no such column" in r.content and "events(id, date, start" in r.content


# ---------- validation at the boundary ----------

def test_bad_date_explains_the_format():
    r = call("free_slots", date="next Tuesday")
    assert r.is_error and "YYYY-MM-DD" in r.content and "today is" in r.content


def test_unknown_fields_are_rejected():
    r = call("list_tasks", status="todo", sort="due")
    assert r.is_error and "sort" in r.content


def test_enum_lists_valid_notes():
    r = call("read_note", name="syllabus")
    assert r.is_error and "course_syllabus.txt" in r.content


def test_end_must_be_after_start():
    r = call("create_event", date="2026-10-15", start="14:00", end="13:00", title="x", category="course")
    assert r.is_error and "must be after start" in r.content


def test_schema_is_generated_from_the_model():
    schema = TOOLS["read_note"]["schema"]["input_schema"]
    assert set(schema["properties"]["name"]["enum"]) == {"course_syllabus.txt", "job_search.txt", "preferences.txt"}
    assert schema["additionalProperties"] is False


# ---------- write tools (unguarded) ----------

def test_create_event_refuses_conflicts():
    r = call("create_event", date="2026-10-13", start="20:00", end="20:30", title="x", category="networking")
    assert r.is_error and "#6 'AI course: live session" in r.content


def test_move_event_and_unknown_id():
    assert "Moved #8 'Dentist'" in call("move_event", event_id=8, date="2026-10-16",
                                         start="08:00", end="08:45").content
    r = call("move_event", event_id=999, date="2026-10-16", start="08:00", end="08:45")
    assert r.is_error and "list_events" in r.content


def test_complete_task_is_idempotent():
    assert "Marked #7" in call("complete_task", task_id=7).content
    assert "already done" in call("complete_task", task_id=7).content
