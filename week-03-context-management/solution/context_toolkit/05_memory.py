"""
05_memory.py - "The drawer next to the desk."

Memory = notes the model writes OUTSIDE the context window and reads back
when it needs them. It survives compaction, resets and new sessions.

Two flavours, both shown here:
  * Scratchpad / progress file  - the agent's own NOTES.md for a long task
  * Long-term user memory       - small facts about the user, loaded by
                                  relevance at the start of a conversation

The memory is exposed to the model as a TOOL (view / write / search), so the
model decides what is worth writing down. 08_openai_native.py registers
it as an OpenAI function tool and routes the calls to this handler.

Run:  python 05_memory.py
"""
import json
from pathlib import Path

from common import count_tokens

MEMORY_TOOL_SCHEMA = {
    "name": "memory",
    "description": (
        "Your persistent notes. ALWAYS view /memories at the start of a task. "
        "Write down decisions, progress and facts you will need later - your "
        "context may be reset at any moment. Keep files short and organised."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "enum": ["view", "write", "append", "search", "delete"]},  # course fix: type
            "path": {"type": "string"},
            "text": {"type": "string"},
            "query": {"type": "string"},
        },
        "required": ["command"],
    },
}


class FileMemory:
    """Client-side backend. The model calls it through the tool above."""

    def __init__(self, root="./memories", max_file_tokens=2_000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_tokens = max_file_tokens

    def _path(self, p: str) -> Path:
        rel = p.removeprefix("/memories").lstrip("/") or "."
        full = (self.root / rel).resolve()
        if not full.is_relative_to(self.root):  # course fix: block ../../etc/passwd AND ../memories_evil
            raise ValueError("path escapes memory directory")
        return full

    def handle(self, cmd: dict) -> str:
        try:
            c = cmd["command"]
            if c == "view":
                p = self._path(cmd.get("path", "/memories"))
                if p.is_dir():   # course fix: show each note's content, not just its name (the model
                                 # often stopped at the list of names and never opened the note)
                    notes = [f"## {x.name}\n{x.read_text()}" for x in sorted(p.iterdir()) if x.is_file()]
                    return "\n\n".join(notes) or "(empty - nothing remembered yet)"
                return p.read_text()
            if c in ("write", "append"):
                p = self._path(cmd["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                new = (p.read_text() + "\n" if c == "append" and p.exists() else "") + cmd["text"]
                if count_tokens(new) > self.max_file_tokens:
                    return "Error: file too long - summarise it before writing more."
                p.write_text(new)
                return f"Saved {cmd['path']} ({count_tokens(new)} tokens)"
            if c == "search":
                q = cmd["query"].lower()
                hits = [f"{f.name}: {line.strip()}"
                        for f in self.root.rglob("*.md")
                        for line in f.read_text().splitlines() if q in line.lower()]
                return "\n".join(hits[:20]) or "no matches"
            if c == "delete":
                self._path(cmd["path"]).unlink()
                return f"Deleted {cmd['path']}"
            return (f"Error: unknown command {c}. Commands: view (a folder, or a file to read it), "   # course fix:
                    "write, append, search, delete.")                                                   # say what to do
        except Exception as e:  # errors go back to the model, not up the stack
            return f"Error: {e}"


def load_relevant_memories(memory: FileMemory, user_message: str, budget_tokens=400) -> str:
    """For chatbots: inject only memories that match the new message."""
    words = {w.strip(".,?!").lower() for w in user_message.split() if len(w) > 3}
    scored = []
    for f in memory.root.rglob("*.md"):
        for line in f.read_text().splitlines():
            score = sum(w in line.lower() for w in words)
            if score:
                scored.append((score, line.strip()))
    out, used = [], 0
    for _, line in sorted(scored, reverse=True):
        if used + count_tokens(line) > budget_tokens:
            break
        out.append(line)
        used += count_tokens(line)
    return "\n".join(out)


if __name__ == "__main__":
    mem = FileMemory("./memories_demo")

    # --- Session 1: the agent works and takes notes (these would be tool calls) ---
    for call in [
        {"command": "view", "path": "/memories"},
        {"command": "write", "path": "/memories/progress.md",
         "text": "# Migration task\n- [x] Wave 1 mapped (customers, accounts)\n- [ ] Wave 2: loans, cards"},
        {"command": "write", "path": "/memories/decisions.md",
         "text": "- Decided: 3 migration waves\n- Constraint: PII never leaves the EU\n- Budget: 400k EUR"},
        {"command": "write", "path": "/memories/user.md",
         "text": "- User prefers answers in bullet points\n- User's go-live date: 1 March 2027"},
    ]:
        print(f"memory.{call['command']:<6} -> {mem.handle(call)}")

    # --- Session 2: fresh context window, empty desk. Open the drawer first. ---
    print("\n=== New session, empty context ===")
    print(mem.handle({"command": "view", "path": "/memories"}))
    print(mem.handle({"command": "view", "path": "/memories/progress.md"}))

    # --- Chatbot pattern: inject only what is relevant to the new question ---
    q = "What was the budget we agreed for the migration?"
    print(f"\nUser asks: {q}\nInjected memory:\n{load_relevant_memories(mem, q)}")

    # security check
    print("\nPath traversal attempt ->", mem.handle({"command": "view", "path": "/memories/../../etc/passwd"}))
    print("\nTool schema to give the model:\n", json.dumps(MEMORY_TOOL_SCHEMA, indent=2)[:300], "...")
