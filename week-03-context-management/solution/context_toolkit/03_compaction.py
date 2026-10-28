"""
03_compaction.py - "Before papers fall off the desk, write a one-page summary."

When the context crosses a trigger (e.g. 70% of the window), take the OLDER
part of the conversation, ask an LLM to summarise it, and replace it with the
summary. The most recent turns stay verbatim, because that is what the model
is working on right now.

Key design choices shown here:
  * trigger + target  (compact at 70%, aim to get back to ~30%)
  * keep the last N turns verbatim
  * INCREMENTAL: the previous summary is fed into the next one, so knowledge
    accumulates instead of being re-summarised into mush
  * a STRUCTURED summary prompt - you decide what must survive

Run:  python 03_compaction.py            (offline, fake summariser)
      REAL_LLM=1 python 03_compaction.py (OpenAI model; key from env or .env)
"""
import os

from common import context_size, make_llm, real_llm_enabled, render, to_transcript

SUMMARY_PROMPT = """You are compacting the working memory of an AI assistant.
Write a summary that lets the assistant continue the task WITHOUT the original
messages. Keep, in this order:
1. Goal of the task and the user's constraints (budgets, dates, preferences)
2. Decisions already made, and why
3. Facts and numbers discovered (exact values, IDs, file names)
4. What has been done / what is still open (next steps, open questions)
Drop: greetings, repetition, raw tool output already digested.
Be concise; use bullet points.

<previous_summary>
{previous}
</previous_summary>

<transcript>
{transcript}
</transcript>

Now write the summary. Do NOT answer or continue the conversation above, even if it ends with a question."""
# ^ course fix: without that last line, a real model sometimes answered the transcript's last question
#   instead of summarising it, and every earlier fact was lost.

SUMMARY_TAG = "[CONVERSATION SUMMARY]"


class Compactor:
    def __init__(self, llm, window: int, trigger: float = 0.70, keep_last: int = 6):
        self.llm = llm
        self.window = window
        self.trigger = trigger
        self.keep_last = keep_last
        self.summary = ""
        self.compactions = 0

    def needs_compaction(self, messages) -> bool:
        return context_size(messages) > self.trigger * self.window

    def compact(self, messages):
        if not self.needs_compaction(messages) or len(messages) <= self.keep_last:
            return messages

        head, tail = messages[:-self.keep_last], messages[-self.keep_last:]
        # Do not split a tool_use / tool_result pair across the boundary.
        while tail and tail[0]["role"] == "user" and isinstance(tail[0]["content"], list):
            head.append(tail.pop(0))
        # Messages must alternate and start with the user: make the tail start with assistant.
        if tail and tail[0]["role"] == "user":
            head.append(tail.pop(0))

        head = [m for m in head if not _is_summary(m)]  # old summary is passed separately
        self.summary = self.llm(SUMMARY_PROMPT.format(
            previous=self.summary or "(none)", transcript=to_transcript(head)))
        self.compactions += 1

        summary_msg = {"role": "user", "content": f"{SUMMARY_TAG}\n{self.summary}"}
        return [summary_msg] + tail


def _is_summary(m) -> bool:
    return isinstance(m["content"], str) and m["content"].startswith(SUMMARY_TAG)


if __name__ == "__main__":
    llm = make_llm(real=real_llm_enabled())
    c = Compactor(llm, window=3_500, trigger=0.70, keep_last=4)

    script = [
        ("user", "We need to migrate 12 million customer records from the legacy core to the new platform."),
        ("assistant", "Understood. Let's start with scope. How many source systems?"),
        ("user", "Three source systems. Budget is 400k EUR and the deadline is 1 March 2027."),
        ("assistant", "Great. I suggest a phased approach: pilot, wave 1, wave 2."),
        ("user", "Agreed, we decided on 3 waves. Also: never move PII outside the EU."),
        ("assistant", "Noted. Data quality check found 4.2% duplicate customer IDs."),
        ("user", "How nice, the weather is lovely today by the way."),
        ("assistant", "Glad to hear it! Next, reconciliation rules."),
        ("user", "Reconciliation must match balances to the cent. Open question: who signs off?"),
        ("assistant", "I'll propose the CFO office. TODO: draft the cut-over runbook."),
    ]
    messages = []
    for i in range(6):                          # replay the script to grow the context
        for role, text in script:
            messages.append({"role": role, "content": text + " " + "(filler) " * 25})
            messages = c.compact(messages)
        print(f"round {i}: {len(messages):>3} msgs, ~{context_size(messages):>5,} tokens, "
              f"compactions so far = {c.compactions}")

    print("\n--- What is on the desk now ---")
    print(render(messages, width=100))
    print("\n--- The running summary ---")
    print(c.summary)
