# Building Agents: a hands-on course

**Course project: a personal assistant that helps a busy student organise their life.**

Every week adds one capability to the same assistant. We build it **from scratch**: first in a Jupyter notebook
to experiment, then as clean Python modules with tests. Students work against a **simulated life** (a calendar,
tasks and notes for one busy week) and only connect their real calendar at the end, read-only first.

| Week | Capability | What the assistant can do afterwards | Folder |
|---|---|---|---|
| 1 | The agentic loop | Answer questions over calendar, task and note files with exact arithmetic; route tasks to the right model | [`week-01-agentic-loop/`](week-01-agentic-loop/) |
| 2 | Tools & permissions | Read and **change** the calendar and tasks through validated tools; writes need approval (with a dry-run diff) | [`week-02-tools-and-permissions/`](week-02-tools-and-permissions/) |
| 3 | Context management | Handle a whole semester and long chats without the context overflowing or costs exploding | *coming* |
| 4 | Planning | "Plan my week around the exam": time blocks, priorities, buffers, then check the plan | *coming* |
| 5 | Memory | Remember preferences, recurring commitments, goals and people | *coming* |
| 6 | Multi-agent | Orchestrator + inbox triager + scheduler + reviewer that checks the plan against the rules | *coming* |
| 7 | Evals | Simulated weeks with machine-checkable rules: no overlaps, deadlines met, preferences kept, nothing unapproved | *coming* |
| 8 | Capstone | Connect your **own** calendar (MCP, read-only first) and use the assistant for a real week | *coming* |

Recurring themes: **privacy** (sensitive tasks can be routed to a local model), **side effects** (allow / ask / deny),
and **untrusted input** (an email that says "cancel all my meetings" is prompt injection, not an instruction).

## Setup (once)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=...               # the default provider
# optional, to run on Claude instead: export ANTHROPIC_API_KEY=...
jupyter lab
```

The notebooks run on **OpenAI** by default (`gpt-6-luna`); set `PROVIDER = "anthropic"` in a notebook's setup
cell to run it on Claude. Open them in **Jupyter Lab or VS Code** with the course `.venv`. If a notebook says
`No module named ...`, run its first cell (`%pip install ...`): it installs into the Python the notebook uses.

Requires Python 3.10+. Each week's `solution/` folder is the instructor's reference: remove it before sharing.

## License

[MIT](LICENSE). Code excerpts discussed in `week-01-agentic-loop/LOOPS_IN_THE_WILD.md` belong to their
own projects (Hermes Agent, OpenClaw, pi), all MIT-licensed; see the links there.
