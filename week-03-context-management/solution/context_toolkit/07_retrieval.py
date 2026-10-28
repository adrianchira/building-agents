"""
07_retrieval.py - "Don't bring the whole library to the desk. Bring the
three pages you need, and know where the rest is."

Two ways to get knowledge into context:
  * Up-front (RAG): before the model runs, retrieve the top-k chunks.
  * Just-in-time: give the model a search tool and let it pull what it needs,
    when it needs it (how coding agents use grep/glob instead of reading
    the whole repo).

This is a tiny BM25 search in pure Python - swap it for embeddings / a vector
DB in production. The context-management idea is the same.

Run:  python 07_retrieval.py
"""
import math
import re
from collections import Counter

from common import count_tokens

DOCS = {
    "gdpr_art17.md": "Right to erasure. The data subject has the right to obtain erasure of personal data without undue delay.",
    "gdpr_art33.md": "Breach notification. The controller notifies the supervisory authority within 72 hours of becoming aware of a personal data breach.",
    "gdpr_art35.md": "A data protection impact assessment (DPIA) is required where processing is likely to result in a high risk.",
    "aiact_art50.md": "Transparency: providers ensure people are informed that they are interacting with an AI system.",
    "migration_runbook.md": "Cut-over weekend: freeze legacy writes Friday 18:00, reconcile balances, go/no-go Sunday 12:00.",
    "hr_policy.md": "Employees accrue 21 days of annual leave. Meal vouchers are granted per worked day.",
} | {f"filler_{i}.md": "Unrelated corporate text about office plants and parking. " * 30 for i in range(40)}


def tokenize(t: str):
    return re.findall(r"[a-z0-9]+", t.lower())


class BM25:
    def __init__(self, docs: dict, k1=1.5, b=0.75):
        self.names = list(docs)
        self.toks = [tokenize(docs[n]) for n in self.names]
        self.avg = sum(map(len, self.toks)) / len(self.toks)
        df = Counter(w for d in self.toks for w in set(d))
        n = len(self.toks)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b

    def search(self, query: str, k=3):
        q = tokenize(query)
        scores = []
        for name, d in zip(self.names, self.toks):
            tf = Counter(d)
            s = sum(self.idf.get(w, 0) * tf[w] * (self.k1 + 1) /
                    (tf[w] + self.k1 * (1 - self.b + self.b * len(d) / self.avg)) for w in q)
            scores.append((s, name))
        return [n for s, n in sorted(scores, reverse=True)[:k] if s > 0]


# Just-in-time: this is the tool definition you would hand the model.
SEARCH_TOOL = {
    "name": "search_docs",
    "description": "Search the policy library. Returns file names and first line. "
                   "Call read_doc(name) only for the files you really need.",
    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}

if __name__ == "__main__":
    question = "How many hours do we have to notify a personal data breach?"
    everything = "\n\n".join(f"## {n}\n{t}" for n, t in DOCS.items())
    print(f"Stuff the whole library : ~{count_tokens(everything):,} tokens on the desk")

    index = BM25(DOCS)
    top = index.search(question, k=2)
    selected = "\n\n".join(f"## {n}\n{DOCS[n]}" for n in top)
    print(f"Retrieve top-2          : ~{count_tokens(selected):,} tokens  -> {top}")

    # Just-in-time: the model sees only the index (names + first words) first.
    listing = "\n".join(f"{n}: {DOCS[n][:40]}" for n in index.search(question, k=5))
    print(f"JIT: search result      : ~{count_tokens(listing):,} tokens, then reads 1 file\n")
    print(listing)
    print("\nLesson: less on the desk = cheaper, faster AND more accurate (less to get lost in).")
