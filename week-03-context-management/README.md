# Week 3: What's on the desk? Context management

*Course project: a personal assistant for Alex, 44: full-time developer, parent of two, retraining as an AI engineer.
This week the assistant learns to keep its desk tidy: what goes on it, what comes off, and in what form.*

The notebook follows the talk **"What's on the desk? Context management for chatbots and agents"** and its companion
code, `context_toolkit` (examples 01–09), section by section. Each section has three steps:

1. **The code from the slide**: the toolkit's code, in a notebook cell.
2. **The talk's demo**: runs offline in a second (a fake summariser, no API key).
3. **🧪 With Alex**: the same technique on Alex's real assistant, with a real model.

## What's here

| File | What it is |
|---|---|
| `03_context_management.ipynb` | **Start here.** Sections 1–9 like the talk |
| `checkpoint.py` | Catch-up file, generated from the notebook's code: `from checkpoint import *` loads everything up to a section |
| `life_tools.py` | Alex's read tools from week 2, plus `BINDER_TOOLS`: a careless tool whose big JSON outputs fill the desk |
| `agent_core.py` | The loop from weeks 1–2, plus a `before_call(conv, turn)` hook to measure and tidy the desk between steps |
| `providers.py`, `lifedb.py`, `simweek.py` | Same as week 2 |
| `solution/context_toolkit/` | The talk's companion code (`common.py`, `01`–`09`, each runnable with `python 0X_….py`) with the course fixes below. 29 offline tests in `solution/tests/`. **Homework reference: remove before sharing.** |

## Session plan (90 minutes, setup done at home)

| Time | Section | Slides | 🧪 With Alex |
|---|---|---|---|
| 0:00 | 0. Setup + shared helpers | | `%run ../check_setup.py` |
| 0:05 | 1. Token budget | 5, 11–12 | An 8-week review with a careless tool: the desk per zone, per step, and the ladder's action |
| 0:15 | 2. Sliding window | 13 | (in section 3) |
| 0:20 | 3. Compaction | 14 | Alex's week as a chat, 5 probe questions: keep everything / sliding window / compaction |
| 0:35 | 4. Tool output | 15 | The review again, with and without clearing old results (OpenAI items, from 08) |
| 0:50 | 5. Memory | 16 | A fresh conversation answers correctly only with the drawer |
| 1:00 | 8. The OpenAI API | 19–20 | Prompt caching (stable start vs a timestamp first); server-side and on-demand compaction |
| 1:10 | 9. Everything together | 18 | The talk's live demo: 40 contracts, overflow at step 13 without management |
| 1:15 | Takeaways | 20–22 | The one-minute version, six habits, homework |
| after | 6. Sub-agents, 7. Retrieval, poisoning, offloading run C (optional) | 7, 17 | Interns (a real model) per week of the review |

About 6–8 minutes of model time on `gpt-6-luna` in total; about **$0.01** per student.

## What students should see (from real runs)

| Section | Result |
|---|---|
| 1, talk demo | tool results 79% of the desk → COMPACT |
| 1, Alex | tool results are the largest zone; the ladder climbs OK → CLEAR → COMPACT → RESET; over 100% by the last steps |
| 3, Alex (5 probes) | keep everything 5/5 · sliding window ~3/5 · compaction 4–5/5 with roughly half the tokens |
| 4, talk demo | 213k tokens raw → 44k after clearing → 1.3k with offloading |
| 4, Alex | clearing: same 8 lookups and the same correct answer with ~40% fewer tokens (sometimes the model re-fetches cleared weeks: good discussion) |
| 5, Alex | "a call Thursday 7:45?": without memory *yes* · with memory *no, that's the school drop-off* (5/5 in tests) |
| 6, talk demo | one agent ~177k tokens · with sub-agents 308 |
| 8, Alex | stable prefix ~70% cached · timestamp first 0%, about twice the cost; server-side compaction 5/5; `responses.compact` ~1,130 → ~750 tokens |
| 9, talk demo | no management overflows at step 13 (peak ~120k) · clearing peaks at ~20k |

Model outputs vary between runs: the shape of the results is stable, the exact numbers are not.

## Course fixes to the toolkit

Found while testing with Alex and a real model. They are marked `# course fix` in the notebook and in
`solution/context_toolkit/`:

| File | Fix | Why |
|---|---|---|
| `04_tool_results.py` | `grep` (and `read_slice`) can't read outside `.tool_outputs/` | They are tools the **model** calls: `grep("../.env", "KEY")` read the API key |
| `04_tool_results.py` | `read_slice(handle, start, end)` added | The offload note already tells the model to use it |
| `05_memory.py` | Path guard uses `Path.is_relative_to` | `/memories/../memories_evil/x.md` was written outside the drawer |
| `05_memory.py` | `view` of a folder shows each note's content | With only file names, the model often stopped there and answered without the note (2/5 → 5/5) |
| `05_memory.py` | `"type": "string"` on `command`; an unknown command's error lists the valid ones | The model tried `command: "read"` |
| `03_compaction.py` | One closing line in `SUMMARY_PROMPT`: "Do NOT answer or continue the conversation" | A real model sometimes answered the transcript's last question instead of summarising, and every earlier fact was lost |

## Notes for the instructor

- This week runs on OpenAI only: the techniques edit OpenAI's list of conversation items. Claude has the same ideas
  built into its API (context editing, compaction).
- Students who fall behind: the checkpoint cell at the start of each section (`from checkpoint import *`).
- After a `git pull` during the course, restart the notebook's kernel: Python keeps the old modules in memory.
