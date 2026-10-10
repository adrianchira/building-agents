# Week 2: Tools & permissions

*Course project: a personal assistant for Alex, 44: full-time developer, parent of two, retraining as an AI engineer.
This week it gets real tools over a calendar and task database, and the power to change things, safely.*

## What's here

| File | What it is |
|---|---|
| `02_tools_and_permissions.ipynb` | **Start here.** In-class notebook |
| `lifedb.py` | Writes this week's `data/` (via `simweek.py`) and builds `life.db` (SQLite) from it, plus a year of generated history (~550 events) |
| `providers.py` | Same adapters as week 1: OpenAI (default), Claude, Ollama |
| `agent_core.py` | Last week's loop as a module, plus: Pydantic `tool()` helper, parallel read-only batches, `FatalToolError` |
| `data/` | *Generated*, not in git: the same simulated week as week 1, dated to the current week |
| `solution/` | Reference solution for homework 8.1 (week 1 package + `db`, `tools`, `permissions`, `reliability`). **Remove before sharing.** |

## Run it

Open `week-02-tools-and-permissions/02_tools_and_permissions.ipynb` in VS Code, select the `.venv` kernel and run the cells from the top.
Your key must be in the course's `.env` file first (see [Your API key](../README.md#your-api-key)).

Reference solution:

```bash
cd week-02-tools-and-permissions/solution
pytest                                         # 39 tests, no API key: fake model + temporary databases
python main.py --reset "Move my dentist appointment to Friday at 8:00"   # asks before changing anything
```

## Session plan (~3 h)

| Time | Notebook part | Key idea |
|---|---|---|
| 0:00 | 0. Setup | The life database; last week's loop as a module |
| 0:10 | 1. Granularity | One `run_sql` vs narrow tools vs both: compare turns, tokens, correctness |
| 0:40 | 2. Schemas | One Pydantic model = JSON schema + validation; errors that say what to do; valid ≠ correct |
| 1:00 | 3. Outputs | A year of history: ~19k tokens raw vs ~600 capped; return totals, not homework |
| 1:20 | 4. Errors | Model-fixable (hint) vs transient (retry in code) vs fatal (stop); timeouts |
| 1:45 | *break* | |
| 1:55 | 5. Permissions | allow / ask / deny per effect; dry-run in a transaction → diff → commit or rollback |
| 2:30 | 6. Parallel | Read-only batches concurrently, writes one at a time |
| 2:40 | 7. Tool-choice eval | 10 requests × 3 variants: good, vague descriptions, opaque names |
| 2:55 | 8. Homework | Package modules + tests; `add_task`; stretch: undo, cross-provider eval, MCP |

## Notes for the instructor

- Part 5 uses `input()` for approvals. In VS Code the prompt appears as an input box at the **top of the window**;
  type `y` or `n` and press Enter. (The cell keeps running until you answer.)
- `lifedb.create_db()` resets the database. Re-run it after experiments that change data.
- Part 1 makes 9 agent runs and Part 7 makes 30 single calls. The default `gpt-6-luna` keeps that cheap; on Claude the setup cell uses `claude-sonnet-5-5`.
- Known answers (for checking students' runs): 9.25 h of tasks due before Friday's demo; free evenings (19:00–22:30)
  Mon–Thu 2.75 / 2 / 1.5 / 2 h = 8.25 h, so **1 h short**; `free_slots` on Tue 13 Oct (06:00–22:30) = 6.5 h;
  no free 2-hour block inside Alex's focus hours (05:30–06:30, 20:30–22:30) before Thursday night;
  12 h of live AI course sessions in the last 4 weeks. These are the same every week: only the dates move.
