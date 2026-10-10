# Week 1: The agentic loop, by hand

*Course project: a personal assistant that helps a busy student organise their life. This week it can read the calendar, tasks and notes and do exact arithmetic.*

> An agent is a model in a loop. On each turn the model either **answers** or **asks for a tool**.
> We run the tool, append the result, and call the model again until it's done.

## What's here

| File | What it is |
|---|---|
| `01_agentic_loop.ipynb` | **Start here.** In-class notebook: one call → one tool by hand → the loop → break it → read the trace |
| `LOOPS_IN_THE_WILD.md` | How Hermes Agent and OpenClaw implement the same loop, and why they add what they add |
| `data/` | A simulated student's week (Mon 12 – Sun 18 Oct 2026): `calendar.csv`, `tasks.csv`, `notes/` (syllabus, preferences, café rota) |
| `solution/` | Reference solution for homework 8.1 (the notebook refactored into modules, with tests). **Instructors: remove before sharing with students.** |

## Run it

```bash
cd week-01-agentic-loop
jupyter notebook 01_agentic_loop.ipynb
```

Reference solution:

```bash
cd week-01-agentic-loop/solution
pytest                                   # no API key needed: uses a fake client
python main.py "What do I have on Wednesday, and when could I fit 2 hours of revision?"
python main.py --route "List the files"          # classify first, then pick provider + model
```

## Part 9: model routing across providers (optional)

```
task ──► classifier (Haiku 4.5) ──► simple | moderate | hard ──► ROUTES[tier] ──► same agentic loop
```

- **Adapters** (`solution/agent/providers.py`): one for the Anthropic Messages API, one for the OpenAI **Responses** API.
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

- Model: `claude-opus-5-5`. Change `MODEL` (notebook) or `config.MODEL` (solution) to use a cheaper model.
- `output_config={"effort": "medium"}` controls how much the model thinks per turn.
- `fallbacks="default"` (beta `server-side-fallback-2026-07-01`): if a safety classifier declines a request,
  the API reruns it on a fallback model. It's why the loop calls `client.beta.messages.create`.
