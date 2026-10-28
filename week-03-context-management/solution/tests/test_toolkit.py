"""The talk's context_toolkit, tested offline (fake_llm, no API key)."""

import copy
import importlib
import json
from types import SimpleNamespace as NS

import pytest

from common import context_size, count_tokens, fake_llm

budget = importlib.import_module("01_token_budget")
window = importlib.import_module("02_sliding_window")
compaction = importlib.import_module("03_compaction")
tool_results = importlib.import_module("04_tool_results")
memory = importlib.import_module("05_memory")
subagents = importlib.import_module("06_subagents")
retrieval = importlib.import_module("07_retrieval")
native = importlib.import_module("08_openai_native")
manager = importlib.import_module("09_context_manager")


def user(text):
    return {"role": "user", "content": text}


def assistant(text):
    return {"role": "assistant", "content": text}


def tool_use(i, name="run_sql"):
    return {"role": "assistant", "content": [{"type": "tool_use", "id": i, "name": name, "input": {}}]}


def tool_result(i, body):
    return {"role": "user", "content": [{"type": "tool_result", "tool_use_id": i, "content": body}]}


# ---------- 01 token budget ----------

@pytest.mark.parametrize("used, word", [(10, "OK"), (49, "OK"), (50, "CLEAR"), (69, "CLEAR"),
                                        (70, "COMPACT"), (84, "COMPACT"), (85, "RESET"), (120, "RESET")])
def test_ladder_thresholds(used, word):
    b = budget.ContextBudget(window=110, reserve_output=10)
    b.zones["history"] = used
    assert b.action().startswith(word)


def test_budget_report_shows_zones_and_pressure():
    b = budget.ContextBudget(window=10_000, reserve_output=1_000)
    b.add("tool_results", "x" * 20_000)
    b.add("history", "y" * 4_000)
    assert b.used == 6_000 and b.free == 3_000
    assert "tool_results" in b.report().splitlines()[1]            # biggest zone first


# ---------- 02 sliding window ----------

def test_window_pins_brief_marks_gap_and_keeps_newest():
    convo = [user("BRIEF")]
    for i in range(20):
        convo += [assistant(f"step {i} " + "x" * 200), user(f"go on {i}")]
    out = window.sliding_window(convo, budget_tokens=300)
    assert out[0]["content"] == "BRIEF"
    assert out[1]["role"] == "assistant" and "earlier messages were removed" in out[1]["content"]
    assert out[-1] == convo[-1]
    assert context_size(out) < context_size(convo)


def test_window_never_starts_with_an_orphan_tool_result():
    convo = [user("BRIEF"), tool_use("t1"), tool_result("t1", "z" * 2_000), assistant("done"), user("next")]
    out = window.sliding_window(convo, budget_tokens=60)
    assert not any(window._starts_with_orphan_tool_result(m) for m in out[1:2])


# ---------- 03 compaction ----------

def test_compaction_keeps_tail_and_is_incremental():
    prompts = []
    def llm(prompt):
        prompts.append(prompt)
        return f"summary {len(prompts)}"
    c = compaction.Compactor(llm, window=200, trigger=0.5, keep_last=4)
    msgs = [user("u0 " + "x" * 120)] + [m for i in range(1, 6) for m in (assistant(f"a{i} " + "x" * 120), user(f"u{i} " + "x" * 120))]
    out = c.compact(msgs)
    assert out[0]["content"].startswith(compaction.SUMMARY_TAG) and out[-1] == msgs[-1]
    assert out[1]["role"] == "assistant"                             # the tail starts with the assistant
    more = out + [assistant("a6 " + "x" * 120), user("u6 " + "x" * 120)]
    c.compact(more)
    assert "<previous_summary>\nsummary 1\n</previous_summary>" in prompts[1]
    assert compaction.SUMMARY_TAG not in prompts[1].split("<transcript>")[1]   # old summary passed separately


def test_compaction_waits_for_the_trigger():
    c = compaction.Compactor(lambda p: pytest.fail("no model call expected"), window=100_000)
    msgs = [user("hi"), assistant("hello")]
    assert c.compact(msgs) == msgs and c.compactions == 0


# ---------- 04 tool results ----------

def test_offload_preview_grep_and_read_slice():
    out = "\n".join(json.dumps({"id": i, "status": "MISMATCH" if i % 97 == 0 else "OK"}) for i in range(2_000))
    note = tool_results.offload_if_large("run_sql", out, max_tokens=100)
    handle = note.split("Saved as '")[1].split("'")[0]
    assert count_tokens(note) < 200 and "read_slice" in note
    assert tool_results.grep(handle, "MISMATCH", limit=3).count("\n") == 3          # 3 hits + "... N more"
    assert tool_results.read_slice(handle, 2, 3).splitlines()[0].startswith('2: {"id": 1')


