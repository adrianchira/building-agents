# Week 1: The agentic loop, by hand

*Course project: a personal assistant for Alex, 44: full-time developer, parent of two, retraining as an AI engineer. This week it can read the calendar, tasks and notes and do exact arithmetic.*

> An agent is a model in a loop. On each turn the model either **answers** or **asks for a tool**.
> We run the tool, append the result, and call the model again until it's done.

## What's here

| File | What it is |
|---|---|
| `01_agentic_loop.ipynb` | **Start here.** In-class notebook: one call → one tool by hand → the loop → break it → read the trace |
| `providers.py` | Adapters: one interface for OpenAI (default), Claude and Ollama. Used from Part 4 on |
| `LOOPS_IN_THE_WILD.md` | How Hermes Agent and OpenClaw implement the same loop, and why they add what they add |
| `simweek.py` | Writes Alex's week into `data/`, dated to the **current** week (template: the course's `life/` folder) |
| `data/` | *Generated* by the setup cell, not in git: `calendar.csv`, `tasks.csv`, `notes/` (AI course syllabus, preferences, job-search pipeline) |
| `solution/` | Reference solution for homework 8.1 (the notebook refactored into modules, with tests). **Instructors: remove before sharing with students.** |

## Run it

Open `week-01-agentic-loop/01_agentic_loop.ipynb` in VS Code, select the `.venv` kernel and run the cells from the top.
Your key must be in the course's `.env` file first (see [Your API key](../README.md#your-api-key)).

Reference solution:

```bash
cd week-01-agentic-loop/solution
pytest                                   # no API key needed: uses a fake client
python main.py "What do I have on Wednesday, and when could I fit 2 hours of capstone work?"
python main.py --route "List the files"          # classify first, then pick provider + model
```

## Part 9: model routing across providers (optional)

```
task ──► classifier (gpt-6-luna) ──► simple | moderate | hard ──► ROUTES[tier] ──► same agentic loop
```

- **Adapters** (`providers.py`, also in `solution/agent/`): one for the OpenAI **Responses** API, one for the Anthropic Messages API.
  Ollama (≥ 0.13.3) serves the Responses API locally, so the second adapter covers both OpenAI and local models.
  OpenAI's current models only allow tool calling over Chat Completions with reasoning turned off, so we use the Responses API.
- **Route table** (`solution/agent/config.py`): candidates per tier in order of preference. Unavailable providers
  (no `OPENAI_API_KEY`, Ollama not running or model not pulled) are skipped. If a tier has no available model, the router tries stronger tiers first.
- **Classifier fallback:** if classification fails or returns an unknown tier, the router uses `hard`.
- Model names change often. Check them against [OpenAI's model list](https://developers.openai.com/api/docs/models)
  and `ollama list` before class.

## Session plan (~3 h)

| Time | Notebook part | Key idea |
|---|---|---|
| 0:00 | 1. One LLM call | The model can't see your files or do exact math |
| 0:20 | 2. One tool by hand | Schema vs function; `stop_reason == "tool_use"`; *you* are the loop |
| 0:50 | 3. Tool registry | Sandboxed tools; errors are returned to the model, not raised |
| 1:10 | 4. Close the loop | Every `stop_reason` is a branch; we own `max_turns` |
| 1:40 | *break* | |
| 1:50 | 5. Break it | Tool failures, turn limits, bad descriptions, missing calculator |
| 2:20 | 6. Read the trace | History is resent every turn → cost grows ~n² |
| 2:35 | 7. Loops in the wild | Same core, more armour (Hermes, OpenClaw) |
| 2:55 | 8. Homework | Modules + tests, `write_file` with human approval |
| *opt.* | 9. Model routing | Cheap classifier picks a tier → route table picks provider/model → same loop. Adapters for Claude, OpenAI and Ollama |

## Homework

See Part 8 of the notebook:
1. **Refactor into modules** (`config`, `tools`, `tracing`, `loop`, `main`) with tests that run without an API key.
2. **Add `write_file`** behind a `y/N` confirmation; a "no" becomes an error result, not a crash.
3. *Stretch:* token budget in dollars, best-effort answer on `max_turns`, Hermes-style budget warning.

## Notes on the API used

- Default: **OpenAI Responses API**, model `gpt-6-luna` (`PROVIDER`/`MODEL` in the notebook, `config.py` in the solution).
  Tools are sent with `strict: false`: in strict mode every field must be required, which breaks optional arguments.
- Claude (`PROVIDER = "anthropic"`, `claude-opus-5-5`): the adapter also sets `output_config.effort` and
  `fallbacks="default"` (beta): if a safety classifier declines a request, the API reruns it on a fallback model.
- Parts 1–2 show the raw API calls for **both** providers side by side; from Part 4 on, `providers.py` hides the difference.
