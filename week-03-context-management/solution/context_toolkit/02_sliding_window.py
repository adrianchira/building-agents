"""
02_sliding_window.py - "Keep the latest papers on the desk, and pin the brief."

The simplest strategy: keep only the most recent messages that fit a token
budget. Two details make it production-safe:

  1. PIN the things that must never fall off (the original task / brief).
  2. Never cut between a tool call and its result - the API rejects a
     tool_result whose tool_use is missing, and the model gets confused.

Good for: chatbots with short-lived topics.  Bad for: long tasks where an
early decision matters later (use compaction or memory for those).

Run:  python 02_sliding_window.py
"""
from common import context_size, count_tokens, render


def _starts_with_orphan_tool_result(msg) -> bool:
    c = msg["content"]
    return msg["role"] == "user" and isinstance(c, list) and any(
        b.get("type") == "tool_result" for b in c
    )


def sliding_window(messages, budget_tokens: int, pin_first: int = 1):
    """Return pinned head + the newest messages that fit in budget_tokens."""
    pinned = messages[:pin_first]
    budget = budget_tokens - sum(count_tokens(m) for m in pinned)

    kept = []
    for msg in reversed(messages[pin_first:]):
        cost = count_tokens(msg)
        if cost > budget:
            break
        kept.insert(0, msg)
        budget -= cost

    # Pairing rule: drop leading tool_results whose tool_use fell off the desk.
    while kept and _starts_with_orphan_tool_result(kept[0]):
        kept.pop(0)
    # Roles must alternate: the first kept message after the pin should be
    # an assistant turn if the pin ends with a user turn.
    while kept and pinned and kept[0]["role"] == pinned[-1]["role"]:
        kept.pop(0)

    dropped = len(messages) - len(pinned) - len(kept)
    if dropped:
        # Tell the model something is missing - silent gaps cause confusion.
        note = {"role": "assistant",
                "content": f"[{dropped} earlier messages were removed to save space]"}
        if kept and kept[0]["role"] == "assistant":
            kept[0] = {"role": "assistant",
                       "content": note["content"] + "\n" + _text(kept[0])}
        else:
            kept.insert(0, note)
    return pinned + kept


def _text(msg) -> str:
    c = msg["content"]
    return c if isinstance(c, str) else " ".join(b.get("text", "") for b in c)


if __name__ == "__main__":
    convo = [{"role": "user", "content": "BRIEF: Plan a data migration for a retail bank. Budget 400k EUR, go-live 1 March."}]
    for i in range(1, 30):
        convo.append({"role": "assistant", "content": f"Step {i}: analysis of workstream {i}. " + "detail " * 40})
        convo.append({"role": "user", "content": f"Thanks, continue with point {i + 1}."})

    print(f"Full history : {len(convo)} messages, ~{context_size(convo):,} tokens")
    trimmed = sliding_window(convo, budget_tokens=2_000)
    print(f"After window : {len(trimmed)} messages, ~{context_size(trimmed):,} tokens\n")
    print(render(trimmed, width=80))
    print("\nNotice: the BRIEF survived (pinned); steps 1..N silently would have vanished,")
    print("so we leave a marker. Anything decided in the middle is gone -> see 03_compaction.")
