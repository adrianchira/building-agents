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

## Setup in VS Code (once)

1. **Get the code** and open the folder in VS Code (File → Open Folder… → `building-agents`).
   Install the recommended extensions when VS Code asks (Python, Jupyter).
2. **Create the environment.** In VS Code's terminal (Terminal → New Terminal):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Add your API key** (see below).
4. **Open a notebook**, e.g. `week-01-agentic-loop/01_agentic_loop.ipynb`. Click **Select Kernel** (top right)
   → *Python Environments* → `.venv`. Run the cells from the top.

The notebooks run on **OpenAI** by default (`gpt-6-luna`). Set `PROVIDER = "anthropic"` in a notebook's setup
cell to run it on Claude. If a notebook says `No module named ...`, you picked the wrong kernel: select `.venv`,
or run the notebook's first cell (`%pip install ...`), which installs into whatever Python the notebook uses.

Requires Python 3.10+. Each week's `solution/` folder is the instructor's reference.

## Your API key

Keys live in **one file, `.env`, in the course folder**. Every notebook and script reads it from there.

```bash
cp .env.example .env               # Windows: copy .env.example .env
```

Open `.env` in VS Code, replace `sk-proj-your-key-here` with your OpenAI key, save, and restart the notebook's
kernel. Then the setup cell's `load_api_key(PROVIDER)` finds it, from any week's folder.

Rules:
- **Never paste a key into a notebook cell or a `.py` file.** Notebooks get shared, emailed and pushed to GitHub.
- `.env` is in `.gitignore`, so `git add .` won't publish it. Don't remove that line.
- If a key leaks anyway (pushed, posted, shared), **revoke it immediately** on the provider's dashboard
  (OpenAI: *API keys* page) and create a new one. Deleting the commit is not enough.
- Set a monthly **spending limit** on your OpenAI account. An agent in a loop can make many calls.

## License

[MIT](LICENSE). Code excerpts discussed in `week-01-agentic-loop/LOOPS_IN_THE_WILD.md` belong to their
own projects (Hermes Agent, OpenClaw, pi), all MIT-licensed; see the links there.