def test_small_outputs_are_not_offloaded():
    assert tool_results.offload_if_large("t", "short") == "short"


@pytest.mark.parametrize("handle", ["../secret.env", "../../.env", "sub/../../x"])
def test_grep_cannot_leave_the_store(tmp_path, handle):          # course fix
    (tmp_path / "secret.env").write_text("OPENAI_API_KEY=sk-proj-NOT-REAL")
    tool_results.STORE.mkdir(exist_ok=True)
    with pytest.raises(ValueError):
        tool_results.grep(handle, "KEY")


def test_clear_keeps_newest_and_never_memory():
    msgs = [user("task")]
    for i, name in enumerate(["run_sql", "memory", "run_sql", "run_sql", "run_sql"]):
        msgs += [tool_use(f"t{i}", name), tool_result(f"t{i}", f"body {i} " + "x" * 100)]
    freed = tool_results.clear_old_tool_results(msgs, keep=2)
    bodies = [m["content"][0]["content"] for m in msgs if m["role"] == "user" and isinstance(m["content"], list)]
    assert bodies[0] == tool_results.PLACEHOLDER and bodies[2] == tool_results.PLACEHOLDER
    assert bodies[1].startswith("body 1")                         # memory is never cleared
    assert bodies[3].startswith("body 3") and bodies[4].startswith("body 4")
    assert freed > 0 and tool_results.clear_old_tool_results(msgs, keep=2) == 0


# ---------- 05 memory ----------

def test_memory_sessions_and_relevance():
    m = memory.FileMemory("./memories")
    assert "empty" in m.handle({"command": "view", "path": "/memories"})
    m.handle({"command": "write", "path": "/memories/family.md", "text": "Partner away Wednesday and Thursday"})
    m.handle({"command": "append", "path": "/memories/family.md", "text": "School drop-off at 8:00"})
    assert m.handle({"command": "view", "path": "/memories"}).startswith("## family.md\nPartner away")  # course fix
    assert "drop-off" in m.handle({"command": "view", "path": "/memories/family.md"})
    assert "family.md" in m.handle({"command": "search", "query": "partner"})
    assert "drop-off" in memory.load_relevant_memories(m, "Who does the school drop-off?")


@pytest.mark.parametrize("path", ["/memories/../../etc/passwd", "/memories/../memories_evil/x.md"])
def test_memory_path_guard(tmp_path, path):                       # course fix: the second one used to escape
    (tmp_path / "memories_evil").mkdir()
    m = memory.FileMemory("./memories")
    assert m.handle({"command": "write", "path": path, "text": "x"}).startswith("Error")
    assert not (tmp_path / "memories_evil" / "x.md").exists()


def test_memory_errors_go_back_to_the_model_and_say_what_to_do():
    msg = memory.FileMemory("./memories").handle({"command": "read"})
    assert msg.startswith("Error") and "view" in msg                       # course fix


def test_summary_prompt_tells_the_model_not_to_answer():
    assert compaction.SUMMARY_PROMPT.rstrip().endswith("even if it ends with a question.")


# ---------- 06 sub-agents, 07 retrieval ----------

def test_subagent_returns_a_small_page():
    r = subagents.run_subagent("find late rows", "payments_2024")
    tokens = r.pop("_subagent_context_tokens")
    assert tokens > 10_000 and count_tokens(json.dumps(r)) <= subagents.RETURN_BUDGET


def test_bm25_finds_the_breach_article():
    assert retrieval.BM25(retrieval.DOCS).search("hours to notify a personal data breach", k=1) == ["gdpr_art33.md"]


# ---------- 08 OpenAI items ----------

def test_clear_old_function_outputs_on_responses_items():
    items = [{"type": "message", "role": "user", "content": "task"}]
    for i, name in enumerate(["read_file", "memory", "read_file", "read_file"]):
        items += [{"type": "function_call", "call_id": f"c{i}", "name": name, "arguments": "{}"},
                  {"type": "function_call_output", "call_id": f"c{i}", "output": f"out {i}"}]
    native.clear_old_function_outputs(items, keep=1)
    outs = [i["output"] for i in items if i["type"] == "function_call_output"]
    assert outs == [native.CLEARED, "out 1", native.CLEARED, "out 3"]


def test_drop_before_last_compaction():
    items = [{"type": "message"}, {"type": "compaction"}, {"type": "message"}, {"type": "compaction"}, {"type": "x"}]
    assert native.drop_before_last_compaction(items) == items[3:]


# ---------- 09 the ladder ----------

def test_layered_manager_keeps_the_desk_under_the_window():
    sizes_none, overflow_none, _ = manager.simulate("none", steps=20, window=20_000)
    sizes_layered, overflow_layered, cm = manager.simulate("layered", steps=20, window=20_000)
    assert overflow_none is not None and overflow_layered is None
    assert max(sizes_layered) < 20_000 and any(l.startswith("clear") for l in cm.log)
