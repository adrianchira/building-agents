# Context Management Toolkit — talk companion code

Small, dependency-free Python examples for a 1-hour talk on context management
for chatbots and agents. Every script runs offline (a deterministic fake
summariser stands in for the LLM). Set `REAL_LLM=1` and `OPENAI_API_KEY`
to use an OpenAI model for the summarisation steps (`pip install openai`;
default `gpt-6-luna`, override with `OPENAI_SUMMARY_MODEL`).
These settings can live in a `.env` file in this folder or any folder above it
(`OPENAI_API_KEY=...`, `REAL_LLM=1`); `common.py` reads it, no extra package needed.

| File | Desk analogy | Technique | For |
|---|---|---|---|
| `common.py` | — | token counting, fake/real LLM, message helpers | all |
| `01_token_budget.py` | measure the desk | budget zones, pressure level → action | both |
| `02_sliding_window.py` | keep the newest papers, pin the brief | token-based trimming, safe tool-pair cuts | chatbots |
| `03_compaction.py` | one-page summary before papers fall | incremental, structured summarisation | both |
| `04_tool_results.py` | sticky note instead of the binder | offload big outputs + clear old tool results | agents |
| `05_memory.py` | the drawer | file-backed memory tool, relevance-based injection | both |
| `06_subagents.py` | send an intern to the archive | isolated sub-agent contexts, return budget | agents |
| `07_retrieval.py` | bring 3 pages, not the library | BM25 retrieval, just-in-time search tool | both |
| `08_openai_native.py` | the office does part of it for you | OpenAI Responses API: server-side compaction, `responses.compact`, prompt caching, plus our clearing + memory as function tools | agents |
| `09_context_manager.py` | all together | layered escalation ladder + live ASCII demo | agents |

```bash
python 01_token_budget.py
python 09_context_manager.py      # best live demo: watch the desk overflow
```

Notes
- Token counts use a ~4 chars/token estimate. Use your provider's counter in production.
- `08` uses the OpenAI Responses API as documented in October 2026
  (`context_management=[{"type": "compaction", "compact_threshold": ...}]`,
  `client.responses.compact`). Agent model defaults to `gpt-6.1-sol`; override with
  `OPENAI_MODEL`. Check developers.openai.com before relying on the names.

Course fixes (week 3 of the building-agents course), marked `# course fix` in the code:
- `04_tool_results.py`: `grep` (and the new `read_slice`) can't read outside `.tool_outputs/`. They are tools the
  model calls, so without the check `grep("../.env", "KEY")` would read your API key.
- `04_tool_results.py`: `read_slice(handle, start, end)` added; the offload note already tells the model to use it.
- `05_memory.py`: the path guard uses `Path.is_relative_to`, so `../memories_evil/...` can't escape the drawer either.
- `03_compaction.py`: one closing line in `SUMMARY_PROMPT` ("Do NOT answer or continue the conversation"): with a real
  model, the summary sometimes answered the transcript's last question instead, and all earlier facts were lost.
- `05_memory.py`: `view` of a folder shows each note's content (the model often stopped at the file names); the
  `command` field has `"type": "string"`; an unknown command's error lists the valid ones (the model tried `read`).
