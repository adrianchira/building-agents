# Week 4: What is an agent harness?

*Course project: a personal assistant for Alex, 44: full-time developer, parent of two, retraining as an AI engineer.
This week the pieces from weeks 1–3 become one engine: a headless harness with three doors into it.*

The notebook follows the talk **"What Is an Agent Harness?"** slide by slide: the car (model vs harness), the engine
room (loop, desk, modules), the doors (interactive, remote, evals), and the coding-agent diagram as a case study.
Every technique is built and run in the notebook first; packaging it is the homework.

> **Same model. Better harness. Better agent.**

## What's here

| File | What it is |
|---|---|
| `04_agent_harness.ipynb` | **Start here.** Sections 1–9, like the talk |
| `checkpoint.py` | Catch-up file, generated from the notebook's code: `from checkpoint import *` loads the harness up to a section. The notebook's CLI door imports it too |
| `life_tools.py` | Alex's tools: week 2's reads and writes (calendar, tasks), week 3's binder, **email** (`draft_email`, `send_email`), and `inbox()`: three emails that arrived overnight. All writes go through one connection, so a sandbox can wrap them in a transaction |
| `skills/*/SKILL.md` | Three skills: `reply-to-recruiter`, `reschedule`, `weekly-review` |
| `providers.py` | Week 3's, plus `add_user_message()` (steering) and a per-call `max_tokens` the harness can lower |
| `lifedb.py` | Week 3's, plus an `outbox` table for emails |
| `agent_core.py`, `simweek.py` | Same as week 3 (`tool()`, `execute_tool`; section 1 uses the old `run_agent` as "the car we built") |
| `solution/harness/` | The homework's reference package (`core`, `events`, `context`, `modules/`, `doors/`, `observe`, `alex`), with 23 offline tests in `solution/tests/` (a scripted fake model, no API key) |

Run the solution's doors from `solution/`: `python -m harness.doors.remote "What's on Thursday?"` or `--triage`.

## Session plan (90 minutes, setup done at home)

| Time | Section | Slides | What happens |
|---|---|---|---|
| 0:00 | 0. Setup | | `%run ../check_setup.py` |
| 0:03 | 1. Engine vs car | 2–3 | Same question, model alone vs. model in a harness |
| 0:08 | 2. Headless engine | 4, 10 | `Event`, `Limits`, the `Harness` class (read `run()` together), `show` / `turn_table` |
| 0:20 | 3. The loop | 5–6 | Northwind wants to move the screen: slide 6's table, for Alex. Limits |
| 0:28 | 4. Desk + compaction | 7–8 | `SummaryTail` on a 4,000-token desk: `[summary]` + `[tail]` |
| 0:36 | 5. Modules | 9 | Sandbox diffs + a scripted "no" · skills (menu vs. pages) · memory across sessions · providers |
| 0:52 | 6. Doors | 11–12 | Steering queue + priority gate · three overnight emails in parallel, changes held · CLI · (webhook optional) |
| 1:07 | 7. Evals & observability | 13 | Flight recorder, a 3-email benchmark ×3, the regression check (with vs. without skills), replay a failure |
| 1:17 | 8. Any agent | 14 | Slide 6's support agent ("charged twice") on the same `Harness` |
| 1:22 | 9. Case study + takeaways | 15–17 | The coding-agent diagram mapped to our code; office-hours questions; homework |

About 5 minutes of model time on `gpt-6-luna` for the whole notebook; about **$0.02** per student.

## What students should see (from real runs)

| Section | Result |
|---|---|
| 1 | The model alone: *"I can't tell without your calendar"* (or a guess: Wednesday 12:00) · in the harness: **Friday 08:00** |
| 3 | 5 turns: read preferences → list events → `move_event` (**⏸ paused for a human**) → `draft_email` → answer. `max_turns=2` stops cleanly |
| 4 | the desk climbs to ~86%, **compacts to ~50%**, and the six gym counts still match the database |
| 5a | the approval shows `- old row / + new row`; Alex's "no" to `send_email` is rolled back, the draft stays |
| 5b | the model loads `reply-to-recruiter` from the menu, books Friday 08:00, saves a **draft** signed "Best, Alex" |
| 5c | "Can I take a call Thursday 08:00?": without memory *yes* · with memory *no, Thursday is capstone day* |
| 6a | the correction typed mid-run goes in between steps, and the call is booked on Thursday · `stop` goes ahead of a normal message and ends the run |
| 6b | three harnesses in ~12 s together; Northwind and Brightline changes held with their diffs. The school email needs nothing: some runs leave it alone, some hold a reminder event (discuss: is that helpful or noise?) |
| 7 | in our runs: with skills 7–8/9 · without 5–6/9. A replayed failure without the skill: a call booked at 17:30, in Alex's no-calls window. The gap is small and noisy: a good opening for week 5 |
| 8 | slide 6, reproduced: orders → policy → refund (⏸) → reply → stop |

Model outputs vary between runs: the shape of the results is stable, the exact numbers are not.

## Things we found while testing (good discussion material)

| What happened | Fix | Where |
|---|---|---|
| After compaction the agent started the job over and looped to the turn limit: the summary began *"the original request is missing"* | Give the summariser the pinned task too: `as_text([items[0], *old])` | section 4 |
| A model call "ran away" twice: 16,000 output tokens, up to 5 minutes, no answer. Turn/cost/time limits only check *between* steps | `Limits.max_output_tokens` (4,000) caps each reply | section 3 |
| Parallel harnesses share one database connection: a write from one could land inside another's dry-run transaction and be rolled back with it | Every write takes `life_tools.LOCK` | `life_tools.py` |
| One run per benchmark case flipped between "skills help" and "skills hurt" | Repeat each case 3× and report n/3 | section 7 |

## Notes for the instructor

- OpenAI by default; `Harness(provider="anthropic", model="claude-sonnet-5-5")` runs on Claude.
- `chat()` (section 6a) uses `input()`: it works in VS Code, not in an automated run, so its call is commented out.
- The CLI cell writes `alex_cli.py` and runs it with the notebook's own Python (`sys.executable`), so the venv is used.
- `memories/`, `runs/` and `alex_cli.py` are created by the notebook and ignored by git.
- Students who fall behind: the checkpoint cell at the start of each section (`from checkpoint import *`).
- After a `git pull` during the course, restart the notebook's kernel: Python keeps the old modules in memory.
