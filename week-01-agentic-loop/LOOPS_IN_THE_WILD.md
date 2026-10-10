# Loops in the wild: Hermes Agent and OpenClaw

You wrote an agentic loop in about 35 lines. This document puts it next to the loops of two real, open-source agents
so you can see **what stays the same** and **what gets added** when an agent meets real users.

The code below is **condensed and simplified** to show the structure: names are real, details are removed.
Always read the original. Every link is pinned to the commit we studied, so the line numbers won't drift.

| Project | Language | Source we read |
|---|---|---|
| **Hermes Agent** (Nous Research, MIT) | Python | [`NousResearch/hermes-agent@4393341`](https://github.com/NousResearch/hermes-agent/tree/439334127f012e1ee0685acd5dba288e459af0ec) |
| **OpenClaw** (OpenClaw Foundation, MIT) | TypeScript | [`openclaw/openclaw@a754556`](https://github.com/openclaw/openclaw/tree/a75455653ba88b468cf2c8dfcb32357293f5a463) |
| **pi** (Mario Zechner, MIT): OpenClaw's loop was adapted from it | TypeScript | [`earendil-works/pi@d677d0e`](https://github.com/earendil-works/pi/tree/d677d0ee7134f834dfc163bf6bdb395df9e57c6b) |

---

## 0. Our loop: the invariant

```python
messages = [user_task]
for turn in range(max_turns):
    reply = model(messages, tools)
    messages.append(reply)                       # whole reply, append-only
    if reply.stop_reason != "tool_use":
        return reply.text                        # model decided it's done
    messages.append(run_all(reply.tool_calls))   # results go back as one message
return "stopped: out of turns"
```

Three things make this an **agent** rather than a workflow:
1. **The model chooses the control flow**: which tool, with what arguments, and when to stop.
2. **The environment answers back**: tool results (including errors) become the model's next input.
3. **The loop has no fixed length**: it runs until the model is done or *we* cut it off.

Keep this in mind. Everything below is this same loop with protection added around it.

---

## 1. Hermes Agent (Python)

**Where:** [`agent/conversation_loop.py` L1636–1686](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/conversation_loop.py#L1636-L1686)

```python
# condensed
while (api_calls < agent.max_iterations and agent.iteration_budget.remaining > 0) \
        or agent._budget_grace_call:
    begin_iteration(...)          # interrupt checks, budget accounting
    prepare_iteration(...)        # e.g. budget warnings
    assemble_api_request(...)
    gate = run_preflight_gate(...)            # context too big? compress first
    if gate.action == "continue": continue
    early = run_api_retry_loop(...)           # retries, rate limits, provider fallback
    if early: return early
    normalize_model_response(...)
    verdict = run_tool_round(...) if assistant_message.tool_calls \
              else finish_text_response(...)
    if verdict.action == "return": return verdict.result
    if verdict.action == "break":  break
result = finalize_turn(...)
```

**Same as ours:** call model → tool calls? run them and continue : finish.

**What Hermes adds, and why:**

| Feature | Where | Problem it solves |
|---|---|---|
| **Two stop conditions**: `max_iterations` *and* a shared `IterationBudget` | [`agent/iteration_budget.py`](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/iteration_budget.py) | Subagents spend from their own budget. `execute_code` turns are *refunded* so batching work into code isn't penalised. |
| **Budget warning** appended to the newest tool result | [`agent/turn_iteration_prep.py` L48](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/turn_iteration_prep.py#L48) | Lets the model wrap up *before* it is cut off (compare your `max_turns=2` experiment). |
| **Wall-clock budget**: wrap-up notice at 80% | [`agent/conversation_loop.py` L122](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/conversation_loop.py#L122) | Turn counts don't measure time. Some turns take minutes. |
| **Preflight gate**: compress context before the call | [`agent/turn_preflight_gate.py`](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/turn_preflight_gate.py) | The growing-history problem from Part 6 of the notebook. |
| **Invalid tool names are answered with an error result**, not executed | [`agent/turn_tool_round.py` L46+](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/turn_tool_round.py#L46) | Same idea as our `Unknown tool` result: every call needs a matching result. |
| **Persist before execute**: the tool call is saved to the session DB *before* the tool runs | same file | If a destructive tool crashes the process, a resumed session knows what was already attempted. |
| **Concurrent tools**, up to 8 worker threads per batch | [`agent/tool_executor.py` L129](https://github.com/NousResearch/hermes-agent/blob/439334127f012e1ee0685acd5dba288e459af0ec/agent/tool_executor.py#L129) | Parallel tool calls in one reply are independent, so run them at once. |
| **Phases return a verdict** (`continue` / `break` / `return`) | whole loop | Keeps a ~1,800-line module navigable. Each phase is testable on its own. |

**Message format note:** Hermes talks to many providers, so internally it uses the OpenAI-style shape
(`assistant.tool_calls` + `role: "tool"` messages) and adapts per provider. We used Anthropic's native shape
(`tool_use` / `tool_result` blocks). The loop is identical; only the envelope differs.

---

## 2. OpenClaw (TypeScript), and pi before it

OpenClaw has **two loops nested inside each other**, plus an outer runner.

### 2a. The inner/outer loop pair: pi's design

**Where (pi, the cleaner version):** [`packages/agent/src/agent-loop.ts` L163+](https://github.com/earendil-works/pi/blob/d677d0ee7134f834dfc163bf6bdb395df9e57c6b/packages/agent/src/agent-loop.ts#L163)

```ts
// condensed
let pending = await config.getSteeringMessages?.() ?? [];   // user typed while we were busy?
while (true) {                                              // OUTER: follow-up messages
  let hasMoreToolCalls = true;
  while (hasMoreToolCalls || pending.length > 0) {          // INNER: tool calls + steering
    inject(pending); pending = [];
    const message = await streamAssistantResponse(context, config, signal, emit);
    if (message.stopReason === "error" || message.stopReason === "aborted") return;

    const toolCalls = message.content.filter(c => c.type === "toolCall");
    hasMoreToolCalls = false;
    if (toolCalls.length > 0) {
      const batch = message.stopReason === "length"
        ? await failToolCallsFromTruncatedMessage(toolCalls)   // don't run cut-off args!
        : await executeToolCalls(context, message, config, signal, emit);
      hasMoreToolCalls = !batch.terminate;
    }
    pending = await config.getSteeringMessages?.() ?? [];
  }
  pending = await config.getFollowUpMessages?.() ?? [];
  if (pending.length === 0) break;
}
```

**Two ideas we don't have yet:**

- **Steering**: the user can type *while the agent works*. The message is queued and injected between turns,
  so the human can redirect mid-task without killing the run.
- **Follow-ups**: when the agent would stop, check whether more work was queued. If so, keep going.

Notice the `stopReason === "length"` branch (pi's name for `max_tokens`). It's exactly the rule in our loop:
**never execute a tool call whose arguments may be truncated.**

pi also emits **events** (`turn_start`, `message_start`, `message_end`, `turn_end`, `agent_end`).
The loop doesn't print anything; a TUI, a web UI or a logger subscribes to the events. Compare that with our `trace_response`.

### 2b. OpenClaw's version: same skeleton, more armour

**Where:** [`packages/agent-core/src/agent-loop.ts` L130–445](https://github.com/openclaw/openclaw/blob/a75455653ba88b468cf2c8dfcb32357293f5a463/packages/agent-core/src/agent-loop.ts#L130-L445)
(the `while (true)` at L205 and `while (hasMoreToolCalls || pendingMessages.length > 0)` at L208)

| Feature | Problem it solves |
|---|---|
| `stopIfAborted()` checked at almost every step, and an *aborted* message is persisted | The user hits Stop. The transcript must not end on a dangling tool call that can't be continued. |
| Tools can start **while the reply is still streaming** (`streamed.executedIds`) | Latency: don't wait for the full reply before starting a slow tool. |
| **Tool-loop detection** (`criticalToolLoopSeen`, `terminateRun`) | The model calls the same tool with the same args again and again. Detect it and end the run with a clear message. |
| **Turn taint**: [`turn-taint.ts` L24](https://github.com/openclaw/openclaw/blob/a75455653ba88b468cf2c8dfcb32357293f5a463/packages/agent-core/src/turn-taint.ts#L24) marks a turn once a tool result came from the **network** | Prompt injection: a web page can contain "ignore your instructions and…". Once tainted, the system can restrict what happens next. |
| Hooks: `prepareNextTurn` (swap model / thinking level / context), `shouldStopAfterTurn`, `beforeToolCall` / `afterToolCall` | The loop stays generic. Permissions, compaction and model routing plug in from outside. |

### 2c. And around it: the run loop

[`src/agents/embedded-agent-runner/run-loop.ts` L242](https://github.com/openclaw/openclaw/blob/a75455653ba88b468cf2c8dfcb32357293f5a463/src/agents/embedded-agent-runner/run-loop.ts#L242) wraps the agent loop in **another** `while (true)`
with a retry budget, model **failover** (auth failures, rate limits) and **compaction** recovery.
So in production there are three layers:

```
run loop      (retries, failover, compaction)      ← infrastructure failures
  outer loop  (follow-up messages)                 ← more work arrived
    inner loop (tool calls + steering)             ← the agentic loop you wrote
```

---

## 3. Side by side

| Question | Our loop | Hermes | OpenClaw / pi |
|---|---|---|---|
| What ends a run? | `end_turn`, `max_turns`, `max_tokens`, `refusal` | model done, iteration budget, wall-clock budget, interrupt, compression failure | model done, abort, hook says stop, loop detector, provider error |
| Who can talk mid-run? | nobody | user interrupt + redirect | steering queue (between turns), follow-up queue (after) |
| Tool errors | `is_error` result | error result; invalid names answered, not executed | error result; truncated calls failed; `before/afterToolCall` hooks |
| Parallel tools | sequential, results in one message | thread pool (≤ 8) | parallel or sequential per config; can start during streaming |
| Context growth | ignored | preflight compression | `prepareNextTurn` / compaction in the run loop |
| Crash safety | none | persist tool call before executing | persisted aborted message, event stream |
| Output | `print` | callbacks / display layer | typed events |
| Size | ~35 lines | ~1,800 lines + phase modules | ~940 (pi) / ~1,450 (OpenClaw) + run loop |

---

## 4. Why this counts

- **The core is the same everywhere.** Strip any production agent down to what must be there and you get your 35 lines.
  Learning frameworks later is easy once you know which part is the loop and which part is armour.
- **Every extra line is a failure someone hit.** Runaway costs → budgets. Users clicking Stop → abort handling.
  Prompt injection from the web → taint. Huge histories → compaction. Reading production loops is reading a list of incidents.
- **The decisions you made today are the same ones they made.** Return errors to the model? Run truncated tool calls?
  Cap the turns? Warn before the cap? Those are design questions, not framework features.
- **"Agentic" is a property of control flow, not of the library.** If the model decides the next step and the loop feeds results back
  until the model is done, it's an agent, whether it's 35 lines or 3,500.

---

## 5. Exercises for discussion

1. Open Hermes' `run_tool_round`. Find the line that persists the tool call. Why **before** execution and not after?
2. In pi, find `failToolCallsFromTruncatedMessage`. What would happen if a `write_file` call with half its `content` were executed?
3. Design a steering queue for our notebook loop. Where exactly in `run_agent` would you check it? What if a message arrives while a tool runs?
4. OpenClaw's loop detector ends the run. Hermes warns the model about its budget. When is each approach better?
5. Pick **one** feature from this document and add it to your module-based agent (homework 8.3 counts).
